"""Daily reflection support: the day pack and the lessons ledger.

The loop (``docs/earnings/REFLECTION.md``): after each trading day the head agent
builds the day pack, grades the day's decisions, and records what it learned as
lessons with evidence. Nothing here places orders or changes rules.

Lessons ledger (``state/earnings/lessons.jsonl``), append-only, three event types:
  {"event": "lesson",   "id", "kind", "statement", "test", "status", "ts"}
  {"event": "evidence", "id", "date", "verdict", "ref", "note", "ts"}
  {"event": "status",   "id", "status", "note", "approved_by", "ts"}

Guardrails enforced on read (a violation is an input error, not a warning):
  * kinds ``execution``, ``process`` and ``data`` change HOW the rules are carried out and
    may start ``active``;
  * kinds ``rule`` and ``risk`` change WHAT is traded or how much is at risk. They start
    as ``hypothesis`` and can only become ``adopted`` through a status event that names
    who approved it (``approved_by``). The loop can propose, never adopt.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import journal as jr
from .config import EngineInputError

LESSON_EVENTS = {"lesson", "evidence", "status"}
KINDS = {"execution", "process", "data", "rule", "risk"}
SELF_ADOPT_KINDS = {"execution", "process", "data"}
STATUSES = {"hypothesis", "active", "proposed", "adopted", "retired"}
VERDICTS = {"supports", "contradicts", "neutral"}
MIN_OBSERVATIONS = 8      # supports + contradicts before a rule/risk hypothesis may be proposed
SUPPORT_RATIO = 2.0       # supports must be at least this multiple of contradicts
NOTE_CHARS = 220


def read_lessons(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    kinds: dict[str, str] = {}
    for n, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError as e:
            raise EngineInputError(f"lessons line {n} is not valid JSON: {e}")
        if not isinstance(ev, dict) or ev.get("event") not in LESSON_EVENTS or not ev.get("id"):
            raise EngineInputError(f"lessons line {n}: missing id or unknown event")
        lid, kind_of = str(ev["id"]), ev.get("event")
        if kind_of == "lesson":
            if lid in kinds:
                raise EngineInputError(f"lessons line {n}: duplicate lesson id {lid}")
            if ev.get("kind") not in KINDS or not str(ev.get("statement") or "").strip():
                raise EngineInputError(f"lessons line {n}: lesson needs a known kind and a statement")
            status = ev.get("status", "hypothesis")
            if status not in ("hypothesis", "active"):
                raise EngineInputError(f"lessons line {n}: a lesson starts as hypothesis or active")
            if status == "active" and ev["kind"] not in SELF_ADOPT_KINDS:
                raise EngineInputError(
                    f"lessons line {n}: a {ev['kind']} lesson cannot start active; it starts as a hypothesis")
            kinds[lid] = ev["kind"]
        else:
            if lid not in kinds:
                raise EngineInputError(f"lessons line {n}: {kind_of} for unknown lesson {lid}")
            if kind_of == "evidence" and ev.get("verdict") not in VERDICTS:
                raise EngineInputError(f"lessons line {n}: verdict must be one of {sorted(VERDICTS)}")
            if kind_of == "status":
                if ev.get("status") not in STATUSES:
                    raise EngineInputError(f"lessons line {n}: unknown status")
                if kinds[lid] not in SELF_ADOPT_KINDS:
                    if ev["status"] == "active":
                        raise EngineInputError(
                            f"lessons line {n}: a {kinds[lid]} lesson is adopted with approval, never set active")
                    if ev["status"] == "adopted" and not str(ev.get("approved_by") or "").strip():
                        raise EngineInputError(
                            f"lessons line {n}: adopting a {kinds[lid]} lesson needs approved_by")
        out.append(ev)
    return out


def fold_lessons(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Current state per lesson id: status, tallies, last evidence date."""
    state: dict[str, dict[str, Any]] = {}
    for ev in events:
        lid = str(ev["id"])
        if ev["event"] == "lesson":
            state[lid] = {
                "id": lid, "kind": ev["kind"], "statement": ev["statement"], "test": ev.get("test"),
                "status": ev.get("status", "hypothesis"), "created": ev.get("ts"),
                "supports": 0, "contradicts": 0, "neutral": 0, "last_evidence": None, "approved_by": None,
            }
        elif ev["event"] == "evidence":
            s = state[lid]
            s[ev["verdict"]] += 1
            d = ev.get("date") or ev.get("ts")
            if d and (s["last_evidence"] is None or str(d) > str(s["last_evidence"])):
                s["last_evidence"] = d
        else:
            state[lid]["status"] = ev["status"]
            if ev.get("approved_by"):
                state[lid]["approved_by"] = ev["approved_by"]
    for s in state.values():
        obs = s["supports"] + s["contradicts"]
        s["ready_to_propose"] = bool(
            s["kind"] not in SELF_ADOPT_KINDS and s["status"] == "hypothesis"
            and obs >= MIN_OBSERVATIONS and s["supports"] >= SUPPORT_RATIO * s["contradicts"])
        s["weak"] = bool(obs >= 4 and s["contradicts"] > s["supports"])
    return state


