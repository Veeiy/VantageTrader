"""Iron fly as ONE multi-leg order for the tastytrade API.

The Robinhood agentic account refuses multi-leg orders from an agent, so the earnings engine
legs in and out there with single-leg orders (docs/earnings/RULES_CHANGELOG.md, v1.2.1). The
tastytrade API takes the whole structure as one order and can dry-run it first
(`TastytradeClient.dry_run_order`: buying-power effect, fees, warnings). These builders turn a
fly into that order. They place nothing; trading a tastytrade account at all is the owner's
decision (proposal P050).

    order = build_iron_fly_open("SPY", "2026-11-17", body=744, put_wing=740, call_wing=748, credit=2.75)
    await client.dry_run_order(account_number, order)      # always first
    await client.place_order(account_number, order)

Legs are listed wings first, then the short body, the order the engine uses when it legs in.
"""
from __future__ import annotations

from ..tastytrade.models import (
    InstrumentType,
    OptionContract,
    OrderLeg,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)

NEVER = ("TSLA",)      # owner's hard limit, checked here as well as in the gates


def _check(underlying: str, body: float, put_wing: float, call_wing: float, price: float, quantity: int) -> float:
    if underlying.strip().upper() in NEVER:
        raise ValueError(f"{underlying} is never traded")
    if not (put_wing < body < call_wing):
        raise ValueError("strikes must satisfy put_wing < body < call_wing")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValueError("quantity must be a whole number >= 1")
    width = max(body - put_wing, call_wing - body)
    if not (0 < price < width):
        raise ValueError(f"price must be above 0 and below the wing width {width:g}")
    return width


def _legs(underlying: str, expiration: str, body: float, put_wing: float, call_wing: float, quantity: int,
          opening: bool) -> list[OrderLeg]:
    sym = underlying.strip().upper()
    wing_action = OrderSide.BUY_TO_OPEN if opening else OrderSide.SELL_TO_CLOSE
    body_action = OrderSide.SELL_TO_OPEN if opening else OrderSide.BUY_TO_CLOSE
    spec = [(put_wing, "P", wing_action), (call_wing, "C", wing_action),
            (body, "P", body_action), (body, "C", body_action)]
    if not opening:                       # closing: the short body first, then the wings
        spec = spec[2:] + spec[:2]
    return [OrderLeg(symbol=OptionContract(sym, expiration, float(k), t).occ_symbol, quantity=quantity,
                     action=action, instrument_type=InstrumentType.EQUITY_OPTION)
            for k, t, action in spec]


def build_iron_fly_open(underlying: str, expiration: str, body: float, put_wing: float, call_wing: float,
                        credit: float, quantity: int = 1) -> OrderRequest:
    """Sell the body call and put, buy both wings, for a net limit credit per fly."""
    _check(underlying, body, put_wing, call_wing, credit, quantity)
    return OrderRequest(order_type=OrderType.LIMIT, time_in_force=TimeInForce.DAY,
                        legs=_legs(underlying, expiration, body, put_wing, call_wing, quantity, opening=True),
                        price=round(credit, 2), price_effect="Credit")


def build_iron_fly_close(underlying: str, expiration: str, body: float, put_wing: float, call_wing: float,
                         debit: float, quantity: int = 1) -> OrderRequest:
    """Buy the body back and sell both wings, for a net limit debit per fly."""
    _check(underlying, body, put_wing, call_wing, debit, quantity)
    return OrderRequest(order_type=OrderType.LIMIT, time_in_force=TimeInForce.DAY,
                        legs=_legs(underlying, expiration, body, put_wing, call_wing, quantity, opening=False),
                        price=round(debit, 2), price_effect="Debit")


def iron_fly_max_loss(body: float, put_wing: float, call_wing: float, credit: float, quantity: int = 1) -> float:
    """Dollars lost if the stock ends beyond the wider wing: (width - credit) x 100 x contracts."""
    width = max(body - put_wing, call_wing - body)
    return round((width - credit) * 100.0 * quantity, 2)
