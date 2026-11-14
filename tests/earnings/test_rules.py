import pytest

from vantage_trader.earnings.config import EngineInputError
from datetime import date

from vantage_trader.earnings.rules import circuit_breaker, exit_decision, next_trading_day

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


# ------------------------------------------------------------ trading calendar

def test_next_trading_day_skips_weekends_and_holidays():
    c = cfg()
    assert next_trading_day(date(2026, 11, 4), c) == date(2026, 11, 5)
    assert next_trading_day(date(2026, 11, 6), c) == date(2026, 11, 9)      # Fri -> Mon
    assert next_trading_day(date(2026, 11, 25), c) == date(2026, 11, 27)    # Thanksgiving
    assert next_trading_day(date(2026, 7, 2), c) == date(2026, 7, 6)        # Jul 3 observed
    assert next_trading_day(date(2026, 11, 25), cfg(market_holidays=[])) == date(2026, 11, 26)


# ------------------------------------------------------------ exits

def L(oid, side, typ, strike, bid, ask, qty=1):
    return {"option_id": oid, "side_held": side, "type": typ, "strike": strike, "quantity": qty,
            "bid": bid, "ask": ask}


FLY_LEGS = [
    L("C202.5", "short", "call", 202.5, 3.0, 3.2),
    L("P202.5", "short", "put", 202.5, 8.0, 8.4),
    L("C222.5", "long", "call", 222.5, 0.1, 0.2),
    L("P182.5", "long", "put", 182.5, 0.5, 0.7),
]


def fly(**over):
    p = {"symbol": "ARM", "structure": "iron_fly", "legs": FLY_LEGS, "entry_price": 15.8,
         "direction": "credit", "opened": "2026-11-04", "expiry": "2026-11-06"}
    p.update(over)
    return p


def straddle(call=(4.9, 5.1), put=(1.0, 1.2), **over):
    p = {"symbol": "XYZ", "structure": "long_straddle", "entry_price": 4.0, "direction": "debit",
         "opened": "2026-11-04", "expiry": "2026-11-06",
         "legs": [L("C100", "long", "call", 100.0, *call), L("P100", "long", "put", 100.0, *put)]}
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
    assert a["width_cap"] == 20.0 and a["leg_qty_mismatch"] is False
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


def test_expiry_required():
    p = fly()
    p.pop("expiry")
    with pytest.raises(EngineInputError):
        exit_decision(snap([p]), cfg())


def test_reconstructed_position_exits_same_day():
    p = fly(opened="2026-11-05", provenance="reconstructed")
    out = exit_decision(snap([p]), cfg())
    assert len(out["actions"]) == 1 and "reconstructed" in out["actions"][0]["reason"]


def test_unknown_opened_exits():
    p = fly()
    p.pop("opened")
    assert len(exit_decision(snap([p]), cfg())["actions"]) == 1


def test_unknown_provenance_held_only_on_open_day():
    p = fly(opened="2026-11-05")
    assert exit_decision(snap([p]), cfg())["actions"] == []
    assert len(exit_decision(snap([p], as_of="2026-11-06T14:45:00Z"), cfg())["actions"]) == 1


def test_closing_debit_split_when_natural_exceeds_hard_ceiling():
    legs = [L("C100", "short", "call", 100, 0.0, 0.05), L("P100", "short", "put", 100, 4.8, 5.8),
            L("C105", "long", "call", 105, 0.0, 0.05), L("P95", "long", "put", 95, 0.0, 0.4)]
    # natural = 0.05 + 5.8 = 5.85 > hard ceiling 5 + 0.50 = 5.50 -> split
    out = exit_decision(snap([fly(legs=legs)]), cfg())
    acts = out["actions"]
    assert [a["reason"] for a in acts] == ["split_verticals_natural_exceeds_width"] * 2
    assert [a["close_legs"][0]["type"] for a in acts] == ["put", "call"]
    assert len({a["group_id"] for a in acts}) == 1 and acts[0]["group_id"]
    for a in acts:
        assert a["combined_cap"] == a["hard_ceiling"] == 5.5 and a["width_cap"] == 5
        assert a["limit_start"] <= 5 and a["limit_worst"] <= 5
        assert len(a["close_legs"]) == 2 and a["trigger"].startswith("post_report_session")
    put, call = acts
    assert put["limit_worst"] == 5.0 and put["limit_start"] == 5.0     # mid 5.1, natural 5.8 -> both clamp to W
    # worthless short call vertical (mid 0) is still a debit buy-back of at least one tick
    assert call["direction"] == "debit" and call["limit_start"] == call["limit_worst"] == 0.05


def test_single_action_may_walk_past_width_up_to_hard_ceiling():
    legs = [L("C100", "short", "call", 100, 0.0, 0.05), L("P100", "short", "put", 100, 5.0, 5.4),
            L("C105", "long", "call", 105, 0.0, 0.05), L("P95", "long", "put", 95, 0.0, 0.1)]
    # mid value = -(5.2 - 0.05) = -5.15 -> start clamped to W=5.00 ; natural 5.45 <= 5.50
    a = exit_decision(snap([fly(legs=legs)]), cfg())["actions"]
    assert len(a) == 1
    assert a[0]["limit_start"] == 5.0 and a[0]["limit_worst"] == 5.45
    assert a[0]["width_cap"] == 5 and a[0]["hard_ceiling"] == 5.5
    legs[1] = L("P100", "short", "put", 100, 5.3, 5.45)               # natural 5.50 -> exactly ceiling
    a = exit_decision(snap([fly(legs=legs)]), cfg(exit_slippage_reserve=20.0))["actions"]
    assert len(a) == 2                                                 # ceiling 5.20 < 5.50 -> split


