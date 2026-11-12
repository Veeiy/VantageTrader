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
    # body 202.5 is 0.005% off the money: the at-the-money equivalent is almost the raw straddle
    assert r["implied_move_raw"] == pytest.approx(0.85 * 22.75 / 202.49, abs=1e-6)
    assert r["implied_move"] == pytest.approx(0.85 * 22.75 / 202.49, abs=1e-5)
    assert r["avg_hist_move"] == pytest.approx(0.44 / 6, abs=1e-6)
    assert r["edge_ratio"] == pytest.approx((0.44 / 6) / (0.85 * 22.75 / 202.49), abs=1e-4)
    assert r["band"] == "final_sweep"
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
    (1.25 * 0.034, "skip", "long_straddle_off"),   # long straddles are off (P010)
    (1.60 * 0.034, "skip", "long_straddle_off"),
])
def test_thresholds(avg, action, reason):
    d, _ = run([straddle_candidate([avg, -avg, avg, -avg])])
    r = row(d, "XYZ")
    assert (r["action"], r["skip_reason"]) == (action, reason)
    if action == "skip":
        assert d["order"] is None
    if action == "sell":
        assert d["order"]["structure"] == "iron_fly"


@pytest.mark.parametrize("over,reason", [
    ({"symbol": "TSLA"}, "blocklisted"),
    ({"symbol": "tsla"}, "blocklisted"),
    ({"verified": False}, "unverified_report_date"),
    ({"flags": ["pending_litigation_ruling"]}, "flagged:pending_litigation_ruling"),
    ({"spot": 9.5}, "price_below_min"),
    ({"chain_symbol": "TSLA"}, "blocklisted"),
    ({"chain_symbol": "NVDA"}, "symbol_mismatch"),
    ({"report_date": "2026-11-05"}, "report_not_imminent"),                 # pm tomorrow: too early
    ({"report_date": "2026-11-03"}, "report_not_imminent"),                 # already reported
    ({"timing": "am"}, "report_not_imminent"),                              # am today: move already happened
    ({"timing": "am", "report_date": "2026-11-06", "expiry": "2026-11-06"}, "report_not_imminent"),
    ({"expiry": "2026-11-04"}, "bad_expiry"),                               # pm: must be > report
    ({"expiry": "2026-11-12"}, "bad_expiry"),                               # > report + 7 days
    ({"expiry": "2026-11-11"}, None),                                       # exactly report + 7 -> ok
    ({"historical_moves": [0.05, 0.06, 0.07]}, "insufficient_history"),
    ({"chain": []}, "missing_atm_quotes"),
    ({"intraday_move": 0.051}, "intraday_move_too_large"),
    ({"intraday_move": -0.06}, "intraday_move_too_large"),
    ({"historical_moves": [0.08] * 6}, "negative_ev"),
    ({"chain": [r for r in chain_rows() if r["strike"] == 202.5]}, "no_valid_wings"),
])
def test_skip_reasons(over, reason):
    d, code = run([arm_candidate(**over)])
    assert code == 0
    assert row(d, over.get("symbol", "ARM").strip().upper())["skip_reason"] == reason
    if reason is not None:
        assert d["status"] == "no_trade" and d["order"] is None


def test_am_report_next_trading_day_and_same_day_expiry_allowed():
    d, _ = run([arm_candidate(timing="am", report_date="2026-11-05", expiry="2026-11-05")])
    assert row(d)["skip_reason"] is None and d["status"] == "trade"


def test_am_report_after_weekend_and_holiday():
    s = snapshot([arm_candidate(timing="am", report_date="2026-11-09", expiry="2026-11-13")])
    s["as_of"] = "2026-11-06T19:55:00Z"                              # Friday
    assert row(score(s, cfg(), [])[0])["skip_reason"] is None
    s = snapshot([arm_candidate(timing="am", report_date="2026-11-27", expiry="2026-11-30")])
    s["as_of"] = "2026-11-25T19:55:00Z"                              # Wed before Thanksgiving
    assert row(score(s, cfg(), [])[0])["skip_reason"] is None
    s["candidates"][0]["report_date"] = "2026-11-26"
    assert row(score(s, cfg(), [])[0])["skip_reason"] == "report_not_imminent"


