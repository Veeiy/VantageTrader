from pathlib import Path

import pytest

from vantage_trader.earnings.calibrate import calibrate
from vantage_trader.earnings.config import DEFAULTS, ConfigError, load_config, validate

from .factories import cfg, trade

REPO = Path(__file__).resolve().parents[2]


def sells(n, realized_over_implied, edge=0.8, implied=0.10):
    ev = []
    for i in range(n):
        ev += trade(f"S{i}", "iron_fly", 15.0, 14.0, i + 1, implied=implied, edge=edge,
                    realized=realized_over_implied * implied * (-1) ** i)
    return ev


def buys(n, realized_over_implied, edge=1.5, implied=0.05):
    ev = []
    for i in range(n):
        ev += trade(f"B{i}", "long_straddle", 4.0, 3.0, i + 1, implied=implied, edge=edge,
                    realized=realized_over_implied * implied)
    return ev


# ------------------------------------------------------------ calibrate

def test_min_trades_guard():
    out = calibrate(sells(7, 2.0), cfg())
    assert out["closed_trades"] == 7 and out["diff"] == {} and out["proposed"] == out["current"]
    assert "need >= 8" in out["reason"] and out["writes_config"] is False


def test_sell_threshold_shrinks_toward_observed():
    out = calibrate(sells(8, 0.96), cfg())   # bias 1.2 -> raw 0.7083, weight 0.5 -> 0.779 -> 0.78
    assert out["proposed"]["sell_max_ratio"] == 0.78
    assert out["diff"] == {"sell_max_ratio": {"from": 0.85, "to": 0.78}}
    s = out["stats"]["iron_fly"]
    assert s["trades"] == 8 and s["win_rate"] == 1.0 and s["avg_pnl"] == 100.0
    assert s["avg_realized_over_implied"] == pytest.approx(0.96)


def test_bounds_clamped():
    out = calibrate(sells(8, 3.0) + buys(8, 0.1), cfg())
    assert out["proposed"]["sell_max_ratio"] == 0.70
    assert out["proposed"]["buy_min_ratio"] == 1.60
    out = calibrate(sells(8, 0.01), cfg())
    assert out["proposed"]["sell_max_ratio"] == 0.95


def test_no_change_when_forecast_accurate():
    out = calibrate(sells(10, 0.8), cfg())
    assert out["diff"] == {} and out["reason"] == "no change warranted"


def test_side_without_trades_unchanged():
    out = calibrate(sells(8, 1.6), cfg())
    assert out["proposed"]["buy_min_ratio"] == 1.25


# ------------------------------------------------------------ config

def test_empty_config_gives_defaults(tmp_path):
    p = tmp_path / "e.yaml"
    p.write_text("")
    c = load_config(p)
    assert c["max_loss_abs"] == 700.0 and c["blocklist"] == ["TSLA"] and c["min_history"] == 4


def test_repo_config_matches_defaults():
    c = load_config(REPO / "config" / "earnings.yaml")
    assert c == validate({})
    assert set(c) == set(DEFAULTS)


def test_missing_config_file():
    with pytest.raises(ConfigError):
        load_config("/nonexistent/earnings.yaml")
    assert load_config("/nonexistent/earnings.yaml", must_exist=False)["sell_max_ratio"] == 0.85


@pytest.mark.parametrize("bad", [
    {"max_los_abs": 500},
    {"max_loss_abs": 800},
    {"max_loss_bp_frac": 0.99},
    {"max_open_positions": 2},
    {"min_price": 5},
    {"max_spread_pct": 0.2},
    {"min_account_value": 300},
    {"max_consecutive_losses": 4},
    {"sell_max_ratio": 0.60},
    {"buy_min_ratio": 1.8},
    {"cancel_by": "13:30 America/Los_Angeles"},
    {"cancel_by": "noon"},
    {"wing_widths_pct": []},
    {"straddle_factor": "high"},
    {"min_history": 2.5},
    {"sell_max_ratio_bounds": [0.5, 0.95]},
])
def test_invalid_config(bad):
    with pytest.raises(ConfigError):
        validate(bad)


def test_config_may_tighten_and_tsla_forced():
    c = validate({"max_loss_abs": 500, "blocklist": ["gme"], "cancel_by": "12:30 America/Los_Angeles"})
    assert c["max_loss_abs"] == 500.0 and c["blocklist"] == ["GME", "TSLA"]
