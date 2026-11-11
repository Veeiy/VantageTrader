"""The entry gate in code (P004) and the at-the-money implied move (P011)."""
import io
import json

import pytest

from vantage_trader.earnings import gate, projection
from vantage_trader.earnings.cli import main
from vantage_trader.earnings.config import EngineInputError

from .factories import cfg, trade

# Real case, 2026-11-11 07:05 PT re-quote (state/earnings/scan/2026-11-11/watchlist.json).
LUNR = {
    "symbol": "LUNR", "timing": "am", "spot": 12.17, "prev_close": 11.81, "K": 12,
    "call": {"bid": 0.84, "ask": 0.97}, "put": {"bid": 0.63, "ask": 0.75},
    "wings": {"call_strike": 13.5, "put_strike": 10.5,
              "call": {"bid": 0.32, "ask": 0.36}, "put": {"bid": 0.12, "ask": 0.23}},
    "hist_moves": [0.224211, -0.042857, 0.100462, 0.044174, 0.023543, 0.035988],
    "regime_20d": 0.0615, "flags": [], "sector_same_direction": False,
    "account_value": 1339, "open_risk_usd": 172,
}

# A wide fly (max loss above $350) on a $100 stock.
WIDE = {
    "symbol": "WIDE", "timing": "pm", "spot": 100.0, "prev_close": 100.0, "K": 100.0,
    "call": {"bid": 4.9, "ask": 5.1}, "put": {"bid": 4.9, "ask": 5.1},
    "wings": {"call_strike": 115.0, "put_strike": 85.0,
              "call": {"bid": 0.2, "ask": 0.3}, "put": {"bid": 0.2, "ask": 0.3}},
    "hist_moves": [0.05, -0.05, 0.05, -0.05], "regime_20d": 0.01, "flags": [],
    "account_value": 2000, "open_risk_usd": 0,
}


def cand(base=LUNR, **over):
    c = json.loads(json.dumps(base))
    c.update(over)
    return c


def run(c, events=None, **cfg_over):
    cfg_over.setdefault("name_risk_frac", 0.12)      # these cases were written at the v1.7 target
    return gate.evaluate(c, cfg(**cfg_over), events or [])


def g(rec, name):
    return next(x for x in rec["gates"] if x["gate"] == name)


# ------------------------------------------------------------ the LUNR fixture

def test_lunr_2026_11_11():
    rec, code = run(cand())
    assert code == 0 and rec["action"] == "sell" and rec["blocked_by"] == []
    m = rec["metrics"]
    assert m["avg_hist_move"] == pytest.approx(0.078539, abs=1e-6)
    assert m["implied"]["implied_move_raw"] == pytest.approx(0.85 * 1.595 / 12.17, abs=1e-6)
    assert m["edge_ratio"] == pytest.approx(0.702, abs=0.001)          # 0.705 from the raw straddle
    assert rec["band"] == "final_sweep"                                 # just above 0.70: not early
    assert m["spread_pct"]["straddle"] == pytest.approx(0.157, abs=0.001)
    assert m["spread_pct"]["worst"] == pytest.approx(0.174, abs=0.001)  # the put leg
    assert rec["risk"]["spread_band_cap"] == 350.0
    f = rec["fly"]
    assert f["credit_mid"] == pytest.approx(1.08) and f["credit_natural"] == pytest.approx(0.88)
    assert f["width"] == 1.5 and rec["breakevens"] == [10.92, 13.08]
    assert rec["max_loss"]["mid"] == pytest.approx(42.0) and rec["max_loss"]["natural"] == pytest.approx(62.0)
    assert rec["max_loss"]["floor"] == pytest.approx(50.64)            # at 0.92 x mid credit
    # v1.7: target 12% of $1,339 = $160.68 -> 3 contracts in all; no phase given = early = 1 now
    assert rec["contracts"] == 1 and rec["contracts_planned"] == 3 and rec["contracts_later"] == 2
    assert rec["sizing"]["target"] == pytest.approx(160.68) and rec["sizing"]["phase"] == "early"
    r = rec["risk"]
    assert r["risk_cap"] == 1000.0 and r["budget_before"] == 828.0
    assert r["this_trade_usd"] == pytest.approx(100.64) and r["budget_left"] == pytest.approx(727.36)
    assert [x["n"] for x in rec["gates"]] == list(range(1, 16))
    assert all(x["pass"] for x in rec["gates"])


