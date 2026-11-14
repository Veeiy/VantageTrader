"""Self-check: do the files that drive the loop agree with each other?

Run after every journal write and before every commit
(``python -m vantage_trader.earnings selfcheck``). It reads files only. It does not
replace ``reconcile`` (journal vs a broker snapshot); it catches the cheaper class of
error where the journal, positions file and metrics drift apart.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import journal as jr
from . import lease as ls
from . import metrics as mt
from . import proposals as pr
from . import reflect as rf
from .config import EngineInputError


def _positions(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise EngineInputError(f"positions file is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise EngineInputError("positions file must be a JSON object")
    return data


def _lease(path: str | None) -> str:
    current = ls.read_lease(path) if path else None
    if current is None:
        return "no lease file"
    return f"{current['holder']} holds {current['date']}"


FUTURE_TOLERANCE = timedelta(minutes=2)


def _ts(value: Any) -> datetime | None:
    """A record's ``ts`` as an aware UTC time; None when absent or not ISO."""
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def selfcheck(journal: str, metrics: str, positions: str, lessons: str, proposals: str,
              lease: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    loaded: dict[str, Any] = {}

    def run(name: str, fn: Callable[[], str]) -> None:
        try:
            checks.append({"check": name, "ok": True, "detail": fn()})
        except (EngineInputError, ValueError, KeyError, TypeError) as e:
            checks.append({"check": name, "ok": False, "detail": str(e)})

    def load(key: str, reader: Callable[[str], Any], path: str) -> Callable[[], str]:
        def inner() -> str:
            loaded[key] = reader(path)
            return f"{len(loaded[key])} records" if hasattr(loaded[key], "__len__") else "ok"
        return inner

    run("journal_parses", load("journal", jr.read_journal, journal))
    run("metrics_parse", load("metrics", mt.read_metrics, metrics))
    run("lessons_parse", load("lessons", rf.read_lessons, lessons))
    run("proposals_parse", load("proposals", pr.read_proposals, proposals))
    run("positions_parse", load("positions", _positions, positions))
    run("lease_parses", lambda: _lease(lease))

    def positions_match_journal() -> str:
        engine = {s: int(v["quantity"]) for s, v in jr.open_state(loaded["journal"])["positions"].items()}
        book = {str(o["symbol"]).upper(): int(o["quantity"]) for o in loaded["positions"].get("open", []) or []}
        if engine != book:
            raise ValueError(f"journal says {engine}, positions file says {book}")
        return f"open: {book or 'flat'}"

    def metrics_match_positions() -> str:
        live = [r for r in loaded["metrics"] if r.get("live", True) and r.get("record") != "paper"]
        entered = {r["trade_id"]: str(r.get("symbol")).upper() for r in live if r["record"] == "entry"}
        exited = {r["trade_id"] for r in live if r["record"] == "exit"}
        open_syms = sorted(sym for tid, sym in entered.items() if tid not in exited)
        book = sorted(str(o["symbol"]).upper() for o in loaded["positions"].get("open", []) or [])
        if open_syms != book:
            raise ValueError(f"metrics show open {open_syms}, positions file shows {book}")
        return f"{len(book)} open trade(s) have entry records"

    def risk_within_cap() -> str:
        risk = loaded["positions"].get("risk")
        opens = loaded["positions"].get("open", []) or []
        if not risk:
            if opens:
                raise ValueError("open positions but no risk block in the positions file")
            return "flat"
        total = float(risk["total_max_loss_usd"]) + float(risk.get("exit_reserves_usd", 0))
        summed = sum(float(o.get("max_loss_usd") or 0) for o in opens)
        if abs(summed - float(risk["total_max_loss_usd"])) > 0.5:
            raise ValueError(f"risk block says {risk['total_max_loss_usd']}, positions sum to {summed}")
        if total > float(risk["cap_usd"]) + 1e-9:
            raise ValueError(f"max loss plus reserves {total} is above the cap {risk['cap_usd']}")
        return f"{total:.0f} of {float(risk['cap_usd']):.0f}"

    def no_future_timestamps() -> str:
        # Twice on 2026-11-13 the head wrote ledger times ahead of the clock (P037).
        clock = now or datetime.now(timezone.utc)
        late: list[str] = []
        for key in ("journal", "metrics", "lessons", "proposals"):
            for r in loaded.get(key) or []:
                t = _ts(r.get("ts")) if isinstance(r, dict) else None
                if t is not None and t > clock + FUTURE_TOLERANCE:
                    late.append(f"{key} {r.get('id') or r.get('trade_id') or r.get('symbol') or ''} {r['ts']}".replace("  ", " "))
        t = _ts((loaded.get("positions") or {}).get("as_of"))
        if t is not None and t > clock + FUTURE_TOLERANCE:
            late.append(f"positions as_of {loaded['positions']['as_of']}")
        if late:
            raise ValueError(f"{len(late)} record(s) dated ahead of the clock ({clock:%Y-%m-%dT%H:%MZ}): " + "; ".join(late[:5]))
        return "no record is dated ahead of the clock"

    run("no_future_timestamps", no_future_timestamps)
    if all(k in loaded for k in ("journal", "positions")):
        run("positions_match_journal", positions_match_journal)
    if all(k in loaded for k in ("metrics", "positions")):
        run("metrics_match_positions", metrics_match_positions)
    if "positions" in loaded:
        run("risk_within_cap", risk_within_cap)
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
