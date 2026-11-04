import json

import pytest

from vantage_trader.earnings import journal as jr
from vantage_trader.earnings.config import EngineInputError
from vantage_trader.earnings.reconcile import reconcile

from .factories import cfg, trade


# ------------------------------------------------------------ journal

def test_append_and_read_roundtrip(tmp_path):
    p = tmp_path / "state" / "j.jsonl"
    jr.append_event(p, {"event": "scan", "notes": "x"})
    jr.append_event(p, {"event": "entry_filled", "symbol": "ARM", "price": 15.8})
    rows = jr.read_journal(p)
    assert [r["event"] for r in rows] == ["scan", "entry_filled"] and all("ts" in r for r in rows)
    assert len(p.read_text().splitlines()) == 2


def test_append_rejects_unknown_event(tmp_path):
    with pytest.raises(EngineInputError):
        jr.append_event(tmp_path / "j.jsonl", {"event": "yolo"})


def test_read_rejects_corrupt_line(tmp_path):
    p = tmp_path / "j.jsonl"
    p.write_text('{"event":"scan"}\nnot json\n')
    with pytest.raises(EngineInputError):
        jr.read_journal(p)


def test_missing_journal_is_empty(tmp_path):
    assert jr.read_journal(tmp_path / "nope.jsonl") == []


def test_closed_trades_pairing_and_pnl():
    ev = trade("ARM", "iron_fly", 15.8, 6.0, 1) + [
        {"ts": "2026-10-05T19:00:00Z", "event": "entry_filled", "symbol": "NVDA", "structure": "long_straddle",
         "price": 4.0, "quantity": 1}]
    trades = jr.closed_trades(ev)
    assert len(trades) == 1
    t = trades[0]
    assert t["pnl"] == pytest.approx(980.0) and t["direction"] == "credit" and t["max_loss"] == 500.0
    st = jr.open_state(ev)
    assert set(st["positions"]) == {"NVDA"}


def test_heal_events_count_as_their_as_event():
    ev = [{"ts": "t1", "event": "heal", "symbol": "ARM", "structure": "iron_fly", "price": 15.0, "quantity": 1,
           "heal": {"type": "orphan_position", "as_event": "entry_filled"}},
          {"ts": "t2", "event": "exit_filled", "symbol": "ARM", "price": 17.0, "quantity": 1}]
    assert jr.closed_trades(ev)[0]["pnl"] == pytest.approx(-200.0)


# ------------------------------------------------------------ reconcile

AS_OF = "2026-11-04T21:00:00Z"   # 13:00 PT


def rsnap(positions=(), orders=(), as_of=AS_OF):
    return {"as_of": as_of, "open_positions": list(positions), "recent_orders": list(orders)}


ENTRY = [{"ts": "2026-11-04T19:55:00Z", "event": "entry_filled", "symbol": "ARM", "structure": "iron_fly",
          "order_id": "o1", "price": 15.8, "quantity": 1}]


def types(out):
    return [i["type"] for i in out["issues"]]


def test_consistent():
    out = reconcile(rsnap([{"symbol": "ARM", "structure": "iron_fly", "quantity": 1}],
                          [{"order_id": "o1", "symbol": "ARM", "state": "filled", "position_effect": "open"}]),
                    ENTRY, cfg())
    assert out["consistent"] and out["issues"] == []


def test_orphan_position_and_heal_is_idempotent():
    s = rsnap([{"symbol": "NVDA", "structure": "iron_fly", "quantity": 1, "opened": "2026-11-03"}])
    out = reconcile(s, [], cfg())
    assert types(out) == ["orphan_position"]
    fix = out["issues"][0]["fix"]["journal_event"]
    assert fix["event"] == "heal" and fix["heal"]["as_event"] == "entry_filled"
    assert reconcile(s, out["journal_appends"], cfg())["consistent"]


def test_missing_entry_fill():
    j = [{"ts": "2026-11-04T19:55:00Z", "event": "entry_submitted", "symbol": "ARM", "structure": "iron_fly",
          "order_id": "o1", "price": 15.8, "quantity": 1, "edge_ratio": 0.77}]
    s = rsnap([{"symbol": "ARM", "structure": "iron_fly", "quantity": 1}],
              [{"order_id": "o1", "symbol": "ARM", "state": "filled", "position_effect": "open", "price": 15.6,
                "quantity": 1}])
    out = reconcile(s, j, cfg())
    assert types(out) == ["missing_fill"]
    ev = out["issues"][0]["fix"]["journal_event"]
    assert ev["heal"]["as_event"] == "entry_filled" and ev["price"] == 15.6 and ev["edge_ratio"] == 0.77
    assert reconcile(s, j + out["journal_appends"], cfg())["consistent"]


