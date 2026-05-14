"""Calendar spread scanner and manager.

Trade structure:
    LONG  1x option   strike K, expiration T_long  (30-60 DTE default)
    SHORT 1x option   strike K, expiration today    (0 DTE default)
    Same option_type (both calls or both puts), same strike K.

Strike selection (delta-targeted):
    For each candidate (side, short_exp, long_exp), the bot scores every
    listed strike whose 0DTE delta on the chosen side falls in the
    configured [short_delta_min, short_delta_max] band. The strike whose
    abs(delta) is closest to the band midpoint wins for that combo.

Direction (call vs put calendar):
    - 'auto': pick the side that keeps the short OTM at the chosen strike,
      minimising assignment risk. (spot < K => calls, spot >= K => puts)
    - 'call' / 'put': force a side.
    - 'both': evaluate both sides and keep the best-scored candidate per
      (underlying, long_exp, short_exp).

Ranking score (higher = better):
    score = theta_per_dollar * liquidity_factor * iv_term_kicker
where:
    theta_per_dollar = abs(short_theta) / debit_paid   (daily |theta| per $1 at risk)
    iv_term_kicker   = 1 + max(0, (long_iv - short_iv) * 2)   (long vega benefit)
    liquidity_factor = clamp(1 - bid_ask_spread_pct / max_bid_ask_spread_pct, 0, 1)

Management rules (checked every manage_every_seconds):
    1. profit_target_pct hit -> close
    2. stop_loss_pct hit -> close
    3. underlying drifted > underlying_drift_strikes from K -> close
    4. long leg DTE <= close_long_at_dte -> close
    5. clock <= close_short_minutes_before_close -> close (0DTE has no roll target today)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Mapping

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
from ..tastytrade.streamer import Greeks

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StrikeRow:
    """A strike's call+put OCC symbols, plus its streamer (.dxfeed) symbols."""
    strike: float
    call_occ: str
    put_occ: str
    call_streamer: str
    put_streamer: str


@dataclass
class CalendarCandidate:
    underlying: str
    option_type: str           # 'C' or 'P'
    strike: float
    long_expiration: str
    short_expiration: str
    long_mid: float
    short_mid: float
    debit: float                # per-contract (long_mid - short_mid)
    short_delta: float | None
    short_theta: float | None
    long_iv: float | None
    short_iv: float | None
    short_open_interest: int
    long_open_interest: int
    bid_ask_spread_pct: float
    theta_per_dollar: float
    score: float
    long_occ: str
    short_occ: str
    long_streamer: str
    short_streamer: str
    rationale: str = ""


