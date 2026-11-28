"""Signed 1-day earnings moves from daily closes.

AMC ("pm") report on day D: close(D)       -> close(next trading day)
BMO ("am") report on day D: close(prev td) -> close(D)
move = close_after / close_before - 1   (signed fraction)

Trading calendar = the set of dates present in the bar list. A bar flagged
``interpolated`` is treated as MISSING (the day exists but its close is unknown),
so an event needing it is skipped with a reason rather than silently using the
neighbouring day. Duplicate dates are collapsed: a real bar wins over an
interpolated one. This covers the broker quirk where the last bar is repeated
and flagged interpolated.

Skip reasons: ``bad_timing``, ``report_date_not_in_bars``, ``no_prior_bar``,
``no_next_bar``, ``interpolated_or_missing_bar``, ``bad_close``.
Moves are returned in ascending event-date order.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .config import EngineInputError


def _parse_date(s: Any, what: str) -> date:
    try:
        return date.fromisoformat(str(s))
    except ValueError:
        raise EngineInputError(f"{what}: bad date {s!r}")


def build_calendar(bars: list[dict[str, Any]], symbol: str = "") -> tuple[list[date], dict[date, float | None]]:
    closes: dict[date, float | None] = {}
    for i, b in enumerate(bars):
        if not isinstance(b, dict) or "date" not in b:
            raise EngineInputError(f"bars[{symbol}][{i}] must be an object with a date")
        d = _parse_date(b["date"], f"bars[{symbol}][{i}]")
        c = b.get("close")
        interp = bool(b.get("interpolated", False))
        val: float | None
        if interp or c is None or isinstance(c, bool) or not isinstance(c, (int, float)) or c <= 0:
            val = None
        else:
            val = float(c)
        if d in closes and closes[d] is not None:
            continue  # keep the real bar already seen
        closes[d] = val
    days = sorted(closes)
    return days, closes


def compute_moves(bars: list[dict[str, Any]], events: list[dict[str, Any]], symbol: str = "") -> dict[str, Any]:
    days, closes = build_calendar(bars, symbol)
    idx = {d: i for i, d in enumerate(days)}
    out_moves: list[tuple[date, float]] = []
    skipped: list[dict[str, str]] = []
    seen: set[date] = set()
    for j, ev in enumerate(events):
        if not isinstance(ev, dict) or "date" not in ev:
            raise EngineInputError(f"events[{symbol}][{j}] must be an object with a date")
        d = _parse_date(ev["date"], f"events[{symbol}][{j}]")
        timing = ev.get("timing")
        if d in seen:
            skipped.append({"date": d.isoformat(), "reason": "duplicate_event"})
            continue
        seen.add(d)
        if timing not in ("am", "pm"):
            skipped.append({"date": d.isoformat(), "reason": "bad_timing"})
            continue
        if d not in idx:
            skipped.append({"date": d.isoformat(), "reason": "report_date_not_in_bars"})
            continue
        i = idx[d]
        if timing == "pm":
            if i + 1 >= len(days):
                skipped.append({"date": d.isoformat(), "reason": "no_next_bar"})
                continue
            before, after = closes[days[i]], closes[days[i + 1]]
        else:
            if i == 0:
                skipped.append({"date": d.isoformat(), "reason": "no_prior_bar"})
                continue
            before, after = closes[days[i - 1]], closes[days[i]]
        if before is None or after is None:
            skipped.append({"date": d.isoformat(), "reason": "interpolated_or_missing_bar"})
            continue
        out_moves.append((d, round(after / before - 1.0, 6)))
    out_moves.sort(key=lambda t: t[0])
    return {
        "moves": [m for _, m in out_moves],
        "dates": [d.isoformat() for d, _ in out_moves],
        "skipped": skipped,
    }


def compute_all(bars: dict[str, Any], events: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bars, dict) or not isinstance(events, dict):
        raise EngineInputError("bars and events must be JSON objects keyed by symbol")
    result: dict[str, Any] = {}
    for sym, evs in events.items():
        if not isinstance(evs, list):
            raise EngineInputError(f"events[{sym}] must be a list")
        sym_bars = bars.get(sym)
        if sym_bars is None:
            result[sym] = {"moves": [], "dates": [],
                           "skipped": [{"date": str(e.get("date")) if isinstance(e, dict) else "?",
                                        "reason": "no_bars_for_symbol"} for e in evs]}
            continue
        if not isinstance(sym_bars, list):
            raise EngineInputError(f"bars[{sym}] must be a list")
        result[sym] = compute_moves(sym_bars, evs, sym)
    return result