def test_today_uses_market_timezone():
    s = snapshot()
    s["as_of"] = "2026-11-05T02:00:00Z"                              # 21:00 ET on Nov 4
    assert row(score(s, cfg(), [])[0])["skip_reason"] is None


def test_expiry_must_be_after_today():
    s = snapshot([arm_candidate(timing="am", report_date="2026-11-05", expiry="2026-11-04")])
    assert row(score(s, cfg(), [])[0])["skip_reason"] == "bad_expiry"


def test_symbol_normalisation():
    d, _ = run([arm_candidate(symbol=" tsla ")])
    assert row(d, "TSLA")["skip_reason"] == "blocklisted"
    d, _ = run([arm_candidate(symbol=" arm ", chain_symbol="Arm ")])
    assert row(d)["skip_reason"] is None and d["order"]["symbol"] == "ARM"
    s = snapshot(open_positions=[{"symbol": " arm", "structure": "iron_fly", "opened": "2026-11-03"}])
    s["account"]["open_risk_usd"] = 100.0
    assert row(score(s, cfg(), [])[0])["skip_reason"] == "already_open"


def test_spread_too_wide():
    rows = chain_rows()
    for r in rows:
        if r["strike"] == 202.5:
            r["put"]["bid"], r["put"]["ask"] = 9.8, 12.6   # 2.8/11.2 = 25.0% -> ok; wider -> skip
    d, _ = run([arm_candidate(chain=rows)])
    assert row(d)["skip_reason"] != "spread_too_wide"
    for r in rows:
        if r["strike"] == 202.5:
            r["put"]["bid"], r["put"]["ask"] = 9.7, 12.6   # 2.9/11.15 = 26.0%
    d, _ = run([arm_candidate(chain=rows)])
    assert row(d)["skip_reason"] == "spread_too_wide"


def test_spread_band_caps_max_loss_at_350():
    rows = chain_rows()
    for r in rows:
        if r["strike"] == 202.5:
            r["call"]["bid"], r["call"]["ask"] = 10.8, 12.2   # 1.4/11.5 = 12.17%: $350 band
    d, _ = run([arm_candidate(chain=rows)], tv=2000.0)
    assert row(d)["spread_band_cap"] == 350.0
    assert d["order"] is None or d["order"]["max_loss_worst"] <= 350.0
    d, _ = run(tv=2000.0)                                       # tight spread: no $350 cap
    assert "spread_band_cap" not in row(d) and d["order"]["max_loss_worst"] > 350.0


def test_no_open_position_limit_but_open_risk_counts():
    s = snapshot(open_positions=[{"symbol": "NVDA", "structure": "iron_fly", "opened": "2026-11-03"}])
    with pytest.raises(EngineInputError):                      # open risk must be given
        score(s, cfg(), [])
    s["account"]["open_risk_usd"] = 100.0
    d, _ = score(s, cfg(), [])
    assert d["status"] == "trade" and d["risk_cap"] == 597.5 and d["risk_cap_total"] == 697.5
    assert d["order"]["max_loss_worst"] <= 597.5 - 50.0
    s["account"]["open_risk_usd"] = 690.0
    assert row(score(s, cfg(), [])[0])["skip_reason"] == "max_loss_exceeds_cap"


def test_risk_cap_from_account_value_not_buying_power():
    d, _ = run(bp=100.0, tv=500.0)                              # cap 465 from account value
    assert d["risk_cap"] == 465.0 and d["status"] == "trade"
    d, _ = run(bp=500.0, tv=100.0)                              # halted: account < $400
    assert d["status"] == "halted"


def test_risk_cap_too_small():
    s = snapshot(tv=500.0)
    s["account"]["open_risk_usd"] = 400.0                       # 65 left < any fly + $50 reserve
    assert row(score(s, cfg(), [])[0])["skip_reason"] == "max_loss_exceeds_cap"