def test_lunr_full_size_in_the_final_window():
    rec, code = run(cand(phase="final"))
    assert code == 0 and rec["contracts"] == 3 and rec["contracts_later"] == 0
    assert rec["max_loss"]["floor"] == pytest.approx(151.92)
    assert rec["max_loss"]["per_contract_floor"] == pytest.approx(50.64)
    assert rec["risk"]["this_trade_usd"] == pytest.approx(301.92)       # 3 x (50.64 + $50 reserve)


# ------------------------------------------------------------ P011

def test_p011_off_the_money_body_uses_atm_equivalent():
    spot, k, sigma = 100.0, 98.0, 0.08                          # body 2% under spot
    c_px, p_px = projection.call_put(spot, k, sigma)
    c = cand(WIDE, spot=spot, prev_close=spot, K=k,
             call={"bid": round(c_px - 0.01, 6), "ask": round(c_px + 0.01, 6)},
             put={"bid": round(p_px - 0.01, 6), "ask": round(p_px + 0.01, 6)},
             wings={"call_strike": 108.0, "put_strike": 88.0,
                    "call": {"bid": 0.5, "ask": 0.6}, "put": {"bid": 0.3, "ask": 0.4}})
    rec, _ = run(c)
    atm_value = 0.85 * projection.straddle(spot, spot, sigma) / spot
    im = rec["metrics"]["implied"]
    assert abs(im["implied_move"] - atm_value) < 0.001             # within 0.1 percentage points
    assert abs(im["implied_move"] - atm_value) < 1e-5
    assert im["implied_move_raw"] - atm_value > 0.0005               # the raw straddle overstates it
    assert im["body_offset_pct"] == pytest.approx(-0.02)


def test_p011_helper_at_the_money_is_unchanged():
    st = projection.straddle(50.0, 50.0, 0.1)
    im = gate.atm_implied_move(50.0, 50.0, st, 0.85)
    assert im["implied_move"] == pytest.approx(im["implied_move_raw"], abs=1e-6)
    assert gate.atm_implied_move(50.0, 45.0, 4.0, 0.85)["implied_move"] is None   # below intrinsic


# ------------------------------------------------------------ edge ratio and band

@pytest.mark.parametrize("ratio,band", [
    (0.50, "tight"), (0.70, "tight"), (0.7001, "final_sweep"), (0.85, "final_sweep"),
    (0.8501, "no_edge"), (1.2499, "no_edge"), (1.25, "long_straddle_off"), (2.0, "long_straddle_off"),
])
def test_edge_band_boundaries(ratio, band):
    assert gate.edge_band(ratio, cfg()) == band


def _moves_for(ratio):
    implied = gate.atm_implied_move(12.17, 12, 1.595, 0.85)["implied_move"]
    x = ratio * implied
    return [x, -x, x, -x, x, -x]


@pytest.mark.parametrize("ratio,passed,reason", [
    (0.69, True, None), (0.84, True, None), (0.86, False, "no_edge"),
    (1.24, False, "no_edge"), (1.26, False, "long_straddle_off"),
])
def test_edge_gate(ratio, passed, reason):
    rec, code = run(cand(hist_moves=_moves_for(ratio), regime_20d=0.001))
    assert g(rec, "edge_ratio")["pass"] is passed
    if not passed:
        assert code == 3 and rec["action"] == "no_trade" and rec["reason"] == reason
        assert rec["contracts"] == 0


def test_long_straddle_off_is_never_a_buy():
    rec, code = run(cand(hist_moves=_moves_for(1.6), regime_20d=0.001))
    assert code == 3 and rec["action"] == "no_trade" and rec["band"] == "long_straddle_off"
    assert rec["reason"] == "long_straddle_off"


# ------------------------------------------------------------ spread and the $350 band

@pytest.mark.parametrize("put,passed", [
    ({"bid": 0.70, "ask": 0.90}, True),     # 0.20 / 0.80 = 25.0%
    ({"bid": 0.70, "ask": 0.91}, False),    # 0.21 / 0.805 = 26.1%
])
def test_spread_25pct_boundary(put, passed):
    rec, _ = run(cand(put=put))
    assert g(rec, "atm_spread")["pass"] is passed
    if not passed:
        assert "spread_too_wide" in rec["blocked_by"]