def test_missing_entry_fill_inferred_from_position():
    j = [{"ts": "t", "event": "entry_submitted", "symbol": "ARM", "order_id": "o9", "price": 15.8, "quantity": 1}]
    out = reconcile(rsnap([{"symbol": "ARM", "quantity": 1}]), j, cfg())
    assert types(out) == ["missing_fill"]


def test_missing_exit_fill():
    j = ENTRY + [{"ts": "2026-11-05T14:45:00Z", "event": "exit_submitted", "symbol": "ARM", "order_id": "x1"}]
    s = rsnap([], [{"order_id": "x1", "symbol": "ARM", "state": "filled", "position_effect": "close", "price": 5.0}],
              as_of="2026-11-05T15:00:00Z")
    out = reconcile(s, j, cfg())
    assert types(out) == ["missing_fill"]
    healed = j + out["journal_appends"]
    assert jr.closed_trades(healed)[0]["pnl"] == pytest.approx(1080.0)
    assert reconcile(s, healed, cfg())["consistent"]


def test_unjournaled_close_fill():
    s = rsnap([], [{"order_id": "x7", "symbol": "ARM", "state": "filled", "position_effect": "close", "price": 5.0}])
    out = reconcile(s, ENTRY, cfg())
    assert types(out) == ["missing_fill"]
    assert out["issues"][0]["fix"]["journal_event"]["heal"]["as_event"] == "exit_filled"


def test_stale_open_order():
    order = {"order_id": "o2", "symbol": "ARM", "state": "queued", "position_effect": "open",
             "created_at": "2026-11-04T19:00:00Z"}   # 11:00 PT
    out = reconcile(rsnap([], [order]), [], cfg())
    assert types(out) == ["stale_open_order"]
    fix = out["issues"][0]["fix"]
    assert fix["broker_action"] == {"action": "cancel_order", "order_id": "o2"}
    assert fix["journal_event"]["heal"]["as_event"] == "entry_cancelled"
    assert out["journal_appends"] == []          # cancel must be confirmed first
    early = reconcile(rsnap([], [order], as_of="2026-11-04T20:40:00Z"), [], cfg())  # 12:40 PT
    assert early["consistent"]
    closing = dict(order, position_effect="close")
    assert reconcile(rsnap([], [closing]), [], cfg())["consistent"]


def test_qty_mismatch():
    out = reconcile(rsnap([{"symbol": "ARM", "quantity": 2}]), ENTRY, cfg())
    assert types(out) == ["qty_mismatch"]
    healed = ENTRY + out["journal_appends"]
    assert reconcile(rsnap([{"symbol": "ARM", "quantity": 2}]), healed, cfg())["consistent"]


def test_journal_position_gone_at_broker():
    out = reconcile(rsnap([]), ENTRY, cfg())
    assert types(out) == ["qty_mismatch"]
    healed = ENTRY + out["journal_appends"]
    t = jr.closed_trades(healed)[0]
    assert t["pnl"] is None and jr.is_loss(t)
    assert reconcile(rsnap([]), healed, cfg())["consistent"]


def test_cancelled_order_housekeeping():
    j = [{"ts": "t", "event": "entry_submitted", "symbol": "ARM", "order_id": "o3"}]
    s = rsnap([], [{"order_id": "o3", "symbol": "ARM", "state": "cancelled", "position_effect": "open"}])
    out = reconcile(s, j, cfg())
    assert out["consistent"] and out["housekeeping"][0]["heal"]["as_event"] == "entry_cancelled"


def test_reconcile_invalid():
    with pytest.raises(EngineInputError):
        reconcile({"as_of": AS_OF, "open_positions": []}, [], cfg())
    with pytest.raises(EngineInputError):
        reconcile(rsnap([], [{"symbol": "ARM"}]), [], cfg())


def test_heal_events_are_valid_journal_lines(tmp_path):
    out = reconcile(rsnap([{"symbol": "NVDA", "quantity": 1}]), [], cfg())
    p = tmp_path / "j.jsonl"
    for e in out["journal_appends"]:
        jr.append_event(p, e)
    assert jr.read_journal(p)[0]["event"] == "heal"
    json.dumps(out)


# ------------------------------------------------------------ audit fixes

