import pytest

from vantage_trader.earnings.config import EngineInputError
from vantage_trader.earnings.rules import circuit_breaker, exit_decision

from .factories import cfg, trade

ACCT = {"total_value": 750.0, "buying_power": 750.0}


# ------------------------------------------------------------ circuit breaker

def test_breaker_clear():
    cb = circuit_breaker(ACCT, trade("A", "iron_fly", 10, 8, 1), cfg())
    assert not cb["halted"] and cb["closed_trades"] == 1


def test_breaker_account_value():
    cb = circuit_breaker({"total_value": 399.99}, [], cfg())
    assert cb["halted"] and "account_value" in cb["reasons"][0]
    assert not circuit_breaker({"total_value": 400.0}, [], cfg())["halted"]


def test_breaker_two_consecutive_max_loss():
    ev = trade("A", "iron_fly", 15.0, 20.0, 1, max_loss=500) + trade("B", "iron_fly", 15.0, 19.6, 2, max_loss=500)
    cb = circuit_breaker(ACCT, ev, cfg())   # losses 500 and 460 (>= 0.9*500)
    assert cb["halted"] and cb["consecutive_max_losses"] == 2


def test_breaker_max_loss_streak_broken_by_smaller_loss():
    ev = (trade("A", "iron_fly", 15.0, 20.0, 1, max_loss=500) + trade("B", "iron_fly", 15.0, 16.0, 2, max_loss=500)
          + trade("C", "iron_fly", 15.0, 20.0, 3, max_loss=500))
    cb = circuit_breaker(ACCT, ev, cfg())
    assert cb["consecutive_max_losses"] == 1 and cb["consecutive_losses"] == 3 and cb["halted"]


def test_breaker_unknown_max_loss_is_conservative():
    ev = trade("A", "iron_fly", 15.0, 16.0, 1, max_loss=None) + trade("B", "iron_fly", 15.0, 16.0, 2, max_loss=None)
    assert circuit_breaker(ACCT, ev, cfg())["halted"]


def test_breaker_three_losses_and_win_resets():
    losses = sum((trade(s, "iron_fly", 10, 11, d, max_loss=1000) for s, d in (("A", 1), ("B", 2), ("C", 3))), [])
    assert circuit_breaker(ACCT, losses, cfg())["halted"]
    win = trade("D", "iron_fly", 10, 5, 4, max_loss=1000)
    cb = circuit_breaker(ACCT, losses + win, cfg())
    assert not cb["halted"] and cb["consecutive_losses"] == 0
    two = losses[2:]
    assert not circuit_breaker(ACCT, two, cfg())["halted"]


def test_breaker_debit_pnl_and_explicit_pnl():
    ev = (trade("A", "long_straddle", 4.0, 3.0, 1, max_loss=400) + trade("B", "long_straddle", 4.0, 3.0, 2, max_loss=400)
          + trade("C", "long_straddle", 4.0, 9.0, 3, max_loss=400, pnl=-1.0))
    cb = circuit_breaker(ACCT, ev, cfg())
    assert cb["consecutive_losses"] == 3


def test_breaker_reset_ts():
    losses = sum((trade(s, "iron_fly", 10, 11, d, max_loss=1000) for s, d in (("A", 1), ("B", 2), ("C", 3))), [])
    assert not circuit_breaker(ACCT, losses, cfg(circuit_reset_ts="2026-10-03T00:00:00Z"))["halted"]


# ------------------------------------------------------------ exits

FLY_LEGS = [
    {"option_id": "C202.5", "side_held": "short", "quantity": 1, "bid": 3.0, "ask": 3.2},
    {"option_id": "P202.5", "side_held": "short", "quantity": 1, "bid": 8.0, "ask": 8.4},
    {"option_id": "C222.5", "side_held": "long", "quantity": 1, "bid": 0.1, "ask": 0.2},
    {"option_id": "P182.5", "side_held": "long", "quantity": 1, "bid": 0.5, "ask": 0.7},
]


def fly(**over):
    p = {"symbol": "ARM", "structure": "iron_fly", "legs": FLY_LEGS, "entry_price": 15.8,
         "direction": "credit", "opened": "2026-11-04"}
    p.update(over)
    return p