def test_single_action_clamp_when_natural_within_width():
    legs = [L("C100", "short", "call", 100, 0.0, 0.05), L("P100", "short", "put", 100, 4.7, 4.95),
            L("C105", "long", "call", 105, 0.0, 0.05), L("P95", "long", "put", 95, 0.0, 0.05)]
    a = exit_decision(snap([fly(legs=legs)]), cfg())["actions"]
    assert len(a) == 1 and a[0]["limit_worst"] == 5.0 and a[0]["limit_start"] <= 5.0


def test_order_legs_stripped_on_every_action():
    acts = exit_decision(snap([fly(), straddle()]), cfg())["actions"]
    for a in acts:
        assert a["order_legs"] == [{k: l[k] for k in ("option_id", "side", "position_effect")}
                                   for l in a["close_legs"]]
        assert all("strike" in l and "type" in l for l in a["close_legs"])
    st = next(a for a in acts if a["symbol"] == "XYZ")
    assert st["width_cap"] is None and st["hard_ceiling"] is None


def test_partial_fill_flatten():
    legs = [L("C202.5", "short", "call", 202.5, 3.0, 3.2, qty=2), L("P202.5", "short", "put", 202.5, 8.0, 8.4, qty=1),
            L("C222.5", "long", "call", 222.5, 0.1, 0.2, qty=1), L("P182.5", "long", "put", 182.5, 0.5, 0.7, qty=1)]
    out = exit_decision(snap([fly(legs=legs, opened="2026-11-05")], mso=0), cfg())   # timing gates ignored
    acts = out["actions"]
    assert all(a["leg_qty_mismatch"] and a["reason"] == "partial_fill_flatten" for a in acts)
    assert [a["sequence"] for a in acts] == [1, 2, 3]
    naked, put_v, call_v = acts                                        # naked short FIRST
    assert naked["close_legs"] == [{"option_id": "C202.5", "side": "buy", "position_effect": "close",
                                    "strike": 202.5, "type": "call"}]
    assert naked["order_legs"] == [{"option_id": "C202.5", "side": "buy", "position_effect": "close"}]
    assert naked["quantity"] == 1 and naked["naked_short"] and naked["limit_worst"] == 3.2
    assert naked["width_cap"] is None and naked["hard_ceiling"] is None
    assert {l["option_id"] for l in put_v["close_legs"]} == {"P202.5", "P182.5"}
    assert put_v["width_cap"] == 20 and put_v["hard_ceiling"] == 20.5 and put_v["limit_worst"] <= 20.5
    assert {l["option_id"] for l in call_v["close_legs"]} == {"C202.5", "C222.5"} and call_v["quantity"] == 1


def test_flatten_leftover_long_sold_last():
    legs = [L("C202.5", "short", "call", 202.5, 3.0, 3.2, qty=1), L("C222.5", "long", "call", 222.5, 0.1, 0.2, qty=2)]
    acts = exit_decision(snap([fly(legs=legs)]), cfg())["actions"]
    assert [len(a["close_legs"]) for a in acts] == [2, 1]
    assert acts[-1]["close_legs"][0]["side"] == "sell" and acts[-1]["quantity"] == 1


def test_unpaired_short_is_broken_and_preopen_hold():
    legs = [L("C202.5", "short", "call", 202.5, 3.0, 3.2), L("P182.5", "long", "put", 182.5, 0.5, 0.7)]
    out = exit_decision(snap([fly(legs=legs)], mso=-30), cfg())
    assert out["actions"] == [] and out["holds"][0]["leg_qty_mismatch"] is True
    acts = exit_decision(snap([fly(legs=legs)], mso=1), cfg())["actions"]
    assert [a["close_legs"][0]["side"] for a in acts] == ["buy", "sell"]


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


def test_exit_symbol_normalised():
    a = exit_decision(snap([fly(symbol=" arm ")]), cfg())["actions"][0]
    assert a["symbol"] == "ARM"


@pytest.mark.parametrize("bad", [
    {"as_of": "2026-11-05T14:45:00Z", "positions": []},                                   # no minutes
    snap([fly(legs=[{"option_id": "x", "side_held": "short", "type": "call", "strike": 1, "bid": None, "ask": 1}])]),
    snap([fly(legs=[{"option_id": "x", "side_held": "sideways", "type": "call", "strike": 1, "bid": 1, "ask": 1}])]),
    snap([fly(legs=[{"option_id": "x", "side_held": "short", "type": "call", "bid": 1, "ask": 1}])]),   # no strike
    snap([fly(legs=[{"option_id": "x", "side_held": "short", "strike": 1, "bid": 1, "ask": 1}])]),     # no type
])
def test_exit_invalid(bad):
    with pytest.raises(EngineInputError):
        exit_decision(bad, cfg())
