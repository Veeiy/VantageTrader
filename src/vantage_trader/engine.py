"""Engine loop: scan -> rank -> enter -> manage -> roll/exit.

This is the orchestration layer. Strategy decisions live in strategy/calendar.py.
The engine is responsible for:
  - timing (entry window, management cadence, market hours)
  - inventory tracking (which spreads are open, capital deployed)
  - dispatching orders (or logging them in dry-run mode)
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import Credentials
from .strategy.calendar import (
    CalendarCandidate,
    CalendarManager,
    CalendarScanner,
    ManagementAction,
    OpenSpread,
    build_close_order,
    build_open_order,
)
from .tastytrade.client import TastytradeClient
from .tastytrade.models import OptionContract, OrderRequest

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
STATE_FILE = Path("state/open_spreads.json")


class Engine:
    def __init__(
        self,
        client: TastytradeClient,
        creds: Credentials,
        config: dict[str, Any],
        dry_run: bool = True,
    ):
        self.client = client
        self.creds = creds
        self.config = config
        self.dry_run = dry_run
        self.scanner = CalendarScanner(client, config["entry"])
        self.manager = CalendarManager(config["management"])
        self.open_spreads: list[OpenSpread] = []
        self._load_state()

    # ---- state persistence ------------------------------------------------

    def _load_state(self) -> None:
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning("could not load state: %s", e)
            return
        for raw in data.get("open_spreads", []):
            self.open_spreads.append(
                OpenSpread(
                    underlying=raw["underlying"],
                    option_type=raw["option_type"],
                    strike=raw["strike"],
                    long=OptionContract(**raw["long"]),
                    short=OptionContract(**raw["short"]),
                    debit_paid=raw["debit_paid"],
                    opened_at=datetime.fromisoformat(raw["opened_at"]),
                    short_quantity=raw.get("short_quantity", 1),
                    long_quantity=raw.get("long_quantity", 1),
                )
            )
        log.info("loaded %d open spread(s) from state", len(self.open_spreads))

    def _save_state(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "open_spreads": [
                {
                    "underlying": s.underlying,
                    "option_type": s.option_type,
                    "strike": s.strike,
                    "long": asdict(s.long),
                    "short": asdict(s.short),
                    "debit_paid": s.debit_paid,
                    "opened_at": s.opened_at.isoformat(),
                    "short_quantity": s.short_quantity,
                    "long_quantity": s.long_quantity,
                }
                for s in self.open_spreads
            ]
        }
        STATE_FILE.write_text(json.dumps(payload, indent=2))

    # ---- main loop --------------------------------------------------------

    async def run_forever(self) -> None:
        cadence = self.config["schedule"]["manage_every_seconds"]
        log.info(
            "engine started; env=%s dry_run=%s cadence=%ss open=%d",
            self.creds.environment, self.dry_run, cadence, len(self.open_spreads),
        )
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(cadence)

    async def tick(self) -> None:
        now = datetime.now(tz=ET)
        if not self._is_market_open(now):
            log.debug("market closed at %s ET; skipping tick", now.strftime("%H:%M"))
            return

        # Always manage first (close/roll before opening new positions).
        await self.manage_open_spreads()

        if self._in_entry_window(now):
            await self.scan_and_enter()

    # ---- entry ------------------------------------------------------------

    async def scan_and_enter(self) -> None:
        risk = self.config["risk"]
        if len(self.open_spreads) >= risk["max_concurrent_spreads"]:
            return

        total_debit = sum(s.debit_paid for s in self.open_spreads)
        if total_debit >= risk["max_total_debit"]:
            log.info("total debit cap reached (%.0f); not entering", total_debit)
            return

        underlyings = self.config["underlyings"]
        # Skip underlyings we already have a spread on (cap = 1 by default).
        already_open = {s.underlying for s in self.open_spreads}
        candidates_by_underlying: dict[str, list[CalendarCandidate]] = {}

        metrics = {
            m.get("symbol"): m
            for m in await self.client.get_market_metrics(underlyings)
        }
        for u in underlyings:
            if u in already_open and risk["max_spreads_per_underlying"] <= 1:
                continue
            try:
                spot = await self._get_spot(u)
            except Exception as e:
                log.warning("%s: spot lookup failed: %s", u, e)
                continue
            m = metrics.get(u, {})
            iv_rank = self._safe_float(m.get("implied-volatility-index-rank"))
            if iv_rank is not None:
                iv_rank *= 100  # tastytrade returns 0..1
            earnings_dte = self._earnings_dte(m)

            cands = await self.scanner.scan_underlying(
                u, spot_price=spot, iv_rank=iv_rank, earnings_dte=earnings_dte,
            )
            await self._enrich_with_quotes(u, cands)
            # Re-filter after enrichment (quotes may invalidate liquidity/debit gates).
            cands = [c for c in cands if self._post_enrich_ok(c)]
            cands.sort(key=lambda c: c.score, reverse=True)
            if cands:
                candidates_by_underlying[u] = cands
                top = cands[0]
                log.info("%s: top candidate -> %s (score=%.3f)", u, top.rationale, top.score)

        # Across all underlyings, pick the best non-conflicting candidate(s) until caps fill.
        slots = risk["max_concurrent_spreads"] - len(self.open_spreads)
        budget = risk["max_total_debit"] - total_debit
        ranked: list[CalendarCandidate] = [
            cands[0] for cands in candidates_by_underlying.values()
        ]
        ranked.sort(key=lambda c: c.score, reverse=True)

        for cand in ranked:
            if slots <= 0:
                break
            cost = cand.debit * 100
            if cost > budget:
                continue
            await self._open_spread(cand)
            slots -= 1
            budget -= cost

    async def _open_spread(self, cand: CalendarCandidate) -> None:
        order = build_open_order(cand, quantity=1)
        log.info(
            "OPEN  %s %s K=%.2f short=%s long=%s debit=$%.2f score=%.3f",
            cand.underlying, cand.option_type, cand.strike,
            cand.short_expiration, cand.long_expiration, cand.debit * 100, cand.score,
        )
        await self._submit(order, label="open")
        self.open_spreads.append(
            OpenSpread(
                underlying=cand.underlying,
                option_type=cand.option_type,
                strike=cand.strike,
                long=OptionContract(
                    underlying=cand.underlying,
                    expiration=cand.long_expiration,
                    strike=cand.strike,
                    option_type=cand.option_type,
                ),
                short=OptionContract(
                    underlying=cand.underlying,
                    expiration=cand.short_expiration,
                    strike=cand.strike,
                    option_type=cand.option_type,
                ),
                debit_paid=cand.debit * 100,
                opened_at=datetime.now(tz=ET),
            )
        )
        self._save_state()

    # ---- management -------------------------------------------------------

    async def manage_open_spreads(self) -> None:
        if not self.open_spreads:
            return
        for spread in list(self.open_spreads):
            try:
                await self._manage_one(spread)
            except Exception:
                log.exception("manage failed for %s K=%.2f", spread.underlying, spread.strike)

    async def _manage_one(self, spread: OpenSpread) -> None:
        # Pull current quotes for both legs.
        quotes = await self.client.get_option_quotes(
            [spread.long.occ_symbol, spread.short.occ_symbol]
        )
        if len(quotes) < 2:
            log.warning(
                "could not quote both legs for %s K=%.2f", spread.underlying, spread.strike
            )
            return
        by_sym = {q.get("symbol"): q for q in quotes}
        long_q = by_sym.get(spread.long.occ_symbol, {})
        short_q = by_sym.get(spread.short.occ_symbol, {})
        long_mid = self._mid_from_quote(long_q)
        short_mid = self._mid_from_quote(short_q)
        if long_mid <= 0 or short_mid <= 0:
            log.warning("zero/missing mid for %s; skipping", spread.underlying)
            return
        spread_mid = long_mid - short_mid

        spot = await self._get_spot(spread.underlying)
        listed = await self._list_strikes_near(spread.underlying, spread.strike)

        decision = self.manager.evaluate(
            spread=spread,
            current_spread_mid=spread_mid,
            underlying_price=spot,
            listed_strikes=listed,
        )
        log.info(
            "MANAGE %s K=%.2f mid=%.2f pnl=%+.1f%% spot=%.2f -> %s (%s)",
            spread.underlying, spread.strike, spread_mid,
            ((spread_mid * 100 - spread.debit_paid) / spread.debit_paid * 100) if spread.debit_paid else 0.0,
            spot, decision.action, decision.reason,
        )

        if decision.action == ManagementAction.CLOSE:
            order = build_close_order(spread, spread_mid)
            await self._submit(order, label="close")
            self.open_spreads.remove(spread)
            self._save_state()
        elif decision.action == ManagementAction.ROLL_SHORT:
            await self._roll_short(spread)

    async def _roll_short(self, spread: OpenSpread) -> None:
        """Roll the short leg to the next eligible expiration at the same strike."""
        chain = await self.client.get_option_chain_nested(spread.underlying)
        expirations = chain.get("items", [{}])[0].get("expirations", [])
        today = date.today()
        eligible = []
        for e in expirations:
            d = (date.fromisoformat(e["date"]) - today).days
            if self.config["entry"]["short_dte_min"] <= d <= self.config["entry"]["short_dte_max"]:
                if e["date"] > spread.short.expiration:
                    eligible.append(e)
        if not eligible:
            log.info("%s: no eligible roll target; closing instead", spread.underlying)
            # Fallback: close
            quotes = await self.client.get_option_quotes(
                [spread.long.occ_symbol, spread.short.occ_symbol]
            )
            by_sym = {q.get("symbol"): q for q in quotes}
            mid = self._mid_from_quote(by_sym.get(spread.long.occ_symbol, {})) - \
                  self._mid_from_quote(by_sym.get(spread.short.occ_symbol, {}))
            await self._submit(build_close_order(spread, mid), label="close-fallback")
            self.open_spreads.remove(spread)
            self._save_state()
            return

        new_exp = eligible[0]["date"]
        # Find the same strike in the new expiration.
        target_occ = None
        for s in eligible[0].get("strikes", []):
            if abs(float(s["strike-price"]) - spread.strike) < 1e-6:
                target_occ = s.get("call" if spread.option_type == "C" else "put")
                break
        if not target_occ:
            log.warning("%s: strike %.2f not listed in %s", spread.underlying, spread.strike, new_exp)
            return

        # Build the roll order via free function (avoid importing here to keep cycle simple).
        from .strategy.calendar import build_roll_short_order
        quotes = await self.client.get_option_quotes([spread.short.occ_symbol, target_occ])
        by_sym = {q.get("symbol"): q for q in quotes}
        old_mid = self._mid_from_quote(by_sym.get(spread.short.occ_symbol, {}))
        new_mid = self._mid_from_quote(by_sym.get(target_occ, {}))
        credit = old_mid - new_mid  # buying old back at old_mid, selling new at new_mid

        new_short = OptionContract(
            underlying=spread.underlying,
            expiration=new_exp,
            strike=spread.strike,
            option_type=spread.option_type,
        )
        order = build_roll_short_order(spread, new_short, credit)
        log.info(
            "ROLL  %s K=%.2f short %s -> %s credit=%+.2f",
            spread.underlying, spread.strike, spread.short.expiration, new_exp, credit,
        )
        await self._submit(order, label="roll")
        spread.short = new_short
        # Adjust effective debit: receiving credit reduces our cost basis.
        spread.debit_paid -= credit * 100
        self._save_state()

    # ---- helpers ----------------------------------------------------------

    async def _submit(self, order: OrderRequest, label: str) -> None:
        if self.dry_run:
            log.info("[DRY-RUN %s] %s", label, json.dumps(order.to_payload()))
            return
        # Sanity: dry-run on tastytrade side first to catch BP issues.
        try:
            await self.client.dry_run_order(self.creds.account_number, order)
        except Exception as e:
            log.error("[%s] tastytrade dry-run rejected: %s", label, e)
            return
        result = await self.client.place_order(self.creds.account_number, order)
        log.info("[%s] submitted: order-id=%s", label, result.get("order", {}).get("id"))

    async def _get_spot(self, symbol: str) -> float:
        data = await self.client.get_equity_quote(symbol)
        bid = self._safe_float(data.get("bid"))
        ask = self._safe_float(data.get("ask"))
        last = self._safe_float(data.get("last"))
        if bid and ask:
            return (bid + ask) / 2
        if last:
            return last
        raise RuntimeError(f"no spot price for {symbol}")

    async def _enrich_with_quotes(
        self, underlying: str, candidates: list[CalendarCandidate]
    ) -> None:
        """Fill bid/ask/OI on candidates via /market-data/by-type."""
        if not candidates:
            return
        symbols = list({c.long_occ for c in candidates} | {c.short_occ for c in candidates})
        quotes = await self.client.get_option_quotes(symbols)
        by_sym = {q.get("symbol"): q for q in quotes}
        for c in candidates:
            lq = by_sym.get(c.long_occ, {})
            sq = by_sym.get(c.short_occ, {})
            l_bid = self._safe_float(lq.get("bid")) or 0.0
            l_ask = self._safe_float(lq.get("ask")) or 0.0
            s_bid = self._safe_float(sq.get("bid")) or 0.0
            s_ask = self._safe_float(sq.get("ask")) or 0.0
            l_mid = (l_bid + l_ask) / 2 if (l_bid and l_ask) else max(l_bid, l_ask)
            s_mid = (s_bid + s_ask) / 2 if (s_bid and s_ask) else max(s_bid, s_ask)
            c.long_mid = l_mid
            c.short_mid = s_mid
            c.debit = max(0.0, l_mid - s_mid)
            c.short_open_interest = int(self._safe_float(sq.get("open-interest")) or 0)
            c.long_open_interest = int(self._safe_float(lq.get("open-interest")) or 0)
            # Recompute bid/ask spread % from richest leg.
            def _pct(b: float, a: float) -> float:
                m = (b + a) / 2 if (b and a) else 0
                return abs(a - b) / m if m > 0 else 1.0
            c.bid_ask_spread_pct = max(_pct(l_bid, l_ask), _pct(s_bid, s_ask))
            # Refresh score with real numbers (theta still unknown without DXLink greeks).
            theta_proxy = c.short_mid  # premium as crude theta proxy
            theta_eff = (theta_proxy / c.debit) if c.debit > 0 else 0.0
            max_spread = self.config["entry"]["max_bid_ask_spread_pct"]
            liquidity = max(0.0, min(1.0, 1.0 - (c.bid_ask_spread_pct / max_spread))) if max_spread else 1.0
            c.score = theta_eff * liquidity

    def _post_enrich_ok(self, c: CalendarCandidate) -> bool:
        cfg = self.config["entry"]
        if c.debit <= 0:
            return False
        if c.debit * 100 > cfg["max_debit_per_spread"]:
            return False
        if c.short_open_interest < cfg["min_open_interest_short"]:
            return False
        if c.long_open_interest < cfg["min_open_interest_long"]:
            return False
        if c.bid_ask_spread_pct > cfg["max_bid_ask_spread_pct"]:
            return False
        return True

    async def _list_strikes_near(self, underlying: str, strike: float) -> list[float]:
        chain = await self.client.get_option_chain_nested(underlying)
        expirations = chain.get("items", [{}])[0].get("expirations", [])
        strikes: set[float] = set()
        for e in expirations:
            for s in e.get("strikes", []):
                strikes.add(float(s["strike-price"]))
        return sorted(strikes)

    @staticmethod
    def _mid_from_quote(q: dict[str, Any]) -> float:
        bid = Engine._safe_float(q.get("bid")) or 0.0
        ask = Engine._safe_float(q.get("ask")) or 0.0
        if bid and ask:
            return (bid + ask) / 2
        return max(bid, ask)

    @staticmethod
    def _safe_float(v: Any) -> float | None:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _earnings_dte(metrics: dict[str, Any]) -> int | None:
        earnings = metrics.get("earnings") or {}
        d = earnings.get("expected-report-date")
        if not d:
            return None
        try:
            return (date.fromisoformat(d) - date.today()).days
        except ValueError:
            return None

    def _is_market_open(self, now: datetime) -> bool:
        # Weekdays only; full US holiday calendar is out of scope here.
        if now.weekday() >= 5:
            return False
        start = now.replace(hour=9, minute=30, second=0, microsecond=0)
        end = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return start <= now <= end

    def _in_entry_window(self, now: datetime) -> bool:
        sched = self.config["schedule"]
        sh, sm = (int(x) for x in sched["entry_window_start"].split(":"))
        eh, em = (int(x) for x in sched["entry_window_end"].split(":"))
        start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
        return start <= now <= end
