"""Calendar spread scanner and manager.

Trade structure (one "spread"):
    LONG  1x option   strike K, expiration T_long   (30-60 DTE)
    SHORT 1x option   strike K, expiration T_short  (1-5 DTE)
    Same option_type (both calls or both puts), same strike K.

Direction selection per underlying:
    Pick the listed strike K closest to (price * (1 + strike_offset_pct)).
    If price < K  -> call calendar  (short call is OTM)
    If price >= K -> put calendar   (short put is OTM)
This keeps the short leg OTM at entry, minimising assignment risk on the short.

Calendars are LONG VEGA: profit when IV rises and underlying pins the strike.
We prefer entry when IV rank is low (room for IV to expand).

Ranking score (higher = better):
    score = theta_efficiency * iv_term_kicker * liquidity_factor
where:
    theta_efficiency = abs(short_theta) / debit_paid
    iv_term_kicker   = 1 + max(0, (long_iv - short_iv) * 2)
    liquidity_factor = clamp(1 - bid_ask_spread_pct / max_bid_ask_spread_pct, 0, 1)

Exit/management rules per open spread (checked on every management tick):
    1. profit_target_pct hit  -> close
    2. stop_loss_pct hit      -> close
    3. underlying drifted > underlying_drift_strikes away from K -> close
    4. long leg DTE <= close_long_at_dte -> close
    5. short leg DTE <= roll_short_at_dte -> roll short to next eligible expiry
       at the same strike (if the spread is otherwise healthy)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

from ..tastytrade.client import TastytradeClient
from ..tastytrade.models import (
    InstrumentType,
    OptionContract,
    OrderLeg,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StrikeQuote:
    """A single strike with its call & put quotes pulled from the chain."""
    strike: float
    call_bid: float
    call_ask: float
    put_bid: float
    put_ask: float
    call_open_interest: int
    put_open_interest: int
    call_iv: float | None = None
    put_iv: float | None = None
    call_theta: float | None = None
    put_theta: float | None = None
    call_occ: str = ""
    put_occ: str = ""


@dataclass
class CalendarCandidate:
    underlying: str
    option_type: str  # 'C' or 'P'
    strike: float
    long_expiration: str
    short_expiration: str
    long_mid: float
    short_mid: float
    debit: float                  # long_mid - short_mid, per contract (not *100)
    short_theta: float | None
    long_iv: float | None
    short_iv: float | None
    short_open_interest: int
    long_open_interest: int
    bid_ask_spread_pct: float     # worst of the two legs
    score: float
    long_occ: str
    short_occ: str
    rationale: str = ""


@dataclass
class OpenSpread:
    """An open calendar spread we are managing."""
    underlying: str
    option_type: str
    strike: float
    long: OptionContract
    short: OptionContract
    debit_paid: float       # per spread (already in dollars: mid * 100)
    opened_at: datetime
    short_quantity: int = 1
    long_quantity: int = 1
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dte(expiration: str, today: date | None = None) -> int:
    today = today or date.today()
    return (date.fromisoformat(expiration) - today).days


def _mid(bid: float, ask: float) -> float:
    if bid <= 0 and ask <= 0:
        return 0.0
    if bid <= 0:
        return ask
    if ask <= 0:
        return bid
    return (bid + ask) / 2.0


def _spread_pct(bid: float, ask: float) -> float:
    mid = _mid(bid, ask)
    if mid <= 0:
        return 1.0
    return abs(ask - bid) / mid


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class CalendarScanner:
    """Builds a ranked list of calendar candidates from option-chain data."""

    def __init__(self, client: TastytradeClient, entry_config: dict[str, Any]):
        self.client = client
        self.cfg = entry_config

    async def scan_underlying(
        self,
        underlying: str,
        spot_price: float,
        iv_rank: float | None,
        earnings_dte: int | None,
    ) -> list[CalendarCandidate]:
        # Gate: skip if IV rank above ceiling (calendars are long vega -> want low IV).
        if iv_rank is not None and iv_rank > self.cfg["iv_rank_max"]:
            log.info(
                "%s: skip (IV rank %.1f > max %.1f)",
                underlying, iv_rank, self.cfg["iv_rank_max"],
            )
            return []

        # Gate: skip if earnings inside our short DTE window.
        if earnings_dte is not None and 0 <= earnings_dte <= self.cfg[
            "skip_if_earnings_within_days"
        ]:
            log.info("%s: skip (earnings in %d days)", underlying, earnings_dte)
            return []

        chain = await self.client.get_option_chain_nested(underlying)
        expirations = self._extract_expirations(chain)
        if not expirations:
            log.warning("%s: no expirations in chain", underlying)
            return []

        today = date.today()
        short_exps = [
            e for e in expirations
            if self.cfg["short_dte_min"] <= _dte(e["date"], today) <= self.cfg["short_dte_max"]
        ]
        long_exps = [
            e for e in expirations
            if self.cfg["long_dte_min"] <= _dte(e["date"], today) <= self.cfg["long_dte_max"]
        ]
        if not short_exps or not long_exps:
            log.info("%s: no expirations in DTE windows", underlying)
            return []

        # Target strike: nearest listed to spot * (1 + offset).
        target_price = spot_price * (1.0 + self.cfg["strike_offset_pct"])
        candidates: list[CalendarCandidate] = []

        for short_exp in short_exps:
            for long_exp in long_exps:
                if long_exp["date"] <= short_exp["date"]:
                    continue
                strike_quote_short = self._nearest_strike(short_exp, target_price)
                strike_quote_long = self._strike_in_exp(long_exp, strike_quote_short.strike)
                if strike_quote_long is None:
                    continue

                # Determine direction from where price sits relative to the chosen strike.
                option_type = "C" if spot_price < strike_quote_short.strike else "P"
                cand = self._build_candidate(
                    underlying=underlying,
                    option_type=option_type,
                    strike=strike_quote_short.strike,
                    short_exp=short_exp["date"],
                    long_exp=long_exp["date"],
                    short_q=strike_quote_short,
                    long_q=strike_quote_long,
                )
                if cand is None:
                    continue
                candidates.append(cand)

        # Filter & sort
        filtered = [c for c in candidates if self._passes_filters(c)]
        filtered.sort(key=lambda c: c.score, reverse=True)
        return filtered

    # -- internal helpers --------------------------------------------------

    @staticmethod
    def _extract_expirations(chain: dict[str, Any]) -> list[dict[str, Any]]:
        items = chain.get("items", [])
        if not items:
            return []
        # nested chain returns items=[{expirations: [{date, strikes: [...]}, ...]}]
        return items[0].get("expirations", []) or []

    @staticmethod
    def _nearest_strike(exp: dict[str, Any], target: float) -> StrikeQuote:
        strikes = exp.get("strikes", [])
        # `strike` field is a string like "500.0"
        best = min(strikes, key=lambda s: abs(float(s["strike-price"]) - target))
        return CalendarScanner._strike_to_quote(best)

    @staticmethod
    def _strike_in_exp(exp: dict[str, Any], strike: float) -> StrikeQuote | None:
        for s in exp.get("strikes", []):
            if abs(float(s["strike-price"]) - strike) < 1e-6:
                return CalendarScanner._strike_to_quote(s)
        return None

    @staticmethod
    def _strike_to_quote(s: dict[str, Any]) -> StrikeQuote:
        # The nested chain endpoint returns OCC symbols but not live quotes.
        # Live quotes/OI/greeks must come from /market-data or DXLink.
        # We populate placeholders here; the engine fills quotes before scoring.
        return StrikeQuote(
            strike=float(s["strike-price"]),
            call_bid=0.0, call_ask=0.0,
            put_bid=0.0, put_ask=0.0,
            call_open_interest=0, put_open_interest=0,
            call_occ=s.get("call", ""),
            put_occ=s.get("put", ""),
        )

    def _build_candidate(
        self,
        underlying: str,
        option_type: str,
        strike: float,
        short_exp: str,
        long_exp: str,
        short_q: StrikeQuote,
        long_q: StrikeQuote,
    ) -> CalendarCandidate | None:
        if option_type == "C":
            s_bid, s_ask = short_q.call_bid, short_q.call_ask
            l_bid, l_ask = long_q.call_bid, long_q.call_ask
            s_iv, l_iv = short_q.call_iv, long_q.call_iv
            s_theta = short_q.call_theta
            s_oi, l_oi = short_q.call_open_interest, long_q.call_open_interest
            s_occ, l_occ = short_q.call_occ, long_q.call_occ
        else:
            s_bid, s_ask = short_q.put_bid, short_q.put_ask
            l_bid, l_ask = long_q.put_bid, long_q.put_ask
            s_iv, l_iv = short_q.put_iv, long_q.put_iv
            s_theta = short_q.put_theta
            s_oi, l_oi = short_q.put_open_interest, long_q.put_open_interest
            s_occ, l_occ = short_q.put_occ, long_q.put_occ

        short_mid = _mid(s_bid, s_ask)
        long_mid = _mid(l_bid, l_ask)
        debit = long_mid - short_mid
        if debit <= 0:
            return None  # not a valid debit calendar

        spread_pct = max(_spread_pct(s_bid, s_ask), _spread_pct(l_bid, l_ask))

        # Score
        theta_eff = (abs(s_theta) / debit) if (s_theta and debit > 0) else 0.0
        iv_kicker = 1.0
        if l_iv is not None and s_iv is not None:
            iv_kicker = 1.0 + max(0.0, (l_iv - s_iv) * 2.0)
        max_spread = self.cfg["max_bid_ask_spread_pct"]
        liquidity = max(0.0, min(1.0, 1.0 - (spread_pct / max_spread))) if max_spread else 1.0
        score = theta_eff * iv_kicker * liquidity

        rationale = (
            f"{option_type} calendar K={strike} "
            f"short {short_exp} mid={short_mid:.2f} / long {long_exp} mid={long_mid:.2f}; "
            f"debit={debit:.2f} theta_eff={theta_eff:.3f} iv_kicker={iv_kicker:.2f} "
            f"liq={liquidity:.2f}"
        )

        return CalendarCandidate(
            underlying=underlying,
            option_type=option_type,
            strike=strike,
            long_expiration=long_exp,
            short_expiration=short_exp,
            long_mid=long_mid,
            short_mid=short_mid,
            debit=debit,
            short_theta=s_theta,
            long_iv=l_iv,
            short_iv=s_iv,
            short_open_interest=s_oi,
            long_open_interest=l_oi,
            bid_ask_spread_pct=spread_pct,
            score=score,
            long_occ=l_occ,
            short_occ=s_occ,
            rationale=rationale,
        )

    def _passes_filters(self, c: CalendarCandidate) -> bool:
        # Debit cap (per-contract dollar value)
        if c.debit * 100 > self.cfg["max_debit_per_spread"]:
            return False
        if c.short_open_interest < self.cfg["min_open_interest_short"]:
            return False
        if c.long_open_interest < self.cfg["min_open_interest_long"]:
            return False
        if c.bid_ask_spread_pct > self.cfg["max_bid_ask_spread_pct"]:
            return False
        return True


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ManagementAction:
    CLOSE = "close"
    ROLL_SHORT = "roll_short"
    HOLD = "hold"


@dataclass
class ManagementDecision:
    action: str
    reason: str
    spread: OpenSpread


class CalendarManager:
    """Evaluates open spreads against management rules."""

    def __init__(self, management_config: dict[str, Any]):
        self.cfg = management_config

    def evaluate(
        self,
        spread: OpenSpread,
        current_spread_mid: float,    # current mid-price to close (long_mid - short_mid), per contract
        underlying_price: float,
        listed_strikes: Iterable[float],
    ) -> ManagementDecision:
        current_value = current_spread_mid * 100
        debit = spread.debit_paid
        pnl_pct = (current_value - debit) / debit if debit > 0 else 0.0

        if pnl_pct >= self.cfg["profit_target_pct"]:
            return ManagementDecision(
                ManagementAction.CLOSE,
                f"profit target hit ({pnl_pct:.1%} >= {self.cfg['profit_target_pct']:.0%})",
                spread,
            )
        if pnl_pct <= -self.cfg["stop_loss_pct"]:
            return ManagementDecision(
                ManagementAction.CLOSE,
                f"stop loss hit ({pnl_pct:.1%} <= -{self.cfg['stop_loss_pct']:.0%})",
                spread,
            )

        long_dte = _dte(spread.long.expiration)
        if long_dte <= self.cfg["close_long_at_dte"]:
            return ManagementDecision(
                ManagementAction.CLOSE,
                f"long leg DTE {long_dte} <= {self.cfg['close_long_at_dte']}",
                spread,
            )

        drift_strikes = self._strike_drift(
            underlying_price, spread.strike, listed_strikes
        )
        if drift_strikes > self.cfg["underlying_drift_strikes"]:
            return ManagementDecision(
                ManagementAction.CLOSE,
                f"underlying drifted {drift_strikes} strikes from K={spread.strike}",
                spread,
            )

        short_dte = _dte(spread.short.expiration)
        if short_dte <= self.cfg["roll_short_at_dte"]:
            return ManagementDecision(
                ManagementAction.ROLL_SHORT,
                f"short DTE {short_dte} <= {self.cfg['roll_short_at_dte']}",
                spread,
            )

        return ManagementDecision(ManagementAction.HOLD, "within tolerances", spread)

    @staticmethod
    def _strike_drift(price: float, strike: float, listed: Iterable[float]) -> int:
        """How many listed strikes lie between `price` and `strike`."""
        listed_sorted = sorted(set(listed))
        if not listed_sorted:
            return 0
        lo, hi = (price, strike) if price < strike else (strike, price)
        return sum(1 for s in listed_sorted if lo < s < hi)


# ---------------------------------------------------------------------------
# Order construction
# ---------------------------------------------------------------------------

def build_open_order(cand: CalendarCandidate, quantity: int = 1) -> OrderRequest:
    """Two-leg debit calendar: BUY long, SELL short. Price as a debit."""
    long_leg = OrderLeg(
        symbol=cand.long_occ,
        quantity=quantity,
        action=OrderSide.BUY_TO_OPEN,
        instrument_type=InstrumentType.EQUITY_OPTION,
    )
    short_leg = OrderLeg(
        symbol=cand.short_occ,
        quantity=quantity,
        action=OrderSide.SELL_TO_OPEN,
        instrument_type=InstrumentType.EQUITY_OPTION,
    )
    return OrderRequest(
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        legs=[long_leg, short_leg],
        price=round(cand.debit, 2),
        price_effect="Debit",
    )


def build_close_order(spread: OpenSpread, mid_price: float) -> OrderRequest:
    """Closing inverts both legs. If currently a debit-valued position, closing
    pays us a credit; if the spread has decayed, closing may cost a debit.
    `mid_price` is the current (long_mid - short_mid) per contract."""
    long_close = OrderLeg(
        symbol=spread.long.occ_symbol,
        quantity=spread.long_quantity,
        action=OrderSide.SELL_TO_CLOSE,
        instrument_type=InstrumentType.EQUITY_OPTION,
    )
    short_close = OrderLeg(
        symbol=spread.short.occ_symbol,
        quantity=spread.short_quantity,
        action=OrderSide.BUY_TO_CLOSE,
        instrument_type=InstrumentType.EQUITY_OPTION,
    )
    if mid_price >= 0:
        price, effect = round(mid_price, 2), "Credit"
    else:
        price, effect = round(-mid_price, 2), "Debit"
    return OrderRequest(
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        legs=[long_close, short_close],
        price=price,
        price_effect=effect,
    )


def build_roll_short_order(
    spread: OpenSpread, new_short: OptionContract, new_credit: float
) -> OrderRequest:
    """Close existing short, open new short at the same strike, later expiration.
    `new_credit` = (old_short_mid - new_short_mid) per contract. Positive = credit."""
    close_old = OrderLeg(
        symbol=spread.short.occ_symbol,
        quantity=spread.short_quantity,
        action=OrderSide.BUY_TO_CLOSE,
        instrument_type=InstrumentType.EQUITY_OPTION,
    )
    open_new = OrderLeg(
        symbol=new_short.occ_symbol,
        quantity=spread.short_quantity,
        action=OrderSide.SELL_TO_OPEN,
        instrument_type=InstrumentType.EQUITY_OPTION,
    )
    if new_credit >= 0:
        price, effect = round(new_credit, 2), "Credit"
    else:
        price, effect = round(-new_credit, 2), "Debit"
    return OrderRequest(
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        legs=[close_old, open_new],
        price=price,
        price_effect=effect,
    )