def test_spread_uses_worst_leg():
    s = gate.spread_pcts((1.0, 1.0), (0.70, 0.91))
    assert s["worst"] == s["put"] > s["straddle"]


def test_max_loss_above_350_blocks_at_any_spread():
    # v1.6: max loss at the credit floor <= $350 per name, also under the 12% spread band
    rec, code = run(cand(WIDE, call={"bid": 4.7, "ask": 5.3}, put={"bid": 4.7, "ask": 5.3}))   # 0.6/5 = 12%
    assert rec["risk"]["spread_band_cap"] is None and rec["max_loss"]["floor"] > 350.0
    assert code == 3 and rec["reason"] == "name_risk_cap" and g(rec, "name_risk")["limit"] == 350.0


def test_spread_above_12pct_caps_max_loss_at_350():
    rec, code = run(cand(WIDE, call={"bid": 4.6, "ask": 5.4}, put={"bid": 4.6, "ask": 5.4}))   # 16%
    assert code == 3 and g(rec, "name_risk")["pass"] is False
    assert rec["reason"] == "name_risk_cap" and g(rec, "name_risk")["limit"] == 350.0
    assert rec["risk"]["spread_band_cap"] == 350.0
    # the same spread on a fly whose max loss fits under $350 passes, with one contract:
    # $282 is above the name target (12% of $2,000 = $240) but one contract is always allowed
    narrow = {"call_strike": 110.0, "put_strike": 90.0, "call": {"bid": 1.0, "ask": 1.2}, "put": {"bid": 1.0, "ask": 1.2}}
    rec, code = run(cand(WIDE, call={"bid": 4.6, "ask": 5.4}, put={"bid": 4.6, "ask": 5.4}, wings=narrow))
    assert code == 0 and rec["max_loss"]["floor"] <= 350.0 and rec["contracts"] == 1
    assert rec["sizing"]["target"] == 240.0


# ------------------------------------------------------------ regime guard

@pytest.mark.parametrize("regime,passed", [(0.0999, True), (0.10, False), (0.12, False)])
def test_regime_boundary(regime, passed):
    rec, _ = run(cand(hist_moves=[0.08, -0.08, 0.08, -0.08, 0.08, -0.08], regime_20d=regime))
    assert g(rec, "regime")["limit"] == pytest.approx(0.10)
    assert g(rec, "regime")["pass"] is passed


# ------------------------------------------------------------ intraday move

@pytest.mark.parametrize("move,sector,flags,passed", [
    (0.05, False, [], True),
    (-0.05, False, [], True),
    (0.0501, False, [], False),
    (0.055, True, [], True),
    (-0.055, True, [], True),
    (0.055, True, ["news_shock"], False),
    (0.055, True, ["big_intraday_move"], True),     # a price fact, not stock news
    (0.07, True, [], True),
    (0.0701, True, [], False),
    (0.10, True, [], False),
])
def test_intraday_boundaries(move, sector, flags, passed):
    rec, _ = run(cand(prev_close=12.17 / (1 + move), sector_same_direction=sector, flags=flags))
    assert g(rec, "intraday")["pass"] is passed


# ------------------------------------------------------------ the other gates

@pytest.mark.parametrize("spot,passed", [(10.0, True), (9.99, False)])
def test_price_boundary(spot, passed):
    rec, _ = run(cand(spot=spot, prev_close=spot))
    assert g(rec, "price")["pass"] is passed


@pytest.mark.parametrize("n,passed", [(4, True), (3, False)])
def test_history_boundary(n, passed):
    rec, _ = run(cand(hist_moves=[0.08, -0.08, 0.08, -0.08][:n]))
    assert g(rec, "history")["pass"] is passed


def test_tsla_never():
    rec, code = run(cand(symbol="tsla"))
    assert code == 3 and rec["reason"] == "blocklisted"


@pytest.mark.parametrize("flags", [["news_shock"], {"pending_litigation_ruling": True}])
def test_news_flag_blocks(flags):
    rec, code = run(cand(flags=flags))
    assert code == 3 and g(rec, "news")["pass"] is False


def test_flag_object_false_is_not_set():
    assert run(cand(flags={"news_shock": False}))[1] == 0


