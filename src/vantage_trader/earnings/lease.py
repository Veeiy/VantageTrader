"""Trader lease: one trading session at a time (P012, docs/earnings/FAILOVER.md).

The lease file (``state/earnings/trader_lease.json``) says which session may place orders
on a given US Pacific trading date:

    {"date": "YYYY-MM-DD", "holder": "head" | "standby", "since": UTC ISO time,
     "session": session id, "reason": text or null, "history": [up to 20 earlier leases]}

A session places orders only while it holds the lease for today. Allowed changes for a
date: no lease -> head; no lease -> standby (the head never checked in); head -> standby
(a takeover, with a reason); the same holder again changes nothing. Standby -> head on the
same date is refused unless the owner overrides it with a reason that quotes Brad. A
lease for an earlier date never blocks today.

This module is file logic only. The git push is the lock and is done by the caller.
"""
from __future__ import annotations

import json
import re
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import EngineInputError

ROLES = ("head", "standby")
HISTORY_MAX = 20
PACIFIC = ZoneInfo("America/Los_Angeles")
_QUOTE = re.compile(r"[\"“”]")


class LeaseHeld(EngineInputError):
    """The other role holds the lease for that date and the change is not allowed."""

    def __init__(self, message: str, holder: str, lease: dict[str, Any]):
        super().__init__(message)
        self.holder = holder
        self.lease = lease


def _check_date(value: Any, what: str) -> str:
    try:
        return _date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise EngineInputError(f"{what} must be a date YYYY-MM-DD, got {value!r}")


def _check(lease: Any, nested: bool = False) -> dict[str, Any]:
    if not isinstance(lease, dict):
        raise EngineInputError("lease must be a JSON object")
    _check_date(lease.get("date"), "lease date")
    if lease.get("holder") not in ROLES:
        raise EngineInputError(f"lease holder must be one of {ROLES}, got {lease.get('holder')!r}")
    for key in ("since", "session"):
        if not isinstance(lease.get(key), str) or not lease[key].strip():
            raise EngineInputError(f"lease {key} must be a non-empty string")
    if lease.get("reason") is not None and not isinstance(lease["reason"], str):
        raise EngineInputError("lease reason must be text or null")
    if not nested:
        hist = lease.get("history", [])
        if not isinstance(hist, list):
            raise EngineInputError("lease history must be a list")
        for h in hist:
            _check(h, nested=True)
    return lease


def read_lease(path: str | Path) -> dict[str, Any] | None:
    """The lease in ``path``; None when the file does not exist."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise EngineInputError(f"lease file is not valid JSON: {e}")
    return _check(data)


def write_lease(path: str | Path, lease: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_check(lease), indent=2) + "\n")


def pacific_today(now: datetime | None = None) -> str:
    """The US Pacific calendar date of ``now`` (default: the current time)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(PACIFIC).date().isoformat()


def _today(lease: dict[str, Any] | None, date: str) -> dict[str, Any] | None:
    return lease if lease and lease.get("date") == date else None


def may_trade(lease: dict[str, Any] | None, role: str, date: str) -> bool:
    """True only when ``role`` holds the lease for ``date``."""
    current = _today(lease, date)
    return bool(current and current["holder"] == role)


def take(lease: dict[str, Any] | None, role: str, session: str, date: str, now: datetime,
         reason: str | None = None, owner_override: bool = False) -> tuple[dict[str, Any], bool]:
    """Take the lease for ``date``. Returns (lease, changed). Raises LeaseHeld when refused."""
    if role not in ROLES:
        raise EngineInputError(f"role must be one of {ROLES}, got {role!r}")
    if not isinstance(session, str) or not session.strip():
        raise EngineInputError("session must be a non-empty session id")
    date = _check_date(date, "date")
    reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
    current = _today(lease, date)
    if current and current["holder"] == role:
        return lease, False  # type: ignore[return-value]
    if role == "standby" and not reason:
        raise EngineInputError("the standby takes the lease only with a reason (why the head is not working)")
    if current and current["holder"] == "standby":
        quotes_brad = bool(reason and "Brad" in reason and _QUOTE.search(reason))
        if not (owner_override and quotes_brad):
            raise LeaseHeld(f"the standby holds the lease for {date}: the head stays out until the next "
                            "trading date (an owner override needs a reason that quotes Brad)", "standby", current)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    history = list(lease.get("history", [])) if lease else []
    if lease:
        history.append({k: v for k, v in lease.items() if k != "history"})
    new = {"date": date, "holder": role,
           "since": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "session": session.strip(), "reason": reason, "history": history[-HISTORY_MAX:]}
    return new, True


def view(lease: dict[str, Any] | None, date: str) -> dict[str, Any]:
    """A small summary of the lease for ``date``, with one plain instruction."""
    current = _today(lease, date)
    if current is None:
        instruction = ("No session holds today's lease yet: the head takes it at its first check-in, "
                       "the standby only on a takeover.")
    elif current["holder"] == "head":
        instruction = "The head holds today's lease: the standby places no orders today."
    else:
        instruction = "The standby holds today's lease: the head places no orders today."
    return {"date": date, "holder": current["holder"] if current else None, "for_today": current is not None,
            "head_may_trade": may_trade(lease, "head", date),
            "standby_may_trade": may_trade(lease, "standby", date),
            "since": current["since"] if current else None,
            "session": current["session"] if current else None,
            "reason": current["reason"] if current else None,
            "instruction": instruction}
