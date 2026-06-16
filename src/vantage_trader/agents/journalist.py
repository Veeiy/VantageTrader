"""Post-Mortem Journalist: end-of-day report on the bot's trading activity.

The engine appends one JSON line per open/close to `state/journal.jsonl`.
At end-of-day (manually via `python -m vantage_trader daily-report`, or
hooked into the engine loop), the journalist:

  1. Receives today's journal events + currently-open spreads as JSON
  2. Optionally runs sandbox tools (bash, python) to compute stats
  3. Returns a markdown daily-report as its final text

The engine writes that markdown to `reports/YYYY-MM-DD.md`. We never have
to download files out of the Anthropic sandbox -- the report comes back
in the response stream.

Unlike the reviewer, this agent gets the full `agent_toolset_20260401` so
it can grind numbers in the sandbox if it wants to. It still has no live
access to our state files (just what we hand it in the prompt).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .runtime import AgentRuntime, AgentSpec

log = logging.getLogger(__name__)

JOURNALIST_KEY = "journalist"

JOURNALIST_SYSTEM = """You are a trading-journal analyst for an automated 0DTE calendar spread bot.

Strategy recap:
  LONG  1x option   strike K   30-60 DTE   (collateral, long vega)
  SHORT 1x option   strike K    0 DTE      (theta engine)
Wins if spot pins near K through 0DTE close; loses on drift or IV crush.

You receive a JSON object with the trading day's data:
  {
    "date": "YYYY-MM-DD",
    "events": [ ... append-only journal entries: kind="open" or "close" ... ],
    "still_open": [ ... spreads opened today (or earlier) still open at EOD ... ]
  }

Each "open" event includes the Trade Reviewer's verdict (if the reviewer
was enabled). Each "close" event includes pnl_dollars, pnl_pct, and the
deterministic close reason. The journalist's job is to TELL THE OPERATOR
WHAT HAPPENED TODAY in a form they can scan in 60 seconds.

You have sandbox tools (bash, python, file ops). Use them if you want to
compute stats, but the FINAL output must be a complete markdown report in
your last text message. We extract that markdown verbatim and save it to
disk -- nothing else makes it out of the sandbox.

Required report structure:

# Daily Report -- <date>

## Headline
- One line P&L summary: total realised P&L $, win/loss count, biggest winner / loser.
- One line on still-open positions (count + total debit at risk overnight).

## Trades
A table or per-trade bullets covering each closed trade. For each:
underlying / option_type / strike / debit_paid / close_value / pnl_$ / pnl_% / close_reason / reviewer_verdict (if any).

## Reviewer scorecard (omit section if reviewer was disabled)
For each open whose reviewer_verdict is set, did the reviewer call it right?
- VETO that the bot still took (advisory mode): did it lose? -> reviewer was correct.
- SOFT_PASS with concern: did the concern materialise?
- PASS: routine, no scoring needed.

## Patterns and anomalies
2-5 bullets. Concrete: "all 3 losses happened when spot drifted >2 strikes
within 30 min of open", "theta/$ scores above 0.002 outperformed the rest
3-1 today". If only one trade today, just say so.

## Tomorrow
2-3 specific suggestions tied to today's data. Skip vague advice.

Tone: dry, analytical, concrete. No hedging language. No emojis."""


@dataclass
class DailyReport:
    date: str
    markdown: str
    path_written: str | None = None


def build_journalist_spec(model: str) -> AgentSpec:
    return AgentSpec(
        key=JOURNALIST_KEY,
        name="VantageTrader Post-Mortem Journalist",
        model=model,
        system=JOURNALIST_SYSTEM,
        # Full toolset: bash, file ops, web search, etc. The journalist may use
        # python to compute stats; final report still comes back as response text.
        tools=[{"type": "agent_toolset_20260401"}],
    )


async def register_journalist(
    runtime: AgentRuntime,
    *,
    model: str = "claude-opus-4-7",
    agent_id: str | None = None,
) -> str:
    return await runtime.register(build_journalist_spec(model), agent_id=agent_id)


async def generate_report(
    runtime: AgentRuntime,
    *,
    date: str,
    events: list[dict[str, Any]],
    still_open: list[dict[str, Any]],
) -> DailyReport:
    payload = {"date": date, "events": events, "still_open": still_open}
    body = json.dumps(payload, default=str, indent=2)
    text = await runtime.run(
        key=JOURNALIST_KEY,
        user_message=(
            f"Today's data:\n\n{body}\n\n"
            "Write the daily report. Return the markdown as your final text "
            "message; we extract it verbatim."
        ),
        title=f"daily-report {date}",
    )
    markdown = _extract_markdown(text, date)
    return DailyReport(date=date, markdown=markdown)


def _extract_markdown(text: str, date: str) -> str:
    """If the agent wrapped its response in a ```markdown fence, unwrap it.
    Otherwise return the text as-is, stripped.
    """
    s = text.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1 and s.endswith("```"):
            s = s[first_nl + 1 : -3].strip()
    if not s:
        log.warning("journalist returned empty markdown for %s", date)
        return f"# Daily Report -- {date}\n\n_(journalist returned no content)_\n"
    return s