def straddle(call=(4.9, 5.1), put=(1.0, 1.2), **over):
    p = {"symbol": "XYZ", "structure": "long_straddle", "entry_price": 4.0, "direction": "debit",
         "opened": "2026-11-04",
         "legs": [{"option_id": "C100", "side_held": "long", "quantity": 1, "bid": call[0], "ask": call[1]},
                  {"option_id": "P100", "side_held": "long", "quantity": 1, "bid": put[0], "ask": put[1]}]}
    p.update(over)
    return p


def snap(positions, as_of="2026-11-05T14:45:00Z", mso=15):
    return {"as_of": as_of, "minutes_since_open": mso, "positions": positions}


def test_amc_exit_next_session_after_10_minutes():
    out = exit_decision(snap([fly()]), cfg())
    assert len(out["actions"]) == 1
    a = out["actions"][0]
    assert a["direction"] == "debit"
    # mid value = 0.15 + 0.60 - 3.10 - 8.20 = -10.55 ; natural = 3.2 + 8.4 - 0.1 - 0.5 = 11.0
    assert a["limit_start"] == 10.55 and a["limit_worst"] == 11.0 and a["limit_step"] == 0.10
    sides = {l["option_id"]: l["side"] for l in a["close_legs"]}
    assert sides == {"C202.5": "buy", "P202.5": "buy", "C222.5": "sell", "P182.5": "sell"}
    assert all(l["position_effect"] == "close" for l in a["close_legs"])
    assert a["quantity"] == 1 and "post_report_session" in a["reason"]
    assert set(a) >= {"symbol", "close_legs", "direction", "limit_start", "limit_worst", "limit_step", "reason"}


def test_wait_until_10_minutes():
    out = exit_decision(snap([fly()], mso=5), cfg())
    assert out["actions"] == [] and "wait" in out["holds"][0]["reason"]


def test_hold_on_entry_day():
    out = exit_decision(snap([fly()], as_of="2026-11-04T20:30:00Z", mso=360), cfg())
    assert out["actions"] == [] and out["holds"][0]["symbol"] == "ARM"


def test_bmo_exits_same_day_as_report():
    p = fly(opened="2026-11-04", report_date="2026-11-05", timing="am")
    assert len(exit_decision(snap([p]), cfg())["actions"]) == 1


def test_amc_with_report_date_holds_on_report_day():
    p = fly(opened="2026-11-05", report_date="2026-11-05", timing="pm")
    out = exit_decision(snap([p], as_of="2026-11-05T20:00:00Z"), cfg())
    assert out["actions"] == []
    out = exit_decision(snap([p], as_of="2026-11-06T14:45:00Z"), cfg())
    assert len(out["actions"]) == 1


def test_expiry_day_always_exits():
    p = fly(opened="2026-11-05", report_date="2026-11-05", timing="pm", expiry="2026-11-05")
    out = exit_decision(snap([p], mso=2), cfg())
    assert len(out["actions"]) == 1 and out["actions"][0]["reason"].startswith("expiry_day")


def test_straddle_take_profit_immediately():
    out = exit_decision(snap([straddle()], as_of="2026-11-04T14:31:00Z", mso=1), cfg())
    a = out["actions"][0]
    assert a["reason"].startswith("take_profit") and a["direction"] == "credit"
    assert a["limit_start"] == 6.10 and a["limit_worst"] == 5.90
    assert {l["side"] for l in a["close_legs"]} == {"sell"}


def test_straddle_below_take_profit_holds_same_day():
    out = exit_decision(snap([straddle(call=(4.4, 4.6))], as_of="2026-11-04T14:31:00Z", mso=1), cfg())
    assert out["actions"] == []


def test_small_price_step():
    p = straddle(call=(1.0, 1.1), put=(0.9, 1.0))
    a = exit_decision(snap([p]), cfg())["actions"][0]
    assert a["limit_start"] == 2.0 and a["limit_step"] == 0.05


@pytest.mark.parametrize("bad", [
    {"as_of": "2026-11-05T14:45:00Z", "positions": []},                                   # no minutes
    snap([fly(legs=[{"option_id": "x", "side_held": "short", "bid": None, "ask": 1}])]),
    snap([fly(legs=[{"option_id": "x", "side_held": "sideways", "bid": 1, "ask": 1}])]),
    snap([fly(opened=None)]),
])
def test_exit_invalid(bad):
    with pytest.raises(EngineInputError):
        exit_decision(bad, cfg())