def test_iron_fly_without_direction_is_credit():
    ev = trade("ARM", "iron_fly", 15.0, 17.0, 1)
    assert "direction" not in ev[0]
    t = jr.closed_trades(ev)[0]
    assert t["direction"] == "credit" and t["pnl"] == pytest.approx(-200.0)


def test_direction_field_wins_over_structure():
    ev = trade("ARM", "weird", 15.0, 17.0, 1)
    ev[0]["direction"] = "debit"
    assert jr.closed_trades(ev)[0]["pnl"] == pytest.approx(200.0)
    ev = trade("ARM", "long_strangle", 4.0, 5.0, 1)
    assert jr.closed_trades(ev)[0]["pnl"] == pytest.approx(100.0)


def test_unknown_direction_pnl_unknown_counts_as_loss():
    ev = trade("ARM", None, 15.0, 10.0, 1)
    for e in ev:
        e.pop("structure")
    t = jr.closed_trades(ev)[0]
    assert t["direction"] is None and t["pnl"] is None and jr.is_loss(t)


def test_journal_symbols_normalised(tmp_path):
    p = tmp_path / "j.jsonl"
    jr.append_event(p, {"event": "entry_filled", "symbol": " arm ", "structure": "iron_fly", "price": 15})
    jr.append_event(p, {"event": "exit_filled", "symbol": "ARM", "price": 14})
    assert jr.closed_trades(jr.read_journal(p))[0]["symbol"] == "ARM"


def test_position_effect_from_legs():
    legs_open = [{"position_effect": "open"}, {"position_effect": "open"}]
    order = {"order_id": "o2", "symbol": "ARM", "state": "queued", "legs": legs_open,
             "created_at": "2026-11-04T19:00:00Z"}
    assert types(reconcile(rsnap([], [order]), [], cfg())) == ["stale_open_order"]
    closing = dict(order, legs=[{"position_effect": "close"}] * 2)
    assert reconcile(rsnap([], [closing]), [], cfg())["consistent"]
    fill = {"order_id": "x9", "symbol": "arm", "state": "filled", "price": 5.0,
            "legs": [{"position_effect": "close"}, {"position_effect": "close"}]}
    assert types(reconcile(rsnap([], [fill]), ENTRY, cfg())) == ["missing_fill"]
    mixed = dict(fill, legs=[{"position_effect": "close"}, {"position_effect": "open"}])
    assert types(reconcile(rsnap([], [mixed]), ENTRY, cfg())) == ["qty_mismatch"]   # not treated as close


def test_missing_broker_quantity_skips_qty_mismatch():
    out = reconcile(rsnap([{"symbol": "ARM", "structure": "iron_fly"}]), ENTRY + ENTRY, cfg())
    assert out["consistent"]


def test_orphan_heal_marks_reconstructed():
    out = reconcile(rsnap([{"symbol": " nvda ", "quantity": 1}]), [], cfg())
    ev = out["issues"][0]["fix"]["journal_event"]
    assert out["issues"][0]["symbol"] == "NVDA" and ev["provenance"] == "reconstructed"


def test_missing_fill_heal_carries_intent_fields():
    legs = [{"option_id": "C202.5", "side": "sell", "position_effect": "open"}]
    sub = {"ts": "2026-11-04T19:55:00Z", "event": "entry_submitted", "symbol": "ARM", "structure": "iron_fly",
           "order_id": "o1", "price": 15.8, "quantity": 1, "edge_ratio": 0.77, "implied_move": 0.095,
           "max_loss": 455.0, "direction": "credit", "report_date": "2026-11-04", "timing": "pm",
           "expiry": "2026-11-06", "opened": "2026-11-04", "ref_id": "r-123", "legs": legs}
    s = rsnap([{"symbol": "ARM", "quantity": 1}],
              [{"order_id": "o1", "symbol": "ARM", "state": "filled", "position_effect": "open", "price": 15.6}])
    ev = reconcile(s, [sub], cfg())["issues"][0]["fix"]["journal_event"]
    for k in ("report_date", "timing", "expiry", "opened", "ref_id", "legs", "max_loss", "direction",
              "structure", "implied_move", "edge_ratio"):
        assert ev[k] == sub[k], k
    assert ev["price"] == 15.6
    # inferred-from-position branch carries them too
    ev2 = reconcile(rsnap([{"symbol": "ARM", "quantity": 1}]), [sub], cfg())["issues"][0]["fix"]["journal_event"]
    assert ev2["ref_id"] == "r-123" and ev2["expiry"] == "2026-11-06"