def lessons_view(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compact grouping for check-ins: what to apply now, what is being tested."""
    state = fold_lessons(events)

    def row(s: dict[str, Any]) -> dict[str, Any]:
        return {"id": s["id"], "kind": s["kind"], "statement": s["statement"],
                "tally": f"+{s['supports']} / -{s['contradicts']} / ~{s['neutral']}",
                "ready_to_propose": s["ready_to_propose"], "weak": s["weak"]}

    groups: dict[str, list[dict[str, Any]]] = {k: [] for k in ("active", "adopted", "hypothesis", "proposed")}
    for s in state.values():
        if s["status"] in groups:
            groups[s["status"]].append(row(s))
    return {
        "apply_now": groups["active"] + groups["adopted"],
        "being_tested": groups["hypothesis"],
        "awaiting_approval": groups["proposed"],
        "retired": sum(1 for s in state.values() if s["status"] == "retired"),
        "rules": {"min_observations": MIN_OBSERVATIONS, "support_ratio": SUPPORT_RATIO,
                  "note": "rule and risk lessons are adopted only with the owner's approval"},
    }


def _short(text: Any) -> str | None:
    if text is None:
        return None
    t = str(text)
    return t if len(t) <= NOTE_CHARS else t[: NOTE_CHARS - 3] + "..."


def _on(date: str, ts: Any) -> bool:
    return str(ts or "").startswith(date)


def day_pack(date: str, journal_events: list[dict[str, Any]], metric_records: list[dict[str, Any]],
             positions: dict[str, Any] | None, lesson_events: list[dict[str, Any]],
             max_loss_tolerance: float = 0.90) -> dict[str, Any]:
    """Everything the daily reflection needs, from files only (no market calls).

    ``date`` is the trading day as YYYY-MM-DD. Journal timestamps are UTC; the regular
    US session falls inside a single UTC date, so a prefix match is enough.
    """
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise EngineInputError("date must be YYYY-MM-DD")
    today = [e for e in journal_events if _on(date, e.get("ts"))]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for e in today:
        kind = jr.effective_event(e)
        by_kind.setdefault(kind, []).append({
            "ts": e.get("ts"), "symbol": e.get("symbol"), "structure": e.get("structure"),
            "price": e.get("price"), "quantity": e.get("quantity"), "pnl": e.get("pnl"),
            "edge_ratio": e.get("edge_ratio"), "implied_move": e.get("implied_move"),
            "realized_move": e.get("realized_move"), "tag": e.get("tag"), "notes": _short(e.get("notes")),
        })
    trades = jr.closed_trades(journal_events)
    closed_today = [t for t in trades if _on(date, t.get("exit_ts"))]
    adjust_pnl = sum(float(e["pnl"]) for e in today
                     if jr.effective_event(e) == "qty_adjust" and isinstance(e.get("pnl"), (int, float)))
    exit_pnl = sum(float(t["pnl"]) for t in closed_today if t.get("pnl") is not None)

    recs = [r for r in metric_records if _on(date, r.get("ts"))]

    def exec_stats(kind: str) -> dict[str, Any]:
        ex = [r.get("execution") or {} for r in recs if r.get("record") == kind and r.get("live", True)]
        vals = [x.get("fill_vs_mid") for x in ex if isinstance(x.get("fill_vs_mid"), (int, float))]
        reps = [x.get("reprices") for x in ex if isinstance(x.get("reprices"), (int, float))]
        return {"n": len(ex), "avg_fill_vs_mid": round(sum(vals) / len(vals), 4) if vals else None,
                "avg_reprices": round(sum(reps) / len(reps), 2) if reps else None}

    open_positions = []
    for o in (positions or {}).get("open", []) or []:
        open_positions.append({k: o.get(k) for k in (
            "symbol", "kind", "structure", "expiry", "quantity", "net_credit", "max_loss_usd",
            "breakevens", "entry_day_close", "edge_ratio")} | {"exit_plan": _short((o.get("plan") or {}).get("exit")
                                                               or (o.get("plan") or {}).get("exit_by"))})

    decisions = []
    for kind in ("entry_filled", "exit_filled", "qty_adjust", "entry_cancelled", "exit_cancelled", "halt"):
        for e in by_kind.get(kind, []):
            decisions.append({"decision": kind, "symbol": e["symbol"], "ts": e["ts"]})
    paper = [{"trade_id": r.get("trade_id"), "symbol": r.get("symbol"), "skip_reason": r.get("skip_reason"),
              "pnl_mid_usd": r.get("pnl_mid_usd"), "pnl_natural_usd": r.get("pnl_natural_usd")}
             for r in recs if r.get("record") == "paper" or r.get("live") is False]

    return {
        "date": date,
        "journal": by_kind,
        "closed_trades_today": closed_today,
        "realized_pnl_usd": {"exits": round(exit_pnl, 2), "adjusts": round(adjust_pnl, 2),
                             "total": round(exit_pnl + adjust_pnl, 2)},
        "execution": {"entries": exec_stats("entry"), "exits": exec_stats("exit")},
        "open_positions": open_positions,
        "risk": (positions or {}).get("risk"),
        "streaks": jr.streaks(trades, max_loss_tolerance),
        "paper_scored_today": paper,
        "decisions_to_grade": decisions,
        "lessons": lessons_view(lesson_events),
        "prompts": [
            "Grade each decision on what was known at the time, then record the outcome separately.",
            "For each lesson in apply_now and being_tested: did today support it, contradict it, or say nothing?",
            "What would have to be true for today's biggest win or loss to be luck?",
            "One change for tomorrow, at most. Rule and risk changes go to the owner as proposals.",
        ],
    }
