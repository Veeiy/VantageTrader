"""Agent team: Managed Agents API wrappers that advise the trading engine.

Each agent is a `model + system + (optional tools)` config consulted by the
engine at a specific hook (e.g. the Trade Reviewer runs on each candidate
before order submission). The engine still owns every decision; agent
output is logged alongside the rule-based output and can optionally
veto an entry.
"""
from .reviewer import (
    REVIEWER_KEY,
    ReviewResult,
    candidate_to_payload,
    register_reviewer,
    review,
)
from .runtime import AgentRuntime, AgentSpec

__all__ = [
    "AgentRuntime",
    "AgentSpec",
    "REVIEWER_KEY",
    "ReviewResult",
    "candidate_to_payload",
    "register_reviewer",
    "review",
]