@pytest.mark.parametrize("value,passed", [(None, True), (False, True), (True, False), ("CPI tomorrow", False)])
def test_macro_veto(value, passed):
    rec, code = run(cand(macro_veto=value))
    assert g(rec, "macro_veto")["pass"] is passed and (code == 0) is passed


def test_circuit_breaker_input_account_and_journal():
    assert g(run(cand(circuit_breaker=True))[0], "circuit_breaker")["pass"] is False
    assert g(run(cand(account_value=399.99))[0], "circuit_breaker")["pass"] is False
    assert g(run(cand(account_value=400))[0], "circuit_breaker")["pass"] is True
    ev = trade("A", "iron_fly", 1.0, 2.0, 1, max_loss=100) + trade("B", "iron_fly", 1.0, 2.0, 2, max_loss=100)
    rec, code = run(cand(), events=ev)
    assert code == 3 and "2 consecutive max-loss trades" in g(rec, "circuit_breaker")["value"]


def test_sector_clash_only_when_given():
    assert g(run(cand())[0], "sector")["pass"] is True
    rec, code = run(cand(sector="Aerospace", sectors_entered_today=["aerospace "]))
    assert code == 3 and rec["reason"] == "same_sector_today"
    assert run(cand(sector="Aerospace", sectors_entered_today=["Utilities"]))[1] == 0


def test_no_wings_blocks():
    rec, code = run(cand(wings=None))
    assert code == 3 and rec["reason"] == "no_wings" and rec["fly"] is None


def test_inverted_wings_block():
    rec, code = run(cand(wings={"call_strike": 11.5, "put_strike": 10.5,
                                "call": {"bid": 0.9, "ask": 1.0}, "put": {"bid": 0.1, "ask": 0.2}}))
    assert code == 3 and rec["reason"] == "no_valid_wings"


def test_risk_budget_boundary():
    # needs 50.64 max loss at the floor + $50 reserve = 100.64
    rec, code = run(cand(open_risk_usd=1000 - 100.64))
    assert code == 0 and rec["risk"]["budget_left"] == pytest.approx(0.0)
    rec, code = run(cand(open_risk_usd=1000 - 100.63))
    assert code == 3 and rec["reason"] == "max_loss_exceeds_cap"


def test_risk_cap_is_93pct_of_account_value_when_smaller():
    rec, _ = run(cand(account_value=1000))
    assert rec["risk"]["risk_cap"] == 930.0 and rec["risk"]["budget_before"] == 758.0


# ------------------------------------------------------------ v1.7: contracts by risk, adds

def test_contracts_follow_the_name_target_not_the_trade_count():
    rec, _ = run(cand(open_risk_usd=0, phase="final"))
    assert rec["contracts"] == 3 and rec["closed_live_trades"] == 0      # no data phase any more
    rec, _ = run(cand(open_risk_usd=0, phase="final"), max_quantity=2)
    assert rec["contracts"] == 2 and rec["sizing"]["binding"] == "max_quantity"
    rec, _ = run(cand(open_risk_usd=0, phase="final", account_value=600))  # target $72 -> 1
    assert rec["contracts"] == 1
    rec, _ = run(cand(open_risk_usd=800, phase="final"))                   # budget $200 -> 1
    assert rec["contracts"] == 1 and rec["sizing"]["binding"] == "max_loss_exceeds_cap"


HELD = {"quantity": 1, "max_loss_usd": 44.0, "K": 12}


def test_add_in_the_final_window_fills_the_target():
    rec, code = run(cand(held=HELD, open_risk_usd=266, phase="final"))
    assert code == 0 and rec["contracts"] == 2                            # (160.68 - 44) / 50.64
    assert rec["max_loss"]["name_total_floor"] == pytest.approx(44 + 2 * 50.64)
    assert g(rec, "add_centered")["pass"] is True


def test_add_before_the_final_window_waits():
    rec, code = run(cand(held=HELD, open_risk_usd=266, phase="early"))
    assert code == 3 and rec["reason"] == "early_tranche_full" and rec["contracts"] == 0
    assert rec["sizing"]["planned"] == 2 and rec["sizing"]["now"] == 0


