from datetime import date, datetime, timedelta

from vantage_trader.strategy.calendar import (
    CalendarManager,
    ManagementAction,
    OpenSpread,
    build_close_order,
    build_open_order,
    build_roll_short_order,
    CalendarCandidate,
)
from vantage_trader.tastytrade.models import OptionContract


def _mgmt_config(**overrides):
    base = {
        "profit_target_pct": 0.25,
        "stop_loss_pct": 0.50,
        "roll_short_at_dte": 1,
        "underlying_drift_strikes": 1,
        "close_long_at_dte": 14,
    }
    base.update(overrides)
    return base


def _spread(short_dte=3, long_dte=45, strike=500.0, debit=100.0):
    today = date.today()
    return OpenSpread(
        underlying="SPY",
        option_type="C",
        strike=strike,
        long=OptionContract(
            underlying="SPY",
            expiration=(today + timedelta(days=long_dte)).isoformat(),
            strike=strike,
            option_type="C",
        ),
        short=OptionContract(
            underlying="SPY",
            expiration=(today + timedelta(days=short_dte)).isoformat(),
            strike=strike,
            option_type="C",
        ),
        debit_paid=debit,
        opened_at=datetime.now(),
    )


def test_manager_closes_at_profit_target():
    mgr = CalendarManager(_mgmt_config())
    spread = _spread(debit=100.0)
    # current_spread_mid * 100 should be 30% above debit -> 1.30
    d = mgr.evaluate(spread, current_spread_mid=1.30, underlying_price=500.0, listed_strikes=[495, 500, 505])
    assert d.action == ManagementAction.CLOSE
    assert "profit target" in d.reason


def test_manager_closes_at_stop_loss():
    mgr = CalendarManager(_mgmt_config())
    spread = _spread(debit=100.0)
    # current_spread_mid * 100 = $40, which is -60% PnL, below -50% stop
    d = mgr.evaluate(spread, current_spread_mid=0.40, underlying_price=500.0, listed_strikes=[495, 500, 505])
    assert d.action == ManagementAction.CLOSE
    assert "stop loss" in d.reason


def test_manager_rolls_short_when_short_dte_reached():
    mgr = CalendarManager(_mgmt_config(roll_short_at_dte=1))
    spread = _spread(short_dte=1, long_dte=30, debit=100.0)
    # in tolerance for P/L: ~+5%
    d = mgr.evaluate(spread, current_spread_mid=1.05, underlying_price=500.0, listed_strikes=[495, 500, 505])
    assert d.action == ManagementAction.ROLL_SHORT


def test_manager_closes_when_long_near_expiry():
    mgr = CalendarManager(_mgmt_config(close_long_at_dte=14))
    spread = _spread(short_dte=5, long_dte=10, debit=100.0)
    d = mgr.evaluate(spread, current_spread_mid=1.05, underlying_price=500.0, listed_strikes=[495, 500, 505])
    assert d.action == ManagementAction.CLOSE
    assert "long leg DTE" in d.reason


def test_manager_closes_on_underlying_drift():
    mgr = CalendarManager(_mgmt_config(underlying_drift_strikes=1))
    spread = _spread(strike=500.0, debit=100.0)
    # underlying at 510 with strikes 500/505/510 => 1 strike strictly between (505) plus boundary at 510
    d = mgr.evaluate(
        spread, current_spread_mid=1.05, underlying_price=512.0,
        listed_strikes=[495, 500, 505, 510, 515],
    )
    assert d.action == ManagementAction.CLOSE
    assert "drifted" in d.reason


def test_manager_holds_within_tolerances():
    mgr = CalendarManager(_mgmt_config())
    spread = _spread(short_dte=3, long_dte=45, debit=100.0)
    d = mgr.evaluate(
        spread, current_spread_mid=1.10, underlying_price=500.0,
        listed_strikes=[495, 500, 505],
    )
    assert d.action == ManagementAction.HOLD


def _candidate():
    return CalendarCandidate(
        underlying="SPY",
        option_type="C",
        strike=500.0,
        long_expiration="2025-03-21",
        short_expiration="2025-02-14",
        long_mid=5.00,
        short_mid=4.00,
        debit=1.00,
        short_theta=-0.05,
        long_iv=0.20,
        short_iv=0.18,
        short_open_interest=1000,
        long_open_interest=500,
        bid_ask_spread_pct=0.05,
        score=1.0,
        long_occ="SPY   250321C00500000",
        short_occ="SPY   250214C00500000",
    )


def test_open_order_is_debit_two_leg():
    order = build_open_order(_candidate(), quantity=2)
    payload = order.to_payload()
    assert payload["price"] == "1.00"
    assert payload["price-effect"] == "Debit"
    assert len(payload["legs"]) == 2
    actions = [leg["action"] for leg in payload["legs"]]
    assert "Buy to Open" in actions
    assert "Sell to Open" in actions
    qtys = {leg["quantity"] for leg in payload["legs"]}
    assert qtys == {2}


def test_close_order_credit_when_mid_positive():
    spread = _spread()
    order = build_close_order(spread, mid_price=0.85)
    payload = order.to_payload()
    assert payload["price-effect"] == "Credit"
    assert payload["price"] == "0.85"
    actions = [leg["action"] for leg in payload["legs"]]
    assert "Sell to Close" in actions
    assert "Buy to Close" in actions


def test_close_order_debit_when_mid_negative():
    spread = _spread()
    order = build_close_order(spread, mid_price=-0.30)
    payload = order.to_payload()
    assert payload["price-effect"] == "Debit"
    assert payload["price"] == "0.30"


def test_roll_short_order_uses_new_strike_same_K():
    spread = _spread()
    new_short = OptionContract(
        underlying="SPY",
        expiration=(date.today() + timedelta(days=7)).isoformat(),
        strike=spread.strike,
        option_type="C",
    )
    order = build_roll_short_order(spread, new_short, new_credit=0.40)
    payload = order.to_payload()
    assert payload["price-effect"] == "Credit"
    assert payload["price"] == "0.40"
    # Must include both buy-to-close (old) and sell-to-open (new)
    actions = [leg["action"] for leg in payload["legs"]]
    assert "Buy to Close" in actions
    assert "Sell to Open" in actions
    new_leg = next(leg for leg in payload["legs"] if leg["action"] == "Sell to Open")
    assert new_leg["symbol"] == new_short.occ_symbol
