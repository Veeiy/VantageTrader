import math

import pytest

from vantage_trader.earnings import cli
from vantage_trader.earnings import projection as pj
from vantage_trader.earnings.config import EngineInputError


def test_call_put_parity_and_limits():
    c, p = pj.call_put(11.66, 12.0, 0.088)
    assert c - p == pytest.approx(11.66 - 12.0, abs=1e-9)
    assert pj.call_put(13.0, 12.0, 0.0) == (1.0, 0.0)
    assert pj.call_put(11.0, 12.0, 0.0) == (0.0, 1.0)
    # at the money the straddle is close to 0.8 * spot * sigma
    assert pj.straddle(100.0, 100.0, 0.10) == pytest.approx(7.97, abs=0.02)
    with pytest.raises(EngineInputError):
        pj.call_put(0.0, 12.0, 0.1)


def test_implied_sigma_round_trip_and_intrinsic_floor():
    for spot, strike, sig in ((12.13, 12.0, 0.135), (23.42, 23.5, 0.11), (58.5, 59.0, 0.06), (171.3, 192.5, 0.2)):
        assert pj.implied_sigma(spot, strike, pj.straddle(spot, strike, sig)) == pytest.approx(sig, abs=1e-5)
    assert pj.implied_sigma(20.0, 23.0, 3.0) is None      # exactly intrinsic
    assert pj.implied_sigma(20.0, 23.0, 2.5) is None      # below intrinsic (stale print)


def test_ambient_daily_variance_from_term_structure():
    # front 156.3% for 3 calendar days, back 110% for 10 days, 5 trading days between
    v = pj.ambient_daily_variance(1.563, 3, 1.10, 10, 5)
    assert v == pytest.approx((1.10 ** 2 * 10 - 1.563 ** 2 * 3) / 365 / 5, rel=1e-12)
    assert math.sqrt(v) == pytest.approx(0.0511, abs=0.0005)
    with pytest.raises(EngineInputError):
        pj.ambient_daily_variance(1.0, 10, 1.0, 3, 5)
    with pytest.raises(EngineInputError):
        pj.ambient_daily_variance(3.0, 3, 1.0, 10, 5)     # inverted beyond repair


POS = {"symbol": "AAA", "body": 12.0, "call_wing": 15.0, "put_wing": 9.0, "credit": 1.28, "quantity": 1,
       "close": 12.15, "spot_base": 11.66, "sigma_base": 0.088, "spots": [11.0, 11.66, 12.0],
       "sigmas": [0.07, 0.088, 0.115], "slippage_usd": 5.0}


def test_project_base_and_grid():
    out = pj.project(POS)
    legs = out["base"]["legs"]
    assert legs["close_cost"] == pytest.approx(legs["body_call"] + legs["body_put"] - legs["wing_call"] - legs["wing_put"], abs=2e-4)
    assert out["base"]["pnl_mid_usd"] == pytest.approx((1.28 - out["base"]["close_cost"]) * 100, abs=0.02)
    assert out["base"]["pnl_after_slippage_usd"] == pytest.approx(out["base"]["pnl_mid_usd"] - 5.0, abs=1e-9)
    assert len(out["grid_pnl_mid_usd"]) == 3 and len(out["grid_pnl_mid_usd"][0]) == 4
    row_body = out["grid_pnl_mid_usd"][2]                  # spot at the body: more vol = worse
    assert row_body["sigma_0.070"] > row_body["sigma_0.088"] > row_body["sigma_0.115"]
    lo, hi = out["range_pnl_mid_usd"]
    assert lo <= out["base"]["pnl_mid_usd"] <= hi
    with pytest.raises(EngineInputError):
        pj.project({"symbol": "AAA"})


def test_attribute_parts_sum_to_the_error():
    s1, g1 = 11.20, 0.10
    legs = pj.fly_close_cost(s1, 12.0, 15.0, 9.0, g1)
    actual = {"spot": s1, "straddle_mid": legs["body_call"] + legs["body_put"],
              "close_cost_mid": legs["close_cost"] + 0.03, "fill_debit": legs["close_cost"] + 0.08}
    out = pj.attribute(POS, actual)
    parts = out["from_spot_usd"] + out["from_vol_usd"] + out["from_skew_and_quotes_usd"]
    assert parts == pytest.approx(out["error_usd"], abs=0.03)
    assert out["actual"]["sigma_implied"] == pytest.approx(g1, abs=1e-4)
    assert out["from_skew_and_quotes_usd"] == pytest.approx(-3.0, abs=0.02)
    assert out["ratios"]["sigma_actual_over_projected"] == pytest.approx(g1 / 0.088, abs=1e-3)
    # after hours moved 12.15 -> 11.66 (-0.49); the exit at 11.20 is -0.95: 194% of that move
    assert out["ratios"]["share_of_after_hours_move_kept"] == pytest.approx(0.95 / 0.49, abs=1e-3)
    assert out["fill"]["slippage_vs_mid_usd"] == pytest.approx(5.0, abs=0.02)
    assert out["error_usd"] == pytest.approx(out["actual"]["pnl_mid_usd"] - out["projected"]["pnl_mid_usd"], abs=0.02)


def test_attribute_handles_a_print_below_intrinsic():
    out = pj.attribute(POS, {"spot": 10.0, "straddle_mid": 1.9, "close_cost_mid": 1.9})
    assert out["actual"]["sigma_implied"] is None and out["from_vol_usd"] is None
    with pytest.raises(EngineInputError):
        pj.attribute(POS, {"spot": 10.0})


def test_cli_project_and_check(tmp_path):
    import json
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps([POS]))
    out, code = cli.run(["project", "--input", str(inp)])
    assert code == 0 and out["projections"][0]["symbol"] == "AAA"
    legs = pj.fly_close_cost(11.5, 12.0, 15.0, 9.0, 0.09)
    act = tmp_path / "act.json"
    act.write_text(json.dumps({"AAA": {"spot": 11.5, "straddle_mid": legs["body_call"] + legs["body_put"],
                                       "close_cost_mid": legs["close_cost"]}}))
    out, code = cli.run(["project-check", "--input", str(inp), "--actual", str(act)])
    assert code == 0 and out["checks"][0]["from_skew_and_quotes_usd"] == pytest.approx(0.0, abs=0.02)
    act.write_text(json.dumps({"ZZZ": {}}))
    with pytest.raises(EngineInputError):
        cli.run(["project-check", "--input", str(inp), "--actual", str(act)])
