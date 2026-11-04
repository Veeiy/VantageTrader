import pytest

from vantage_trader.earnings.config import EngineInputError
from vantage_trader.earnings.scoring import score

from .factories import arm_candidate, cfg, chain_rows, snapshot, straddle_candidate, trade


def run(cands=None, events=None, **kw):
    decision, code = score(snapshot(cands, **kw), cfg(), events or [])
    return decision, code


def row(decision, sym="ARM"):
    return next(r for r in decision["ranked"] if r["symbol"] == sym)


def test_arm_example_metrics_and_trade():
    d, code = run()
    r = row(d)
    assert code == 0 and d["status"] == "trade"
    assert r["implied_move"] == pytest.approx(0.85 * 22.75 / 202.49, abs=1e-6)
    assert r["avg_hist_move"] == pytest.approx(0.44 / 6, abs=1e-6)
    assert r["edge_ratio"] == pytest.approx((0.44 / 6) / (0.85 * 22.75 / 202.49), abs=1e-4)
    assert r["action"] == "sell" and r["skip_reason"] is None
    o = d["order"]
    assert o["structure"] == "iron_fly" and o["direction"] == "credit" and o["quantity"] == 1
    assert o["cancel_by"] == "12:50 America/Los_Angeles" and o["expiry"] == "2026-11-06"
    assert o["max_loss_worst"] <= d["risk_cap"] == 697.5
    for k in ("symbol", "structure", "quantity", "direction", "expiry", "legs", "limit_start",
              "limit_floor", "limit_step", "max_loss", "max_profit", "breakevens", "hist_win_rate", "cancel_by"):
        assert k in o
    for k in ("symbol", "edge_ratio", "implied_move", "avg_hist_move", "action", "skip_reason", "ev_per_dollar_risk"):
        assert k in r


# implied for straddle_candidate = 0.85 * 4.0 / 100 = 0.034
@pytest.mark.parametrize("avg,action,reason", [
    (0.85 * 0.034, "sell", None),          # exactly sell_max_ratio
    (0.86 * 0.034, "skip", "no_edge"),
    (1.24 * 0.034, "skip", "no_edge"),
    (1.25 * 0.034, "buy", None),           # exactly buy_min_ratio
    (1.60 * 0.034, "buy", None),
])
def test_thresholds(avg, action, reason):
    d, _ = run([straddle_candidate([avg, -avg, avg, -avg])])
    r = row(d, "XYZ")
    assert (r["action"], r["skip_reason"]) == (action, reason)
    if action == "buy":
        assert d["order"]["structure"] == "long_straddle" and d["order"]["direction"] == "debit"
    if action == "sell":
        assert d["order"]["structure"] == "iron_fly"


@pytest.mark.parametrize("over,reason", [
    ({"symbol": "TSLA"}, "blocklisted"),
    ({"symbol": "tsla"}, "blocklisted"),
    ({"verified": False}, "unverified_report_date"),
    ({"flags": ["pending_litigation_ruling"]}, "flagged:pending_litigation_ruling"),
    ({"spot": 9.5}, "price_below_min"),
    ({"expiry": "2026-11-04"}, "expiry_not_after_report"),                 # pm: must be > report
    ({"timing": "am", "expiry": "2026-11-03"}, "expiry_not_after_report"),
    ({"historical_moves": [0.05, 0.06, 0.07]}, "insufficient_history"),
    ({"chain": []}, "missing_atm_quotes"),
    ({"intraday_move": 0.051}, "intraday_move_too_large"),
    ({"intraday_move": -0.06}, "intraday_move_too_large"),
    ({"historical_moves": [0.08] * 6}, "negative_ev"),
    ({"chain": [r for r in chain_rows() if r["strike"] == 202.5]}, "no_valid_wings"),
])
def test_skip_reasons(over, reason):
    d, code = run([arm_candidate(**over)])
    assert code == 0 and d["status"] == "no_trade" and d["order"] is None
    assert row(d, over.get("symbol", "ARM").upper())["skip_reason"] == reason


def test_am_expiry_same_day_is_allowed():
    d, _ = run([arm_candidate(timing="am", report_date="2026-11-06", expiry="2026-11-06")])
    assert row(d)["skip_reason"] != "expiry_not_after_report"


def test_spread_too_wide():
    rows = chain_rows()
    for r in rows:
        if r["strike"] == 202.5:
            r["put"]["bid"], r["put"]["ask"] = 10.5, 12.0   # 1.5/11.25 = 13.3%
    d, _ = run([arm_candidate(chain=rows)])
    assert row(d)["skip_reason"] == "spread_too_wide"


def test_call_spread_too_wide():
    rows = chain_rows()
    for r in rows:
        if r["strike"] == 202.5:
            r["call"]["bid"], r["call"]["ask"] = 10.8, 12.2   # 1.4/11.5 = 12.17% -> skip
    d, _ = run([arm_candidate(chain=rows)])
    assert row(d)["skip_reason"] == "spread_too_wide"


def test_open_position_limit():
    d, _ = run(open_positions=[{"symbol": "NVDA", "structure": "iron_fly", "opened": "2026-11-03"}])
    assert row(d)["skip_reason"] == "open_position_limit" and d["order"] is None


def test_risk_cap_too_small():
    d, _ = run(bp=100.0, tv=500.0)
    assert row(d)["skip_reason"] == "max_loss_exceeds_cap"


def test_no_buying_power():
    d, _ = run([straddle_candidate([0.06] * 4)], bp=0.0, tv=500.0)
    assert row(d, "XYZ")["skip_reason"] == "no_buying_power"


def test_ranking_takes_best_ev():
    d, _ = run([arm_candidate(), straddle_candidate([0.06, -0.07, 0.065, -0.06], symbol="ABC"),
                arm_candidate(symbol="TSLA")])
    tradeable = [r for r in d["ranked"] if r["action"] != "skip"]
    assert [r["symbol"] for r in tradeable] == sorted(
        [r["symbol"] for r in tradeable], key=lambda s: -row(d, s)["ev_per_dollar_risk"])
    assert d["order"]["symbol"] == tradeable[0]["symbol"]
    assert d["ranked"][-1]["symbol"] == "TSLA"


def test_halted_by_account_value():
    d, code = run(tv=399.0)
    assert code == 3 and d["status"] == "halted" and d["order"] is None
    assert d["ranked"]  # still reported


def test_halted_by_losses():
    ev = (trade("A", "iron_fly", 10, 12, 1, max_loss=1000) + trade("B", "iron_fly", 10, 12, 2, max_loss=1000)
          + trade("C", "iron_fly", 10, 12, 3, max_loss=1000))
    d, code = run(events=ev)
    assert code == 3 and "3 losing trades" in d["reason"]


def test_no_candidates():
    d, code = run([])
    assert code == 0 and d["status"] == "no_trade" and d["ranked"] == []


@pytest.mark.parametrize("mutate", [
    lambda s: s.pop("account"),
    lambda s: s.update(as_of="yesterday"),
    lambda s: s["candidates"][0].update(timing="after"),
    lambda s: s["candidates"][0].update(spot="202"),
    lambda s: s["candidates"][0].update(intraday_move=None),
    lambda s: s["candidates"][0].update(verified="yes"),
    lambda s: s["candidates"][0].pop("chain"),
])
def test_invalid_snapshot(mutate):
    s = snapshot()
    mutate(s)
    with pytest.raises(EngineInputError):
        score(s, cfg(), [])
