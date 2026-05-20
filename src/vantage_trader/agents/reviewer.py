"""Trade Reviewer: second-opinion on calendar spread candidates.

The deterministic scanner already filters on delta band, theta/$, debit,
liquidity, IV rank, and earnings proximity. The reviewer's job is the soft
layer those rules can't easily express -- "does this candidate make sense
as a whole given long-vs-short IV, debit-vs-theta, drift room to expiry?"

Contract:
  Input:  one JSON-serialised CalendarCandidate snapshot (see
          `candidate_to_payload`).
  Output: a single JSON object {"verdict": "PASS"|"SOFT_PASS"|"VETO",
          "reason": "<one short sentence>"}.

The reviewer is advisory by default; `agents.reviewer.veto_enforced: true`
in config makes a VETO actually skip the entry.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from ..strategy.calendar import CalendarCandidate
from .runtime import AgentRuntime, AgentSpec

log = logging.getLogger(__name__)

REVIEWER_KEY = "reviewer"

REVIEWER_SYSTEM = """You are a derivatives risk analyst reviewing 0DTE calendar spread candidates for a trading bot.

The bot's strategy is a horizontal calendar at (or near) ATM:
  LONG  1x option   strike K   30-60 DTE   (collateral, long vega, slow theta)
  SHORT 1x option   strike K    0 DTE      (theta engine, fastest decay)
Both legs are the same option_type and strike.

The position is long vega and short gamma. It wins if spot pins near K
through the 0DTE close and the long leg's IV holds up. It loses fast if
(a) spot drifts past K, (b) the long's IV collapses, or (c) the debit
was too rich relative to expected daily theta.

You receive a JSON object with these fields (some may be null):
  underlying, option_type ("C" or "P"), strike, spot,
  short_expiration, long_expiration,
  short_delta, short_theta, long_iv, short_iv,
  debit (per-contract, dollars per share), debit_dollars (debit * 100),
  score, theta_per_dollar, bid_ask_spread_pct,
  short_open_interest, long_open_interest, rationale.

The candidate has ALREADY passed the rule-based filters: delta band,
debit cap, OI floors, max bid-ask spread, IV rank cap, earnings window,
min theta/$. You are the second pair of eyes catching what those miss.

Verdict guide:
  PASS       - structurally sound; no concerns beyond what the filters already covered.
  SOFT_PASS  - enter, but a real concern is worth flagging (e.g. theta/$ marginal,
               IV term structure flat or inverted, debit on the high end).
  VETO       - reserve for clear structural problems the bot shouldn't take:
               long_iv well below short_iv (IV term inversion -> long leg cheap for a reason);
               debit_dollars implausibly close to max_debit ceiling vs. weak theta;
               option_type direction inconsistent with spot vs strike (short ITM at entry);
               or other plain red flags.

Respond with a SINGLE JSON object and NOTHING else. No prose, no code fence,
no preamble. Schema:
  {"verdict": "PASS" | "SOFT_PASS" | "VETO", "reason": "<one short sentence>"}
"""


@dataclass
class ReviewResult:
    verdict: Literal["PASS", "SOFT_PASS", "VETO"]
    reason: str
    raw: str

    @property
    def allow(self) -> bool:
        return self.verdict != "VETO"


def build_reviewer_spec(model: str) -> AgentSpec:
    return AgentSpec(
        key=REVIEWER_KEY,
        name="VantageTrader Trade Reviewer",
        model=model,
        system=REVIEWER_SYSTEM,
        tools=[],
    )


async def register_reviewer(
    runtime: AgentRuntime,
    *,
    model: str = "claude-opus-4-7",
    agent_id: str | None = None,
) -> str:
    return await runtime.register(build_reviewer_spec(model), agent_id=agent_id)


def candidate_to_payload(cand: CalendarCandidate, *, spot: float | None = None) -> dict[str, Any]:
    """Snapshot of the candidate that gets sent to the reviewer.

    Spot isn't on CalendarCandidate today, so the caller passes it explicitly.
    """
    return {
        "underlying": cand.underlying,
        "option_type": cand.option_type,
        "strike": cand.strike,
        "spot": spot,
        "short_expiration": cand.short_expiration,
        "long_expiration": cand.long_expiration,
        "short_delta": cand.short_delta,
        "short_theta": cand.short_theta,
        "long_iv": cand.long_iv,
        "short_iv": cand.short_iv,
        "debit": cand.debit,
        "debit_dollars": round(cand.debit * 100, 2),
        "score": cand.score,
        "theta_per_dollar": cand.theta_per_dollar,
        "bid_ask_spread_pct": cand.bid_ask_spread_pct,
        "short_open_interest": cand.short_open_interest,
        "long_open_interest": cand.long_open_interest,
        "rationale": cand.rationale,
    }


async def review(runtime: AgentRuntime, payload: dict[str, Any]) -> ReviewResult:
    body = json.dumps(payload, default=str, indent=2)
    text = await runtime.run(
        key=REVIEWER_KEY,
        user_message=f"Review this candidate:\n\n{body}",
        title=f"review {payload.get('underlying')} K={payload.get('strike')}",
    )
    return parse_review(text)


_CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)
_VALID = {"PASS", "SOFT_PASS", "VETO"}


def parse_review(text: str) -> ReviewResult:
    """Parse the reviewer's response. On any failure, default to SOFT_PASS
    so a bad reply never silently approves OR silently blocks trades --
    it gets flagged and logged.
    """
    raw = text
    stripped = _CODE_FENCE.sub("", text).strip()
    # Some models still wrap with stray prose; grab the first {...} block.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        stripped = stripped[start : end + 1]
    try:
        obj = json.loads(stripped)
        verdict = str(obj["verdict"]).upper().strip()
        if verdict not in _VALID:
            raise ValueError(f"unknown verdict {verdict!r}")
        reason = str(obj.get("reason", "")).strip() or "(no reason given)"
        return ReviewResult(verdict=verdict, reason=reason, raw=raw)  # type: ignore[arg-type]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
        log.warning("reviewer parse failed (%s); defaulting SOFT_PASS. raw=%r", e, raw[:300])
        return ReviewResult(verdict="SOFT_PASS", reason=f"reviewer-parse-error: {e}", raw=raw)
