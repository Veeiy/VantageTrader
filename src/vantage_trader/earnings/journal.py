"""Append-only JSONL journal.

Line schema (CONTRACT): {"ts","event","symbol","structure","order_id","price",
"quantity","implied_move","edge_ratio","realized_move","pnl","notes"}.
Extra keys are allowed and preserved. Recognised optional extensions:

* ``max_loss`` on ``entry_filled`` (copy ``order.max_loss_worst`` or ``order.max_loss``
  from the decision). Used by the circuit breaker's "consecutive max-loss" rule.
  If a losing trade has no known max_loss it is CONSERVATIVELY counted as a
  max-loss trade.
* ``direction`` ("credit"|"debit"); inferred from structure when absent.
* ``heal`` on ``heal`` events: {"type": <issue type>, "as_event": <event>}. A heal
  event with ``as_event`` in {entry_filled, exit_filled, entry_cancelled,
  exit_cancelled} is treated as that event when deriving positions/trades; with
  ``as_event == "qty_adjust"`` it sets the open quantity for the symbol.

Closed trades = entry_filled paired FIFO per symbol with the next exit_filled.
pnl = exit event's ``pnl`` when present, else computed from prices
(credit: (entry-exit)*100*qty, debit: (exit-entry)*100*qty). If neither is
available pnl is None and the trade is treated as a LOSS for streaks.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import EngineInputError

EVENTS = {"scan", "entry_submitted", "entry_filled", "entry_cancelled", "exit_submitted",
          "exit_filled", "halt", "heal", "calibrate"}
CREDIT_STRUCTURES = {"iron_fly", "iron_condor"}
DEBIT_STRUCTURES = {"long_straddle", "long_strangle"}


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_journal(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for n, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise EngineInputError(f"journal line {n} is not valid JSON: {e}")
        if not isinstance(obj, dict) or obj.get("event") not in EVENTS:
            raise EngineInputError(f"journal line {n}: missing or unknown event")
        out.append(obj)
    return out


def append_event(path: str | Path, event: dict[str, Any]) -> dict[str, Any]:
    if event.get("event") not in EVENTS:
        raise EngineInputError(f"unknown journal event {event.get('event')!r}")
    ev = dict(event)
    ev.setdefault("ts", now_ts())
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(ev, sort_keys=True) + "\n")
    return ev


def effective_event(ev: dict[str, Any]) -> str:
    if ev.get("event") == "heal" and isinstance(ev.get("heal"), dict):
        return ev["heal"].get("as_event") or "heal"
    return ev.get("event", "")


def direction_of(ev: dict[str, Any]) -> str:
    d = ev.get("direction")
    if d in ("credit", "debit"):
        return d
    return "credit" if ev.get("structure") in CREDIT_STRUCTURES else "debit"


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def closed_trades(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    open_by_sym: dict[str, list[dict[str, Any]]] = {}
    trades: list[dict[str, Any]] = []
    for ev in events:
        kind = effective_event(ev)
        sym = ev.get("symbol")
        if kind == "entry_filled":
            open_by_sym.setdefault(sym, []).append(ev)
        elif kind == "exit_filled" and open_by_sym.get(sym):
            entry = open_by_sym[sym].pop(0)
            qty = _num(entry.get("quantity")) or _num(ev.get("quantity")) or 1
            ep, xp = _num(entry.get("price")), _num(ev.get("price"))
            direction = direction_of(entry)
            pnl = _num(ev.get("pnl"))
            if pnl is None and ep is not None and xp is not None:
                pnl = (ep - xp) * 100 * qty if direction == "credit" else (xp - ep) * 100 * qty
                pnl = round(pnl, 2)
            max_loss = _num(entry.get("max_loss")) or _num(ev.get("max_loss"))
            trades.append({
                "symbol": sym, "structure": entry.get("structure"), "direction": direction,
                "entry_ts": entry.get("ts"), "exit_ts": ev.get("ts"),
                "entry_price": ep, "exit_price": xp, "quantity": qty, "pnl": pnl,
                "max_loss": max_loss,
                "implied_move": _num(entry.get("implied_move")) or _num(ev.get("implied_move")),
                "edge_ratio": _num(entry.get("edge_ratio")) or _num(ev.get("edge_ratio")),
                "realized_move": _num(ev.get("realized_move")) if _num(ev.get("realized_move")) is not None
                else _num(entry.get("realized_move")),
            })
    return trades


def is_loss(t: dict[str, Any]) -> bool:
    return t["pnl"] is None or t["pnl"] < 0


def is_max_loss(t: dict[str, Any], tolerance: float) -> bool:
    if not is_loss(t):
        return False
    if t["pnl"] is None or not t.get("max_loss"):
        return True  # unknown -> conservative
    return -t["pnl"] >= tolerance * t["max_loss"] - 1e-9


def streaks(trades: list[dict[str, Any]], tolerance: float, since_ts: str | None = None) -> dict[str, int]:
    ts_sorted = sorted((t for t in trades if since_ts is None or str(t.get("exit_ts") or "") >= since_ts),
                       key=lambda t: str(t.get("exit_ts") or ""))
    losses = max_losses = 0
    for t in reversed(ts_sorted):
        if is_loss(t):
            losses += 1
        else:
            break
    for t in reversed(ts_sorted):
        if is_max_loss(t, tolerance):
            max_losses += 1
        else:
            break
    return {"consecutive_losses": losses, "consecutive_max_losses": max_losses,
            "closed_trades": len(ts_sorted)}


def open_state(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Derive journal view: open positions per symbol and pending (unresolved) orders."""
    positions: dict[str, dict[str, Any]] = {}
    pending: dict[str, dict[str, Any]] = {}
    for ev in events:
        kind = effective_event(ev)
        sym = ev.get("symbol")
        oid = ev.get("order_id")
        if kind in ("entry_submitted", "exit_submitted") and oid:
            pending[str(oid)] = ev
        elif kind in ("entry_filled", "entry_cancelled", "exit_filled", "exit_cancelled"):
            if oid:
                pending.pop(str(oid), None)
            else:
                # no id: resolve oldest pending order of same phase for that symbol
                phase = kind.split("_")[0] + "_submitted"
                for k, p in list(pending.items()):
                    if p.get("symbol") == sym and effective_event(p) == phase:
                        pending.pop(k)
                        break
        if kind == "entry_filled":
            pos = positions.setdefault(sym, {"symbol": sym, "structure": ev.get("structure"),
                                             "quantity": 0, "opened_ts": ev.get("ts")})
            pos["quantity"] += int(_num(ev.get("quantity")) or 1)
        elif kind == "exit_filled" and sym in positions:
            positions[sym]["quantity"] -= int(_num(ev.get("quantity")) or positions[sym]["quantity"])
            if positions[sym]["quantity"] <= 0:
                positions.pop(sym)
        elif kind == "qty_adjust":
            q = int(_num(ev.get("quantity")) or 0)
            if q <= 0:
                positions.pop(sym, None)
            else:
                positions.setdefault(sym, {"symbol": sym, "structure": ev.get("structure"),
                                           "quantity": q, "opened_ts": ev.get("ts")})["quantity"] = q
    return {"positions": positions, "pending_orders": pending}
