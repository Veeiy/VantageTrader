from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OrderSide(str, Enum):
    BUY_TO_OPEN = "Buy to Open"
    SELL_TO_OPEN = "Sell to Open"
    BUY_TO_CLOSE = "Buy to Close"
    SELL_TO_CLOSE = "Sell to Close"


class OrderType(str, Enum):
    MARKET = "Market"
    LIMIT = "Limit"


class TimeInForce(str, Enum):
    DAY = "Day"
    GTC = "GTC"


class InstrumentType(str, Enum):
    EQUITY = "Equity"
    EQUITY_OPTION = "Equity Option"


@dataclass
class OrderLeg:
    symbol: str
    quantity: int
    action: OrderSide
    instrument_type: InstrumentType = InstrumentType.EQUITY

    def to_payload(self) -> dict[str, Any]:
        return {
            "instrument-type": self.instrument_type.value,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "action": self.action.value,
        }


@dataclass
class OrderRequest:
    order_type: OrderType
    time_in_force: TimeInForce
    legs: list[OrderLeg]
    price: float | None = None
    price_effect: str | None = None  # "Debit" or "Credit"

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "order-type": self.order_type.value,
            "time-in-force": self.time_in_force.value,
            "legs": [leg.to_payload() for leg in self.legs],
        }
        if self.order_type == OrderType.LIMIT:
            if self.price is None or self.price_effect is None:
                raise ValueError("Limit orders require price and price_effect")
            payload["price"] = f"{self.price:.2f}"
            payload["price-effect"] = self.price_effect
        return payload


@dataclass(frozen=True)
class OptionContract:
    """One option leg, identified by its OCC symbol.

    OCC format (21 chars): ROOT(6, left-justified, space-padded) + YYMMDD + C/P
    + STRIKE(8, strike*1000 zero-padded). Example for SPY 500 PUT 2024-06-14:
    'SPY   240614P00500000'
    """
    underlying: str
    expiration: str         # 'YYYY-MM-DD'
    strike: float
    option_type: str        # 'C' or 'P'

    @property
    def occ_symbol(self) -> str:
        root = f"{self.underlying:<6}"
        yymmdd = self.expiration.replace("-", "")[2:]
        strike_int = int(round(self.strike * 1000))
        return f"{root}{yymmdd}{self.option_type}{strike_int:08d}"

    @property
    def streamer_symbol(self) -> str:
        """DXLink/dxfeed format, e.g. '.SPY240614P500' or '.SPY240614P500.5'."""
        yymmdd = self.expiration.replace("-", "")[2:]
        if self.strike == int(self.strike):
            strike_part = str(int(self.strike))
        else:
            strike_part = f"{self.strike:g}"
        return f".{self.underlying}{yymmdd}{self.option_type}{strike_part}"


@dataclass
class Position:
    symbol: str
    quantity: int
    direction: str  # "Long" / "Short" / "Zero"
    average_open_price: float
    raw: dict[str, Any] = field(default_factory=dict)