def test_intraday_sector_band_and_regime():
    assert row(run([arm_candidate(intraday_move=0.06, sector_same_direction=True)])[0])["skip_reason"] is None
    assert row(run([arm_candidate(intraday_move=0.071, sector_same_direction=True)])[0])["skip_reason"] \
        == "intraday_move_too_large"
    assert row(run([arm_candidate(intraday_move=0.055, sector_same_direction=True,
                                  flags=["big_intraday_move"])])[0])["skip_reason"] is None
    avg = 0.44 / 6
    assert row(run([arm_candidate(regime_20d=1.25 * avg)])[0])["skip_reason"] == "regime_guard"
    assert row(run([arm_candidate(regime_20d=1.24 * avg)])[0])["skip_reason"] is None


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
    lambda s: s["candidates"][0].update(chain_symbol=5),
])
def test_invalid_snapshot(mutate):
    s = snapshot()
    mutate(s)
    with pytest.raises(EngineInputError):
        score(s, cfg(), [])


def test_expiry_on_early_close_day_is_bad():
    s = snapshot([arm_candidate(report_date="2026-11-25", expiry="2026-11-27")])
    s["as_of"] = "2026-11-25T19:55:00Z"
    assert row(score(s, cfg(), [])[0])["skip_reason"] == "bad_expiry"
    assert row(score(s, cfg(market_early_closes=[]), [])[0])["skip_reason"] is None
    s["candidates"][0]["expiry"] = "2026-11-30"
    assert row(score(s, cfg(), [])[0])["skip_reason"] is None


def test_order_has_stripped_order_legs_and_reserve():
    d, _ = run()
    o = d["order"]
    assert o["order_legs"] == [{"option_id": l["option_id"], "side": l["side"], "position_effect": "open"}
                               for l in o["legs"]]
    assert all(set(l) == {"option_id", "side", "position_effect"} for l in o["order_legs"])
    assert o["exit_slippage_reserve"] == 50.0 and o["risk_cap_effective"] == 647.5
    assert o["max_loss_worst"] <= d["risk_cap"] - 50.0 * o["quantity"]


def _with_open_risk(tv, open_risk):
    s = snapshot(tv=tv)
    s["account"]["open_risk_usd"] = open_risk
    return s


def test_reserve_pushes_wide_fly_over_cap():
    # budget 465 - 186 = 279; W=15 max loss 215: fits with reserve 50 (265) but not with 70 (285)
    d, _ = score(_with_open_risk(500.0, 186.0), cfg(), [])
    assert d["order"]["wing_width"] == 15.0
    d, _ = score(_with_open_risk(500.0, 186.0), cfg(exit_slippage_reserve=70.0), [])
    assert d["order"]["wing_width"] == 10.0
    d, _ = score(_with_open_risk(500.0, 353.4), cfg(), [])    # budget 111.6 < 105 + 50
    assert row(d)["skip_reason"] == "max_loss_exceeds_cap"


def test_contracts_by_risk_not_one_per_name():
    # Brad, 2026-11-12: "Get rid of the one contract per name rule". A cheap fly (about $26 of
    # max loss a contract) on a $750 account gets the contracts its 20% target allows.
    chain = [
        {"strike": 20.0, "call": {"id": "C20", "bid": 0.50, "ask": 0.52}, "put": {"id": "P20", "bid": 0.48, "ask": 0.50}},
        {"strike": 19.0, "call": {"id": "C19", "bid": 1.20, "ask": 1.30}, "put": {"id": "P19", "bid": 0.10, "ask": 0.12}},
        {"strike": 21.0, "call": {"id": "C21", "bid": 0.10, "ask": 0.12}, "put": {"id": "P21", "bid": 1.20, "ask": 1.30}},
    ]
    c = straddle_candidate([0.02, -0.03, 0.01, -0.02, 0.03, 0.02], spot=20.0, chain=chain)
    d, code = run([c])
    o = d["order"]
    assert code == 0 and d["status"] == "trade"
    assert d["contracts_limit"] == 10
    assert o["quantity"] > 1                                    # no one-contract limit
    unit = o["max_loss_worst"] / o["quantity"]
    assert abs(o["max_loss_worst"] - 150.0) <= unit             # about the name target: 20% of $750
    assert o["max_loss_worst"] <= 350.0                         # the per-name cap still holds
    assert o["max_loss_worst"] + 50.0 * o["quantity"] <= d["risk_cap"]
    s = row(d, "XYZ")["sizing"]
    assert s["contracts"] == o["quantity"] and s["planned"] >= o["quantity"]


def test_expensive_fly_still_gets_one_contract():
    d, _ = run()                                                # ARM: one contract is over the target
    assert d["order"]["quantity"] == 1 and row(d)["sizing"]["contracts"] == 1