def test_add_needs_spot_at_the_body_strike():
    # 0.25 x straddle 1.595 = 0.399 of room around the body 12
    rec, code = run(cand(held=HELD, open_risk_usd=266, phase="final", spot=12.6, prev_close=12.4))
    assert code == 3 and rec["reason"] == "add_off_center"
    assert g(rec, "add_centered")["limit"] == pytest.approx(0.3988, abs=1e-4)
    rec, code = run(cand(held=dict(HELD, K=12.5), open_risk_usd=266, phase="final"))
    assert code == 3 and rec["reason"] == "add_different_body"


def test_add_skips_the_sector_rule_and_stops_at_the_target():
    rec, code = run(cand(held=HELD, open_risk_usd=266, phase="final", sector="space",
                         sectors_entered_today=["space"]))
    assert code == 0 and g(rec, "sector")["pass"] is True
    rec, code = run(cand(held={"quantity": 3, "max_loss_usd": 150.0, "K": 12}, open_risk_usd=400, phase="final"))
    assert code == 3 and rec["reason"] == "name_target_reached"


@pytest.mark.parametrize("bad", [
    {"held": {"max_loss_usd": 44, "K": 12}}, {"held": {"quantity": 1.5, "max_loss_usd": 44, "K": 12}},
    {"held": [1]}, {"phase": "later"},
])
def test_bad_held_or_phase_is_rejected(bad):
    with pytest.raises(EngineInputError):
        run(cand(**bad))


def test_phase_from_the_clock():
    from datetime import datetime, timezone
    c = cfg()
    assert gate.phase_now(c, datetime(2026, 11, 11, 19, 29, tzinfo=timezone.utc)) == "early"   # 11:29 PT
    assert gate.phase_now(c, datetime(2026, 11, 11, 19, 30, tzinfo=timezone.utc)) == "final"   # 11:30 PT


def test_every_failure_is_listed():
    rec, code = run(cand(symbol="TSLA", spot=9.0, prev_close=9.0, macro_veto=True))
    assert code == 3 and rec["reason"] == "blocklisted"
    assert {"blocklisted", "price_below_min", "macro_veto"} <= set(rec["blocked_by"])


@pytest.mark.parametrize("mutate", [
    lambda c: c.pop("spot"),
    lambda c: c.update(hist_moves="0.1"),
    lambda c: c.update(call={"bid": 1.0, "ask": 0.5}),
    lambda c: c.pop("regime_20d"),
    lambda c: c.pop("open_risk_usd"),
    lambda c: c.update(sector_same_direction="yes"),
    lambda c: c.update(flags=5),
    lambda c: c.update(wings={"call_strike": 13.5}),
    lambda c: c.update(macro_veto=3),
])
def test_bad_input(mutate):
    c = cand()
    mutate(c)
    with pytest.raises(EngineInputError):
        gate.evaluate(c, cfg(), [])


# ------------------------------------------------------------ CLI

def _call(capsys, argv):
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_cli_gate_file_exit_0(tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(LUNR))
    code, d = _call(capsys, ["gate", "--input", str(p), "--journal", str(tmp_path / "none.jsonl")])
    assert code == 0 and d["action"] == "sell" and d["journal"]["found"] is False


def test_cli_gate_stdin_blocked_exit_3(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(cand(macro_veto=True))))
    code, d = _call(capsys, ["gate", "--journal", str(tmp_path / "none.jsonl")])
    assert code == 3 and d["action"] == "no_trade" and d["reason"] == "macro_veto"


@pytest.mark.parametrize("argv_fn,stdin", [
    (lambda t: ["gate", "--input", str(t / "missing.json")], None),
    (lambda t: ["gate"], "{not json"),
    (lambda t: ["gate"], json.dumps({"symbol": "X"})),
])
def test_cli_gate_bad_input_exit_2(tmp_path, capsys, monkeypatch, argv_fn, stdin):
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    code, d = _call(capsys, argv_fn(tmp_path) + ["--journal", str(tmp_path / "none.jsonl")])
    assert code == 2 and "error" in d


def test_v18_default_target_is_a_fifth_of_the_account():
    # v1.8: 20% of $1,339 = $267.80 -> (267.8 - 44) / 50.64 = 4.4 -> 4 more on the held LUNR
    rec, code = gate.evaluate(cand(held=HELD, open_risk_usd=266, phase="final"), cfg(), [])
    assert code == 0 and rec["sizing"]["target"] == pytest.approx(267.8) and rec["contracts"] == 4
    assert rec["max_loss"]["name_total_floor"] <= 350.0

