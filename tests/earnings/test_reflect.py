import json

import pytest

from vantage_trader.earnings import cli, reflect
from vantage_trader.earnings.config import EngineInputError


def _write(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


def _lesson(lid, kind, status="hypothesis", statement="s"):
    return {"event": "lesson", "id": lid, "kind": kind, "statement": statement, "test": "t", "status": status,
            "ts": "2026-11-10T22:00:00Z"}


def _ev(lid, verdict, date="2026-11-10"):
    return {"event": "evidence", "id": lid, "date": date, "verdict": verdict, "ref": "X-1", "note": "n"}


def test_missing_ledger_is_empty(tmp_path):
    view = reflect.lessons_view(reflect.read_lessons(tmp_path / "none.jsonl"))
    assert view["apply_now"] == [] and view["being_tested"] == [] and view["retired"] == 0


def test_process_lessons_may_start_active_and_rule_lessons_may_not(tmp_path):
    ok = _write(tmp_path, "a.jsonl", [_lesson("L1", "execution", "active"), _lesson("H1", "rule")])
    view = reflect.lessons_view(reflect.read_lessons(ok))
    assert [r["id"] for r in view["apply_now"]] == ["L1"]
    assert [r["id"] for r in view["being_tested"]] == ["H1"]
    bad = _write(tmp_path, "b.jsonl", [_lesson("H1", "rule", "active")])
    with pytest.raises(EngineInputError, match="cannot start active"):
        reflect.read_lessons(bad)


def test_rule_lesson_cannot_be_adopted_without_approval(tmp_path):
    rows = [_lesson("H1", "risk"), {"event": "status", "id": "H1", "status": "adopted"}]
    with pytest.raises(EngineInputError, match="needs approved_by"):
        reflect.read_lessons(_write(tmp_path, "a.jsonl", rows))
    rows = [_lesson("H1", "risk"), {"event": "status", "id": "H1", "status": "active"}]
    with pytest.raises(EngineInputError, match="never set active"):
        reflect.read_lessons(_write(tmp_path, "b.jsonl", rows))
    rows = [_lesson("H1", "risk"), {"event": "status", "id": "H1", "status": "proposed"},
            {"event": "status", "id": "H1", "status": "adopted", "approved_by": "Brad 2026-11-13"}]
    state = reflect.fold_lessons(reflect.read_lessons(_write(tmp_path, "c.jsonl", rows)))
    assert state["H1"]["status"] == "adopted" and state["H1"]["approved_by"] == "Brad 2026-11-13"
    assert [r["id"] for r in reflect.lessons_view(reflect.read_lessons(tmp_path / "c.jsonl"))["apply_now"]] == ["H1"]


def test_tallies_and_ready_to_propose(tmp_path):
    rows = [_lesson("H1", "rule"), _lesson("H2", "rule"), _lesson("L1", "process", "active")]
    rows += [_ev("H1", "supports", f"2026-11-{10 + i:02d}") for i in range(6)] + [_ev("H1", "contradicts")] * 2
    rows += [_ev("H2", "supports")] * 2 + [_ev("H2", "contradicts")] * 3 + [_ev("H2", "neutral")]
    rows += [_ev("L1", "supports")] * 9
    state = reflect.fold_lessons(reflect.read_lessons(_write(tmp_path, "a.jsonl", rows)))
    assert (state["H1"]["supports"], state["H1"]["contradicts"]) == (6, 2)
    assert state["H1"]["ready_to_propose"] is True and state["H1"]["last_evidence"] == "2026-11-15"
    assert state["H2"]["ready_to_propose"] is False and state["H2"]["weak"] is True and state["H2"]["neutral"] == 1
    assert state["L1"]["ready_to_propose"] is False   # process lessons are never "proposed"


def test_bad_ledger_lines(tmp_path):
    for rows in ([{"event": "evidence", "id": "L9", "verdict": "supports"}],          # unknown lesson
                 [_lesson("L1", "process"), _lesson("L1", "process")],                 # duplicate id
                 [_lesson("L1", "process"), {"event": "evidence", "id": "L1", "verdict": "maybe"}],
                 [{"event": "lesson", "id": "L1", "kind": "vibes", "statement": "x"}],
                 [{"event": "lesson", "id": "L1", "kind": "process", "statement": " "}]):
        with pytest.raises(EngineInputError):
            reflect.read_lessons(_write(tmp_path, "x.jsonl", rows))


def _journal():
    base = {"order_id": None, "implied_move": None, "edge_ratio": None, "realized_move": None, "pnl": None, "notes": ""}
    return [
        {**base, "ts": "2026-11-10T19:42:34Z", "event": "entry_filled", "symbol": "AAA", "structure": "iron_fly",
         "price": 1.28, "quantity": 2, "direction": "credit", "implied_move": 0.10, "edge_ratio": 0.78},
        {**base, "ts": "2026-11-10T19:54:13Z", "event": "heal", "symbol": "AAA", "structure": "iron_fly",
         "price": 1.38, "quantity": 1, "pnl": -10.32, "heal": {"type": "partial_close", "as_event": "qty_adjust"},
         "notes": "x" * 400},
        {**base, "ts": "2026-11-11T14:50:00Z", "event": "exit_filled", "symbol": "AAA", "structure": "iron_fly",
         "price": 1.00, "quantity": 1, "pnl": 27.5, "realized_move": -0.07, "max_loss": 172},
    ]


def test_day_pack_separates_days_and_counts_adjust_cost():
    metrics_recs = [
        {"trade_id": "AAA-1", "record": "entry", "ts": "2026-11-10T19:42:34Z", "symbol": "AAA", "live": True,
         "execution": {"fill_vs_mid": 0.96, "reprices": 4}},
        {"trade_id": "ZZZ-P1", "record": "paper", "ts": "2026-11-11T14:55:00Z", "symbol": "ZZZ", "live": False,
         "skip_reason": "no edge", "pnl_mid_usd": 40.0},
    ]
    positions = {"open": [{"symbol": "AAA", "kind": "earnings", "structure": "iron fly", "quantity": 1,
                           "net_credit": 1.28, "max_loss_usd": 172, "breakevens": [10.7, 13.3],
                           "plan": {"exit": "next morning"}}], "risk": {"cap_usd": 650}}
    lessons = [_lesson("L1", "execution", "active")]
    d1 = reflect.day_pack("2026-11-10", _journal(), metrics_recs, positions, lessons)
    assert [d["decision"] for d in d1["decisions_to_grade"]] == ["entry_filled", "qty_adjust"]
    assert d1["realized_pnl_usd"] == {"exits": 0.0, "adjusts": -10.32, "total": -10.32}
    assert d1["closed_trades_today"] == [] and d1["execution"]["entries"]["avg_fill_vs_mid"] == 0.96
    assert len(d1["journal"]["qty_adjust"][0]["notes"]) <= reflect.NOTE_CHARS
    assert d1["open_positions"][0]["exit_plan"] == "next morning" and d1["risk"] == {"cap_usd": 650}
    assert d1["lessons"]["apply_now"][0]["id"] == "L1"
    d2 = reflect.day_pack("2026-11-11", _journal(), metrics_recs, positions, lessons)
    assert d2["realized_pnl_usd"]["exits"] == 27.5 and len(d2["closed_trades_today"]) == 1
    assert d2["paper_scored_today"][0]["symbol"] == "ZZZ" and d2["streaks"]["closed_trades"] == 1
    with pytest.raises(EngineInputError):
        reflect.day_pack("11/10/2026", [], [], None, [])


def test_cli_commands(tmp_path):
    j = _write(tmp_path, "journal.jsonl", _journal())
    l = _write(tmp_path, "lessons.jsonl", [_lesson("L1", "process", "active")])
    out, code = cli.run(["lessons", "--lessons", str(l)])
    assert code == 0 and out["apply_now"][0]["id"] == "L1"
    out, code = cli.run(["daily-review", "--date", "2026-11-10", "--journal", str(j), "--lessons", str(l),
                         "--metrics", str(tmp_path / "none.jsonl"), "--positions", str(tmp_path / "none.json")])
    assert code == 0 and out["date"] == "2026-11-10" and out["open_positions"] == []