@dataclass
class OpenSpread:
    underlying: str
    option_type: str
    strike: float
    long: OptionContract
    short: OptionContract
    debit_paid: float          # per spread, in dollars (mid * 100)
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
    """Builds and ranks calendar candidates using live greeks from DXLink."""

    def __init__(self, client: TastytradeClient, entry_config: dict[str, Any]):
        self.client = client
        self.cfg = entry_config

    def gather_target_strikes(
        self, chain: dict[str, Any], spot: float, max_strikes_per_side: int = 8
    ) -> list[StrikeRow]:
        """Pick a window of strikes around spot for greek subscription.

        Returns up to 2*max_strikes_per_side strikes, centred on spot,
        intersected with strikes that exist in BOTH a short-DTE and a long-DTE
        expiration. The streamer subscribes greeks for the short DTE only.
        """
        expirations = self._extract_expirations(chain)
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
            return []

        # Strikes that appear in ANY short_exp AND ANY long_exp.
        short_strikes = {
            float(s["strike-price"]) for e in short_exps for s in e.get("strikes", [])
        }
        long_strikes = {
            float(s["strike-price"]) for e in long_exps for s in e.get("strikes", [])
        }
        common = sorted(short_strikes & long_strikes, key=lambda k: abs(k - spot))[
            : max_strikes_per_side * 2
        ]
        # Build StrikeRow from the first short exp that contains each strike.
        rows: list[StrikeRow] = []
        for strike in common:
            for e in short_exps:
                row = self._strike_in_exp(e, strike)
                if row is not None:
                    rows.append(row)
                    break
        return rows

    def expiration_pairs(
        self, chain: dict[str, Any]
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """All (short_exp, long_exp) pairs in our DTE windows where long > short."""
        expirations = self._extract_expirations(chain)
        today = date.today()
        short_exps = [
            e for e in expirations
            if self.cfg["short_dte_min"] <= _dte(e["date"], today) <= self.cfg["short_dte_max"]
        ]
        long_exps = [
            e for e in expirations
            if self.cfg["long_dte_min"] <= _dte(e["date"], today) <= self.cfg["long_dte_max"]
        ]
        out: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for short_e in short_exps:
            for long_e in long_exps:
                if long_e["date"] > short_e["date"]:
                    out.append((short_e, long_e))
        return out

    def build_candidate(
        self,
        underlying: str,
        spot: float,
        short_exp: dict[str, Any],
        long_exp: dict[str, Any],
        side: str,                  # 'C' or 'P'
        quotes: Mapping[str, Mapping[str, Any]],   # occ_symbol -> bid/ask/oi
        greeks: Mapping[str, Greeks],              # streamer_symbol -> Greeks
    ) -> CalendarCandidate | None:
        """Pick the best strike for this side+expiration pair under delta band."""
        target = (self.cfg["short_delta_min"] + self.cfg["short_delta_max"]) / 2

        best: CalendarCandidate | None = None
        for s in short_exp.get("strikes", []):
            short_row = self._strike_to_row(s)
            long_row = self._strike_in_exp(long_exp, short_row.strike)
            if long_row is None:
                continue

            short_occ = short_row.call_occ if side == "C" else short_row.put_occ
            long_occ = long_row.call_occ if side == "C" else long_row.put_occ
            short_dx = short_row.call_streamer if side == "C" else short_row.put_streamer
            long_dx = long_row.call_streamer if side == "C" else long_row.put_streamer

            g_short = greeks.get(short_dx)
            g_long = greeks.get(long_dx)
            if g_short is None or g_short.delta is None:
                continue

            abs_delta = abs(g_short.delta)
            if not (self.cfg["short_delta_min"] <= abs_delta <= self.cfg["short_delta_max"]):
                continue

            q_short = quotes.get(short_occ, {})
            q_long = quotes.get(long_occ, {})
            s_bid = self._f(q_short.get("bid")) or 0.0
            s_ask = self._f(q_short.get("ask")) or 0.0
            l_bid = self._f(q_long.get("bid")) or 0.0
            l_ask = self._f(q_long.get("ask")) or 0.0
            s_mid = _mid(s_bid, s_ask)
            l_mid = _mid(l_bid, l_ask)
            debit = l_mid - s_mid
            if debit <= 0:
                continue

            spread_pct = max(_spread_pct(s_bid, s_ask), _spread_pct(l_bid, l_ask))

            theta_per_dollar = 0.0
            if g_short.theta is not None and debit > 0:
                theta_per_dollar = abs(g_short.theta) / (debit * 100)

            iv_short = g_short.volatility if g_short else None
            iv_long = g_long.volatility if g_long else None
            iv_kicker = 1.0
            if iv_long is not None and iv_short is not None:
                iv_kicker = 1.0 + max(0.0, (iv_long - iv_short) * 2.0)
            max_spread = self.cfg["max_bid_ask_spread_pct"]
            liquidity = max(0.0, min(1.0, 1.0 - (spread_pct / max_spread))) if max_spread else 1.0
            score = theta_per_dollar * iv_kicker * liquidity

            candidate = CalendarCandidate(
                underlying=underlying,
                option_type=side,
                strike=short_row.strike,
                long_expiration=long_exp["date"],
                short_expiration=short_exp["date"],
                long_mid=l_mid,
                short_mid=s_mid,
                debit=debit,
                short_delta=g_short.delta,
                short_theta=g_short.theta,
                long_iv=iv_long,
                short_iv=iv_short,
                short_open_interest=int(self._f(q_short.get("open-interest")) or 0),
                long_open_interest=int(self._f(q_long.get("open-interest")) or 0),
                bid_ask_spread_pct=spread_pct,
                theta_per_dollar=theta_per_dollar,
                score=score,
                long_occ=long_occ,
                short_occ=short_occ,
                long_streamer=long_dx,
                short_streamer=short_dx,
                rationale=(
                    f"{side} K={short_row.strike} "
                    f"short_delta={g_short.delta:+.2f} theta/$={theta_per_dollar:.4f} "
                    f"debit=${debit*100:.0f} liq={liquidity:.2f}"
                ),
            )
            if not self._passes_filters(candidate):
                continue
            # Prefer strike closest to delta band midpoint, then higher score.
            score_key = (
                -abs(abs_delta - target),  # closer to midpoint is better
                candidate.score,
            )
            if best is None:
                best = candidate
                best_key = score_key
            elif score_key > best_key:  # type: ignore[has-type]
                best = candidate
                best_key = score_key
        return best

    def select_side(self, spot: float, strike: float) -> str:
        """Resolve direction config to 'C' or 'P' for a given strike."""
        direction = self.cfg.get("direction", "auto")
        if direction == "call":
            return "C"
        if direction == "put":
            return "P"
        # auto: keep short OTM
        return "C" if spot < strike else "P"

    def sides_to_consider(self, spot: float, strike: float) -> list[str]:
        direction = self.cfg.get("direction", "auto")
        if direction == "both":
            return ["C", "P"]
        return [self.select_side(spot, strike)]

    # -- helpers -----------------------------------------------------------

    def _passes_filters(self, c: CalendarCandidate) -> bool:
        if c.debit * 100 > self.cfg["max_debit_per_spread"]:
            return False
        if c.short_open_interest < self.cfg["min_open_interest_short"]:
            return False
        if c.long_open_interest < self.cfg["min_open_interest_long"]:
            return False
        if c.bid_ask_spread_pct > self.cfg["max_bid_ask_spread_pct"]:
            return False
        if c.theta_per_dollar < self.cfg.get("min_theta_per_dollar", 0.0):
            return False
        return True

    @staticmethod
    def _extract_expirations(chain: dict[str, Any]) -> list[dict[str, Any]]:
        items = chain.get("items", [])
        if not items:
            return []
        return items[0].get("expirations", []) or []

    @staticmethod
    def _strike_in_exp(exp: dict[str, Any], strike: float) -> StrikeRow | None:
        for s in exp.get("strikes", []):
            if abs(float(s["strike-price"]) - strike) < 1e-6:
                return CalendarScanner._strike_to_row(s)
        return None

    @staticmethod
    def _strike_to_row(s: dict[str, Any]) -> StrikeRow:
        return StrikeRow(
            strike=float(s["strike-price"]),
            call_occ=s.get("call", ""),
            put_occ=s.get("put", ""),
            call_streamer=s.get("call-streamer-symbol", "") or s.get("streamer-symbol", ""),
            put_streamer=s.get("put-streamer-symbol", "") or s.get("streamer-symbol", ""),
        )

    @staticmethod
    def _f(v: Any) -> float | None:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ManagementAction:
    CLOSE = "close"
    HOLD = "hold"


@dataclass
class ManagementDecision:
    action: str
    reason: str
    spread: OpenSpread


class CalendarManager:
    """Evaluates open spreads against management rules.

    On 0DTE shorts there's no roll target same-day; the manager closes the
    spread by `close_short_minutes_before_close` minutes before market close.
    The engine will re-enter fresh on the next session if criteria still hold.
    """

    def __init__(self, management_config: dict[str, Any]):
        self.cfg = management_config

    def evaluate(
        self,
        spread: OpenSpread,
        current_spread_mid: float,    # (long_mid - short_mid) per contract right now
        underlying_price: float,
        listed_strikes: Iterable[float],
        minutes_to_close: int | None = None,
    ) -> ManagementDecision:
        debit = spread.debit_paid
        current_value = current_spread_mid * 100
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

        drift_strikes = self._strike_drift(underlying_price, spread.strike, listed_strikes)
        if drift_strikes > self.cfg["underlying_drift_strikes"]:
            return ManagementDecision(
                ManagementAction.CLOSE,
                f"underlying drifted {drift_strikes} strikes from K={spread.strike}",
                spread,
            )

        # 0DTE end-of-day close (only matters when short is today's date).
        short_dte = _dte(spread.short.expiration)
        if short_dte == 0 and minutes_to_close is not None:
            cutoff = self.cfg.get("close_short_minutes_before_close", 15)
            if minutes_to_close <= cutoff:
                return ManagementDecision(
                    ManagementAction.CLOSE,
                    f"0DTE short - {minutes_to_close}m to close <= {cutoff}m cutoff",
                    spread,
                )

        return ManagementDecision(ManagementAction.HOLD, "within tolerances", spread)

    @staticmethod
    def _strike_drift(price: float, strike: float, listed: Iterable[float]) -> int:
        listed_sorted = sorted(set(listed))
        if not listed_sorted:
            return 0
        lo, hi = (price, strike) if price < strike else (strike, price)
        return sum(1 for s in listed_sorted if lo < s < hi)


# ---------------------------------------------------------------------------
# Order construction
# ---------------------------------------------------------------------------

def build_open_order(cand: CalendarCandidate, quantity: int = 1) -> OrderRequest:
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
