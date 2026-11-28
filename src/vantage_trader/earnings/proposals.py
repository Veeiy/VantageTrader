"""Improvement proposals ledger (``state/earnings/proposals.jsonl``), append-only.

Brad, 2026-11-10: "Propose changes and iterations daily for us to heal and strengthen
the trading loop." Each daily reflection adds proposals here; this module only reads
and validates them.

Events:
  {"event": "proposal", "id", "date", "type": "heal|strengthen", "kind", "title",
   "problem", "change", "measure", "decider": "agent|owner", "ts"}
  {"event": "decision", "id", "decision": "approved|declined|deferred", "by", "note", "ts"}
  {"event": "implemented", "id", "ref", "note", "ts"}
  {"event": "verified", "id", "result": "worked|did_not_work|inconclusive", "note", "ts"}

Guardrails enforced on read:
  * kinds ``rule``, ``risk`` and ``cost`` are the owner's call: ``decider`` must be
    ``owner`` and an approval must name the person who gave it, or be an agent's decision
    that cites a standing delegation reaching that proposal (see ``DELEGATIONS``);
  * a proposal flagged ``hard_limit`` (the account, never TSLA, defined risk, limit orders,
    the total risk cap, money in or out) is approved by the owner's words only;
  * nothing is ``implemented`` before it is approved, and nothing is ``verified`` before
    it is implemented.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import EngineInputError

EVENTS = {"proposal", "decision", "implemented", "verified"}
TYPES = {"heal", "strengthen"}
KINDS = {"execution", "process", "data", "tooling", "rule", "risk", "cost"}
OWNER_KINDS = {"rule", "risk", "cost"}
DECISIONS = {"approved", "declined", "deferred"}
RESULTS = {"worked", "did_not_work", "inconclusive"}


def _is_agent(by: Any) -> bool:
    return str(by or "").strip().lower().startswith("agent")


# Standing delegations from the owner (docs/earnings/RULES_CHANGELOG.md, "Delegation").
# An agent may approve an owner-kind proposal only when its "by" cites one of these by its
# marker and the decision is dated on or after it.
#   * The delegation of 2026-11-11 covers rule, risk and cost iterations. It does not cover a
#     proposal flagged ``needs_owner`` (a max loss per name above the stated numbers, a new live
#     strategy line).
#   * The delegation of 2026-11-16 ("Dont need a decision on me. Remember, self healing and
#     strengthening the model with your own decision making") covers ``needs_owner`` proposals
#     too: the agent decides them and tells the owner after.
#   * Nothing covers a proposal flagged ``hard_limit``: the account, never TSLA, defined risk
#     only, limit orders only, the total risk cap, money in or out. Those need the owner's words.
# Sizing above 1 contract left the owner-only list on 2026-11-11 (RULES_CHANGELOG v1.7).
DELEGATIONS: tuple[dict[str, Any], ...] = (
    {"since": "2026-11-11T16:13:00Z", "marker": "delegation of 2026-11-11", "covers_needs_owner": False,
     "quote": "for these iterations like p018 and p019, youre good to push. but i want you to push these "
              "reccommendations and changes if you see fit. you have owners permission to automate."},
    {"since": "2026-11-17T02:14:00Z", "marker": "delegation of 2026-11-16", "covers_needs_owner": True,
     "quote": "Dont need a decision on me. Remember, self healing and strengthening the model with your "
              "own decision making"},
)


def under_delegation(by: Any, ts: Any, needs_owner: bool = False) -> bool:
    """True when an agent's decision cites a standing delegation that was in force at ``ts`` and
    that reaches this proposal (a ``needs_owner`` proposal needs the delegation of 2026-11-16)."""
    text, when = str(by or "").lower(), str(ts or "")
    return any(d["marker"] in text and when >= d["since"] and (d["covers_needs_owner"] or not needs_owner)
               for d in DELEGATIONS)


def read_proposals(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    meta: dict[str, dict[str, Any]] = {}
    for n, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError as e:
            raise EngineInputError(f"proposals line {n} is not valid JSON: {e}")
        if not isinstance(ev, dict) or ev.get("event") not in EVENTS or not ev.get("id"):
            raise EngineInputError(f"proposals line {n}: missing id or unknown event")
        pid, kind_of = str(ev["id"]), ev["event"]
        if kind_of == "proposal":
            if pid in meta:
                raise EngineInputError(f"proposals line {n}: duplicate proposal id {pid}")
            if ev.get("type") not in TYPES or ev.get("kind") not in KINDS:
                raise EngineInputError(f"proposals line {n}: unknown type or kind")
            if not str(ev.get("title") or "").strip() or not str(ev.get("change") or "").strip():
                raise EngineInputError(f"proposals line {n}: a proposal needs a title and a change")
            if ev.get("decider") not in ("agent", "owner"):
                raise EngineInputError(f"proposals line {n}: decider must be agent or owner")
            if ev["kind"] in OWNER_KINDS and ev["decider"] != "owner":
                raise EngineInputError(f"proposals line {n}: a {ev['kind']} proposal is the owner's decision")
            meta[pid] = {"decider": ev["decider"], "approved": False, "implemented": False,
                         "needs_owner": bool(ev.get("needs_owner")), "hard_limit": bool(ev.get("hard_limit"))}
        else:
            if pid not in meta:
                raise EngineInputError(f"proposals line {n}: {kind_of} for unknown proposal {pid}")
            m = meta[pid]
            if kind_of == "decision":
                if ev.get("decision") not in DECISIONS or not str(ev.get("by") or "").strip():
                    raise EngineInputError(f"proposals line {n}: a decision needs a known value and 'by'")
                if ev["decision"] == "approved" and _is_agent(ev["by"]) and (m["decider"] == "owner" or m["hard_limit"]):
                    if m["hard_limit"] or not under_delegation(ev["by"], ev.get("ts"), m["needs_owner"]):
                        raise EngineInputError(f"proposals line {n}: {pid} can only be approved by the owner")
                m["approved"] = ev["decision"] == "approved"
            elif kind_of == "implemented":
                if not m["approved"]:
                    raise EngineInputError(f"proposals line {n}: {pid} is implemented before it is approved")
                m["implemented"] = True
            else:
                if ev.get("result") not in RESULTS:
                    raise EngineInputError(f"proposals line {n}: unknown result")
                if not m["implemented"]:
                    raise EngineInputError(f"proposals line {n}: {pid} is verified before it is implemented")
        out.append(ev)
    return out


def fold_proposals(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for ev in events:
        pid = str(ev["id"])
        if ev["event"] == "proposal":
            state[pid] = {k: ev.get(k) for k in ("id", "date", "type", "kind", "title", "problem", "change",
                                                 "measure", "decider")}
            state[pid].update(status="open", decided_by=None, ref=None, result=None)
        elif ev["event"] == "decision":
            state[pid]["status"] = {"approved": "approved", "declined": "declined", "deferred": "open"}[ev["decision"]]
            state[pid]["decided_by"] = ev.get("by")
        elif ev["event"] == "implemented":
            state[pid]["status"], state[pid]["ref"] = "implemented", ev.get("ref")
        else:
            state[pid]["status"], state[pid]["result"] = "verified", ev["result"]
    return state


def proposals_view(events: list[dict[str, Any]]) -> dict[str, Any]:
    state = fold_proposals(events)

    def row(s: dict[str, Any]) -> dict[str, Any]:
        return {k: s[k] for k in ("id", "date", "type", "kind", "title", "change", "measure")}

    vals = list(state.values())
    return {
        "awaiting_owner": [row(s) for s in vals if s["status"] == "open" and s["decider"] == "owner"],
        "awaiting_agent": [row(s) for s in vals if s["status"] == "open" and s["decider"] == "agent"],
        "approved_not_implemented": [row(s) for s in vals if s["status"] == "approved"],
        "implemented_not_verified": [row(s) | {"ref": s["ref"]} for s in vals if s["status"] == "implemented"],
        "closed": {
            "declined": sum(1 for s in vals if s["status"] == "declined"),
            "worked": sum(1 for s in vals if s["result"] == "worked"),
            "did_not_work": sum(1 for s in vals if s["result"] == "did_not_work"),
            "inconclusive": sum(1 for s in vals if s["result"] == "inconclusive"),
        },
    }
