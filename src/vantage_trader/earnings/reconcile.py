"""Broker <-> journal reconciliation. The broker is the source of truth; only the
journal is repaired (by appending ``heal`` events), never the broker.

Snapshot shape (CONTRACT leaves the details open; this is the interpretation):
  open_positions: [{"symbol","structure","opened","quantity"?,"entry_price"?}]
      one row per earnings STRUCTURE (agent aggregates broker option legs by symbol).
      ``quantity`` missing -> unknown: no qty_mismatch is raised for that row.
  recent_orders:  [{"order_id","symbol","state","position_effect"?:"open"|"close",
                    "legs"?:[{"position_effect",...}], "created_at"?, "price"?,
                    "quantity"?, "structure"?}]
      position_effect is taken from the top level, else from legs[].position_effect
      when all legs agree; otherwise unknown. Unknown is treated as "open" for the
      stale-order check (conservative) and never as "close".
  Symbols are strip().upper()'d everywhere.
      state: filled | cancelled/canceled/rejected/failed/expired | anything else = open
      (queued, unconfirmed, confirmed, partially_filled, ...).

Issue types and fixes (each issue: {"type","symbol","fix"}; ``fix`` is an object
{"description", "broker_action" | null, "journal_event" | null}):
  missing_fill      journal has *_submitted but broker shows the order filled (or, for
                    an entry with no broker order record, a position exists).
                    -> heal as_event entry_filled / exit_filled with the broker price.
  stale_open_order  broker entry order (position_effect open) still working at/after
                    ``cancel_by`` on its creation day.
                    -> broker_action cancel_order; journal_event heal as entry_cancelled
                       to append AFTER the cancel is confirmed.
  orphan_position   broker position with no open journal position -> heal as entry_filled.
  qty_mismatch      quantities differ; broker 0 (position gone, no fill record) ->
                    heal as exit_filled with unknown pnl (counted as a loss by the
                    circuit breaker); otherwise heal as qty_adjust to broker quantity.
Non-issue housekeeping: a journal *_submitted whose broker order was cancelled/rejected
gets a heal (entry_cancelled / exit_cancelled) in ``housekeeping``; it does not make
``consistent`` false.

``journal_appends`` lists every heal event that can be appended right away (all fixes
except stale_open_order, whose event waits on the broker cancel).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import journal as jr
from . import rules
from .config import EngineInputError, norm_symbol, parse_cancel_by

FILLED = {"filled"}
DEAD = {"cancelled", "canceled", "rejected", "failed", "expired"}


def _heal(as_of: str, issue: str, as_event: str, sym: str, notes: str, **fields: Any) -> dict[str, Any]:
    ev = {"ts": as_of, "event": "heal", "symbol": sym, "notes": f"{issue}: {notes}",
          "heal": {"type": issue, "as_event": as_event}}
    ev.update({k: v for k, v in fields.items() if v is not None})
    return ev


def position_effect(order: dict[str, Any]) -> str | None:
    pe = order.get("position_effect")
    if pe in ("open", "close"):
        return pe
    legs = order.get("legs")
    if isinstance(legs, list) and legs:
        effects = {l.get("position_effect") for l in legs if isinstance(l, dict)}
        if len(effects) == 1 and next(iter(effects)) in ("open", "close"):
            return next(iter(effects))
    return None


def _is_stale(order: dict[str, Any], now: datetime, cfg: dict[str, Any]) -> bool:
    h, m, tz = parse_cancel_by(cfg["cancel_by"])
    z = ZoneInfo(tz)
    created = rules.parse_ts(order["created_at"], "created_at").astimezone(z) if order.get("created_at") else now.astimezone(z)
    deadline = created.replace(hour=h, minute=m, second=0, microsecond=0)
    return now.astimezone(z) >= deadline


def reconcile(snapshot: dict[str, Any], events: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise EngineInputError("snapshot must be a JSON object")
    as_of = snapshot.get("as_of")
    now = rules.parse_ts(as_of)
    bpos_raw = snapshot.get("open_positions")
    orders = snapshot.get("recent_orders")
    if not isinstance(bpos_raw, list) or not isinstance(orders, list):
        raise EngineInputError("reconcile snapshot needs open_positions and recent_orders lists")
    for o in orders:
        if not isinstance(o, dict) or not o.get("order_id") or not o.get("symbol") or not o.get("state"):
            raise EngineInputError("each recent_order needs order_id, symbol, state")
    bpos: dict[str, dict[str, Any]] = {}
    for p in bpos_raw:
        if not isinstance(p, dict) or not p.get("symbol"):
            raise EngineInputError("each open_position needs a symbol")
        bpos[norm_symbol(p["symbol"])] = p
    by_id = {str(o["order_id"]): o for o in orders}

    issues: list[dict[str, Any]] = []
    housekeeping: list[dict[str, Any]] = []
    heals: list[dict[str, Any]] = []
    state = jr.open_state(events)
    journal_ids = {str(e.get("order_id")) for e in events if e.get("order_id")}

    # 1. pending journal orders vs broker order state
    for oid, sub in state["pending_orders"].items():
        sym = norm_symbol(sub.get("symbol"))
        phase = "entry" if jr.effective_event(sub) == "entry_submitted" else "exit"
        bo = by_id.get(oid)
        st = str(bo["state"]).lower() if bo else None
        carry = {k: sub.get(k) for k in ("structure", "implied_move", "edge_ratio", "max_loss", "direction")}
        if st in FILLED:
            ev = _heal(as_of, "missing_fill", f"{phase}_filled", sym,
                       f"broker shows order {oid} filled; journal had only {phase}_submitted",
                       order_id=oid, price=bo.get("price", sub.get("price")),
                       quantity=bo.get("quantity", sub.get("quantity")), **carry)
            heals.append(ev)
            issues.append({"type": "missing_fill", "symbol": sym,
                           "fix": {"description": f"append {phase}_filled heal for order {oid}",
                                   "broker_action": None, "journal_event": ev}})
        elif st in DEAD:
            ev = _heal(as_of, "order_closed", f"{phase}_cancelled", sym,
                       f"broker order {oid} is {st}", order_id=oid)
            heals.append(ev)
            housekeeping.append(ev)
        elif bo is None and phase == "entry" and sym in bpos and sym not in state["positions"]:
            bp = bpos[sym]
            ev = _heal(as_of, "missing_fill", "entry_filled", sym,
                       f"order {oid} not in recent_orders but broker holds a position",
                       order_id=oid, price=bp.get("entry_price", sub.get("price")),
                       quantity=bp.get("quantity", sub.get("quantity")), **carry)
            heals.append(ev)
            issues.append({"type": "missing_fill", "symbol": sym,
                           "fix": {"description": f"append entry_filled heal for order {oid}",
                                   "broker_action": None, "journal_event": ev}})

    # 2. stale working entry orders
    for o in orders:
        st = str(o["state"]).lower()
        if st in FILLED or st in DEAD or (position_effect(o) or "open") != "open":
            continue
        if _is_stale(o, now, cfg):
            sym = norm_symbol(o["symbol"])
            ev = _heal(as_of, "stale_open_order", "entry_cancelled", sym,
                       f"entry order {o['order_id']} still working past {cfg['cancel_by']}; "
                       "append only after broker confirms the cancel", order_id=str(o["order_id"]))
            issues.append({"type": "stale_open_order", "symbol": sym,
                           "fix": {"description": f"cancel order {o['order_id']}, then append journal_event",
                                   "broker_action": {"action": "cancel_order", "order_id": str(o["order_id"])},
                                   "journal_event": ev}})

    # 3. positions (after virtually applying the fill heals)
    jpos = jr.open_state(list(events) + heals)["positions"]
    jpos = {norm_symbol(k): v for k, v in jpos.items()}
    for sym, bp in bpos.items():
        if sym not in jpos:
            ev = _heal(as_of, "orphan_position", "entry_filled", sym,
                       "broker holds a position the journal does not know; adopting it "
                       "(exit snapshot must mark it provenance=reconstructed)",
                       structure=bp.get("structure"), quantity=bp.get("quantity", 1), provenance="reconstructed",
                       price=bp.get("entry_price"), direction=bp.get("direction"))
            heals.append(ev)
            issues.append({"type": "orphan_position", "symbol": sym,
                           "fix": {"description": "adopt broker position into journal; exit rules now apply",
                                   "broker_action": None, "journal_event": ev}})
        else:
            bq = bp.get("quantity")
            if isinstance(bq, (int, float)) and not isinstance(bq, bool) and int(bq) != jpos[sym]["quantity"]:
                ev = _heal(as_of, "qty_mismatch", "qty_adjust", sym,
                           f"journal qty {jpos[sym]['quantity']} != broker qty {int(bq)}",
                           quantity=int(bq), structure=bp.get("structure"))
                heals.append(ev)
                issues.append({"type": "qty_mismatch", "symbol": sym,
                               "fix": {"description": "set journal quantity to broker quantity",
                                       "broker_action": None, "journal_event": ev}})
    for sym, jp in jpos.items():
        if sym in bpos:
            continue
        close = next((o for o in orders if norm_symbol(o["symbol"]) == sym and str(o["state"]).lower() in FILLED
                      and position_effect(o) == "close" and str(o["order_id"]) not in journal_ids), None)
        if close is not None:
            ev = _heal(as_of, "missing_fill", "exit_filled", sym,
                       f"broker close order {close['order_id']} filled but never journaled",
                       order_id=str(close["order_id"]), price=close.get("price"),
                       quantity=close.get("quantity", jp["quantity"]), structure=jp.get("structure"))
            itype = "missing_fill"
        else:
            ev = _heal(as_of, "qty_mismatch", "exit_filled", sym,
                       f"journal qty {jp['quantity']} but broker has none and no fill found; "
                       "pnl unknown (counted as loss) - review manually",
                       quantity=jp["quantity"], structure=jp.get("structure"))
            itype = "qty_mismatch"
        heals.append(ev)
        issues.append({"type": itype, "symbol": sym,
                       "fix": {"description": "close the journal position to match broker",
                               "broker_action": None, "journal_event": ev}})

    appends = [h for h in heals]
    return {"as_of": as_of, "consistent": not issues, "issues": issues,
            "housekeeping": housekeeping, "journal_appends": appends}
