"""Engine loop: scan -> rank -> enter -> manage -> close.

Responsibilities:
  - Connect & maintain the DXLink greeks streamer for option subscriptions
  - Drive the entry window (one-shot per day) and management cadence
  - Track open spreads, persist state across restarts
  - Submit orders (or log them in dry-run mode)
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .agents import (
    AgentRuntime,
    DailyReport,
    ReviewResult,
    candidate_to_payload,
    generate_report,
    register_journalist,
    register_reviewer,
    review,
)
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
from .tastytrade.streamer import DXLinkStreamer

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
STATE_FILE = Path("state/open_spreads.json")
JOURNAL_FILE = Path("state/journal.jsonl")
REPORTS_DIR = Path("reports")


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
        self.streamer: DXLinkStreamer | None = None
        self._last_entry_date: date | None = None
        self.agents_cfg: dict[str, Any] = config.get("agents") or {}
        self.agent_runtime: AgentRuntime | None = None
        if self.agents_cfg.get("enabled"):
            self.agent_runtime = AgentRuntime(
                environment_id=self.agents_cfg.get("environment_id"),
            )
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
        last = data.get("last_entry_date")
        if last:
            try:
                self._last_entry_date = date.fromisoformat(last)
            except ValueError:
                pass
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
            ],
            "last_entry_date": self._last_entry_date.isoformat() if self._last_entry_date else None,
        }
        STATE_FILE.write_text(json.dumps(payload, indent=2))

    # ---- lifecycle --------------------------------------------------------

    async def start_streamer(self) -> None:
        token_data = await self.client.get_quote_streamer_token()
        url = token_data.get("dxlink-url") or token_data.get("websocket-url")
        token = token_data.get("token")
        if not url or not token:
            raise RuntimeError(f"missing dxlink url/token in {token_data}")
        self.streamer = DXLinkStreamer(url=url, token=token)
        await self.streamer.connect()

    async def run_forever(self) -> None:
        cadence = self.config["schedule"]["manage_every_seconds"]
        log.info(
            "engine starting; env=%s dry_run=%s cadence=%ss open=%d",
            self.creds.environment, self.dry_run, cadence, len(self.open_spreads),
        )
        await self.start_streamer()
        try:
            while True:
                try:
                    await self.tick()
                except Exception:
                    log.exception("tick failed")
                await asyncio.sleep(cadence)
        finally:
            if self.streamer is not None:
                await self.streamer.close()

    async def tick(self) -> None:
        now = datetime.now(tz=ET)
        if not self._is_market_open(now):
            log.debug("market closed at %s ET; skipping tick", now.strftime("%H:%M"))
            return

        # Manage first so capital frees up before we scan for new entries.
        await self.manage_open_spreads(now)

        if self._in_entry_window(now) and self._last_entry_date != now.date():
            await self.scan_and_enter()
            self._last_entry_date = now.date()
            self._save_state()

    # ---- entry ------------------------------------------------------------

    async def scan_and_enter(self) -> None:
        risk = self.config["risk"]
        if len(self.open_spreads) >= risk["max_concurrent_spreads"]:
            log.info("concurrent-spread cap (%d) reached; skipping entry", risk["max_concurrent_spreads"])
            return

        total_debit = sum(s.debit_paid for s in self.open_spreads)
        budget = risk["max_total_debit"] - total_debit
        if budget <= 0:
            log.info("total debit cap reached (%.0f); not entering", total_debit)
            return

        underlyings = self.config["underlyings"]
        already_open = {s.underlying for s in self.open_spreads}
        metrics_by_sym = {
            m.get("symbol"): m
            for m in await self.client.get_market_metrics(underlyings)
        }

        all_candidates: list[CalendarCandidate] = []
        for u in underlyings:
            if u in already_open and risk["max_spreads_per_underlying"] <= 1:
                continue
            try:
                cands = await self._scan_one_underlying(u, metrics_by_sym.get(u, {}))
            except Exception:
                log.exception("%s: scan failed", u)
                continue
            for c in cands:
                log.info("CAND %s %s", u, c.rationale)
            if cands:
                all_candidates.append(cands[0])

        all_candidates.sort(key=lambda c: c.score, reverse=True)

        slots = risk["max_concurrent_spreads"] - len(self.open_spreads)
        for cand in all_candidates:
            if slots <= 0:
                break
            cost = cand.debit * 100
            if cost > budget:
                continue
            await self._open_spread(cand)
            slots -= 1
            budget -= cost

    async def _scan_one_underlying(
        self, underlying: str, metrics: dict[str, Any]
    ) -> list[CalendarCandidate]:
        iv_rank = self._safe_float(metrics.get("implied-volatility-index-rank"))
        if iv_rank is not None:
            iv_rank *= 100  # tastytrade returns 0..1
        if iv_rank is not None and iv_rank > self.config["entry"]["iv_rank_max"]:
            log.info("%s: skip (IV rank %.1f > max %.1f)",
                     underlying, iv_rank, self.config["entry"]["iv_rank_max"])
            return []

        earnings_dte = self._earnings_dte(metrics)
        if earnings_dte is not None and 0 <= earnings_dte <= self.config["entry"]["skip_if_earnings_within_days"]:
            log.info("%s: skip (earnings in %d days)", underlying, earnings_dte)
            return []

        chain = await self.client.get_option_chain_nested(underlying)
        spot = await self._get_spot(underlying)

        target_rows = self.scanner.gather_target_strikes(chain, spot)
        if not target_rows:
            log.info("%s: no overlapping strikes in DTE windows", underlying)
            return []

        # Subscribe greeks for short-DTE strikes around spot.
        if self.streamer is None:
            raise RuntimeError("streamer not started")
        short_streamer_syms: set[str] = set()
        for r in target_rows:
            short_streamer_syms.add(r.call_streamer)
            short_streamer_syms.add(r.put_streamer)
        # Long greeks too, so we can compute term-structure kicker.
        long_streamer_syms = self._collect_long_streamer_symbols(chain, [r.strike for r in target_rows])

        all_sub = list(short_streamer_syms | long_streamer_syms)
        await self.streamer.subscribe_greeks(all_sub)
        greeks_now = await self.streamer.wait_for_greeks(all_sub, timeout=5.0)
        if len(greeks_now) < len(all_sub):
            log.info("%s: greeks coverage %d/%d (proceeding with partial)",
                     underlying, len(greeks_now), len(all_sub))

        # Fetch REST quotes for all candidate option OCC symbols (bid/ask/OI).
        all_occ: set[str] = set()
        for r in target_rows:
            all_occ.add(r.call_occ)
            all_occ.add(r.put_occ)
        all_occ |= self._collect_long_occ_symbols(chain, [r.strike for r in target_rows])
        quote_items = await self.client.get_option_quotes(list(all_occ))
        quotes_by_sym = {q.get("symbol"): q for q in quote_items}

        # Build candidates for every (short_exp, long_exp, side) combo.
        pairs = self.scanner.expiration_pairs(chain)
        candidates: list[CalendarCandidate] = []
        for short_exp, long_exp in pairs:
            for side in self.scanner.sides_to_consider(spot, spot):  # side filter resolved per-strike inside
                cand = self.scanner.build_candidate(
                    underlying=underlying,
                    spot=spot,
                    short_exp=short_exp,
                    long_exp=long_exp,
                    side=side,
                    quotes=quotes_by_sym,
                    greeks=greeks_now,
                )
                if cand is None:
                    continue
                # When direction == 'auto' we want short OTM at the chosen strike.
                if self.config["entry"].get("direction", "auto") == "auto":
                    expected_side = "C" if spot < cand.strike else "P"
                    if cand.option_type != expected_side:
                        continue
                candidates.append(cand)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    async def _open_spread(self, cand: CalendarCandidate) -> None:
        review_result = await self._consult_reviewer(cand)
        if review_result and review_result.verdict == "VETO" and self._veto_enforced():
            log.info(
                "[VETO enforced] skipping open for %s K=%.2f",
                cand.underlying, cand.strike,
            )
            return
        order = build_open_order(cand, quantity=1)
        log.info(
            "OPEN  %s %s K=%.2f short=%s long=%s debit=$%.2f delta=%+.2f theta=%.3f score=%.4f",
            cand.underlying, cand.option_type, cand.strike,
            cand.short_expiration, cand.long_expiration, cand.debit * 100,
            cand.short_delta or 0.0, cand.short_theta or 0.0, cand.score,
        )
        await self._submit(order, label="open")
        opened_at = datetime.now(tz=ET)
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
                opened_at=opened_at,
            )
        )
        self._append_journal({
            "ts": opened_at.isoformat(),
            "kind": "open",
            "underlying": cand.underlying,
            "option_type": cand.option_type,
            "strike": cand.strike,
            "short_expiration": cand.short_expiration,
            "long_expiration": cand.long_expiration,
            "debit_paid": round(cand.debit * 100, 2),
            "short_delta": cand.short_delta,
            "short_theta": cand.short_theta,
            "long_iv": cand.long_iv,
            "short_iv": cand.short_iv,
            "theta_per_dollar": cand.theta_per_dollar,
            "score": cand.score,
            "rationale": cand.rationale,
            "reviewer_verdict": review_result.verdict if review_result else None,
            "reviewer_reason": review_result.reason if review_result else None,
        })
        self._save_state()

    # ---- agent team -------------------------------------------------------

    def _veto_enforced(self) -> bool:
        return bool((self.agents_cfg.get("reviewer") or {}).get("veto_enforced"))

    async def _consult_reviewer(self, cand: CalendarCandidate) -> ReviewResult | None:
        """Run the Trade Reviewer on this candidate and log the verdict.

        Returns the parsed result, or None if the reviewer is disabled or
        the call failed (so the engine's deterministic decision stands).
        """
        rcfg = self.agents_cfg.get("reviewer") or {}
        if not (self.agent_runtime and rcfg.get("enabled")):
            return None
        try:
            await self._ensure_reviewer_registered()
            spot = await self._get_spot(cand.underlying)
            payload = candidate_to_payload(cand, spot=spot)
            result: ReviewResult = await review(self.agent_runtime, payload)
        except Exception:
            log.exception("reviewer call failed; falling back to rule-based decision")
            return None
        log.info(
            "REVIEW %s K=%.2f %s -- %s",
            cand.underlying, cand.strike, result.verdict, result.reason,
        )
        return result

    async def _ensure_reviewer_registered(self) -> None:
        rcfg = self.agents_cfg.get("reviewer") or {}
        assert self.agent_runtime is not None
        from .agents.reviewer import REVIEWER_KEY
        if self.agent_runtime.agent_id(REVIEWER_KEY):
            return
        await register_reviewer(
            self.agent_runtime,
            model=rcfg.get("model", "claude-opus-4-7"),
            agent_id=rcfg.get("agent_id"),
        )

    async def _ensure_journalist_registered(self) -> None:
        jcfg = self.agents_cfg.get("journalist") or {}
        assert self.agent_runtime is not None
        from .agents.journalist import JOURNALIST_KEY
        if self.agent_runtime.agent_id(JOURNALIST_KEY):
            return
        await register_journalist(
            self.agent_runtime,
            model=jcfg.get("model", "claude-opus-4-7"),
            agent_id=jcfg.get("agent_id"),
        )

    # ---- journal & daily report ------------------------------------------

    def _append_journal(self, entry: dict[str, Any]) -> None:
        try:
            JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
            with JOURNAL_FILE.open("a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except OSError as e:
            log.warning("journal append failed: %s", e)

    @staticmethod
    def _read_journal(path: Path = JOURNAL_FILE) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                log.warning("skipping malformed journal line: %s", e)
        return entries

    @staticmethod
    def _filter_by_date(entries: list[dict[str, Any]], target: date) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for e in entries:
            ts = e.get("ts", "")
            try:
                d = datetime.fromisoformat(ts).date()
            except ValueError:
                continue
            if d == target:
                out.append(e)
        return out

    def _open_spreads_snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "underlying": s.underlying,
                "option_type": s.option_type,
                "strike": s.strike,
                "short_expiration": s.short.expiration,
                "long_expiration": s.long.expiration,
                "debit_paid": s.debit_paid,
                "opened_at": s.opened_at.isoformat(),
            }
            for s in self.open_spreads
        ]

    async def generate_daily_report(self, target: date | None = None) -> DailyReport:
        """Run the Post-Mortem Journalist for the given trading day.

        Reads `state/journal.jsonl`, filters to `target` (default: today in
        ET), sends the events + currently-open spreads to the journalist
        agent, and writes the returned markdown to `reports/YYYY-MM-DD.md`.
        """
        if self.agent_runtime is None:
            raise RuntimeError(
                "agents.enabled is false in config; cannot generate report"
            )
        jcfg = self.agents_cfg.get("journalist") or {}
        if not jcfg.get("enabled"):
            raise RuntimeError("agents.journalist.enabled is false in config")

        day = target or datetime.now(tz=ET).date()
        all_entries = self._read_journal()
        todays = self._filter_by_date(all_entries, day)
        log.info(
            "daily-report %s: %d journal entries, %d open spreads",
            day.isoformat(), len(todays), len(self.open_spreads),
        )

        await self._ensure_journalist_registered()
        report = await generate_report(
            self.agent_runtime,
            date=day.isoformat(),
            events=todays,
            still_open=self._open_spreads_snapshot(),
        )

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = REPORTS_DIR / f"{day.isoformat()}.md"
        out_path.write_text(report.markdown)
        report.path_written = str(out_path)
        log.info("daily-report written to %s (%d chars)", out_path, len(report.markdown))
        return report

    # ---- management -------------------------------------------------------

    async def manage_open_spreads(self, now: datetime) -> None:
        if not self.open_spreads:
            return
        minutes_to_close = self._minutes_until_close(now)
        for spread in list(self.open_spreads):
            try:
                await self._manage_one(spread, minutes_to_close)
            except Exception:
                log.exception("manage failed for %s K=%.2f", spread.underlying, spread.strike)

    async def _manage_one(self, spread: OpenSpread, minutes_to_close: int | None) -> None:
        quotes = await self.client.get_option_quotes(
            [spread.long.occ_symbol, spread.short.occ_symbol]
        )
        if len(quotes) < 2:
            log.warning("could not quote both legs for %s K=%.2f", spread.underlying, spread.strike)
            return
        by_sym = {q.get("symbol"): q for q in quotes}
        long_mid = self._mid_from_quote(by_sym.get(spread.long.occ_symbol, {}))
        short_mid = self._mid_from_quote(by_sym.get(spread.short.occ_symbol, {}))
        if long_mid <= 0 or short_mid <= 0:
            log.warning("zero/missing mid for %s; skipping", spread.underlying)
            return
        spread_mid = long_mid - short_mid

        spot = await self._get_spot(spread.underlying)
        listed = await self._list_strikes(spread.underlying)

        decision = self.manager.evaluate(
            spread=spread,
            current_spread_mid=spread_mid,
            underlying_price=spot,
            listed_strikes=listed,
            minutes_to_close=minutes_to_close,
        )
        pnl_pct = ((spread_mid * 100 - spread.debit_paid) / spread.debit_paid * 100) if spread.debit_paid else 0.0
        log.info(
            "MANAGE %s K=%.2f mid=%.2f pnl=%+.1f%% spot=%.2f -> %s (%s)",
            spread.underlying, spread.strike, spread_mid, pnl_pct, spot,
            decision.action, decision.reason,
        )

        if decision.action == ManagementAction.CLOSE:
            order = build_close_order(spread, spread_mid)
            await self._submit(order, label="close")
            close_value = round(spread_mid * 100, 2)
            self._append_journal({
                "ts": datetime.now(tz=ET).isoformat(),
                "kind": "close",
                "underlying": spread.underlying,
                "option_type": spread.option_type,
                "strike": spread.strike,
                "short_expiration": spread.short.expiration,
                "long_expiration": spread.long.expiration,
                "debit_paid": spread.debit_paid,
                "close_value": close_value,
                "pnl_dollars": round(close_value - spread.debit_paid, 2),
                "pnl_pct": round(pnl_pct / 100.0, 4),
                "reason": decision.reason,
                "opened_at": spread.opened_at.isoformat(),
            })
            self.open_spreads.remove(spread)
            self._save_state()

    # ---- helpers ----------------------------------------------------------

    async def _submit(self, order: OrderRequest, label: str) -> None:
        if self.dry_run:
            log.info("[DRY-RUN %s] %s", label, json.dumps(order.to_payload()))
            return
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

    async def _list_strikes(self, underlying: str) -> list[float]:
        chain = await self.client.get_option_chain_nested(underlying)
        expirations = chain.get("items", [{}])[0].get("expirations", [])
        strikes: set[float] = set()
        for e in expirations:
            for s in e.get("strikes", []):
                strikes.add(float(s["strike-price"]))
        return sorted(strikes)

    def _collect_long_streamer_symbols(
        self, chain: dict[str, Any], strikes: list[float]
    ) -> set[str]:
        out: set[str] = set()
        today = date.today()
        for e in chain.get("items", [{}])[0].get("expirations", []):
            dte = (date.fromisoformat(e["date"]) - today).days
            if not (self.config["entry"]["long_dte_min"] <= dte <= self.config["entry"]["long_dte_max"]):
                continue
            for s in e.get("strikes", []):
                strike = float(s["strike-price"])
                if any(abs(strike - k) < 1e-6 for k in strikes):
                    if s.get("call-streamer-symbol"):
                        out.add(s["call-streamer-symbol"])
                    if s.get("put-streamer-symbol"):
                        out.add(s["put-streamer-symbol"])
        return out

    def _collect_long_occ_symbols(
        self, chain: dict[str, Any], strikes: list[float]
    ) -> set[str]:
        out: set[str] = set()
        today = date.today()
        for e in chain.get("items", [{}])[0].get("expirations", []):
            dte = (date.fromisoformat(e["date"]) - today).days
            if not (self.config["entry"]["long_dte_min"] <= dte <= self.config["entry"]["long_dte_max"]):
                continue
            for s in e.get("strikes", []):
                strike = float(s["strike-price"])
                if any(abs(strike - k) < 1e-6 for k in strikes):
                    if s.get("call"):
                        out.add(s["call"])
                    if s.get("put"):
                        out.add(s["put"])
        return out

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

    @staticmethod
    def _minutes_until_close(now: datetime) -> int | None:
        if now.weekday() >= 5:
            return None
        close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        delta = (close - now).total_seconds() / 60
        if delta < 0:
            return None
        return int(delta)
