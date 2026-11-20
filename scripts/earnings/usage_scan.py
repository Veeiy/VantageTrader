#!/usr/bin/env python3
"""What the trading system cost to run on one day, read from Claude Code's own transcripts.

It adds up every model call of the head session and of its subagents at list prices per
token. On a subscription nothing is billed per token, so the dollar figure is a common unit
for comparing days and agents, not an invoice. A token count alone misleads: a token re-read
from the prompt cache costs 1/25 (Opus 5.5) to 1/80 (Fable 5.2, one-hour cache) of a token
written to it, so an agent that wakes after its cache has expired pays for its whole
conversation again.

    python3 scripts/earnings/usage_scan.py --date 2026-11-17 --append state/earnings/usage.jsonl

Prints one line for the daily reflection. With --append it also writes one JSON row a day
(a row for the same date is replaced). Stdlib only. It reads no account, order or repo file.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")

# List prices in dollars per million tokens (as cached 2026-11-03):
# input, output, cache read, cache write with a 5-minute life, cache write with a 1-hour life.
RATES = {
    "claude-fable-5-2": (8.0, 40.0, 0.20, 10.0, 16.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0, 8.0),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125, 0.20),  # cache prices approximate
}
COLD_MIN_TOKENS = 30_000  # below this a call is too small to matter


def read_calls(path: str) -> list[dict]:
    """One record per model call in a transcript file, oldest first."""
    best: dict[str, dict] = {}
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") != "assistant":
                continue
            msg = row.get("message") or {}
            use = msg.get("usage") or {}
            model = msg.get("model") or ""
            if not use or not model or model.startswith("<"):
                continue
            try:
                ts = datetime.fromisoformat(str(row.get("timestamp")).replace("Z", "+00:00"))
            except ValueError:
                continue
            split = use.get("cache_creation") or {}
            w1 = split.get("ephemeral_1h_input_tokens") or 0
            w5 = split.get("ephemeral_5m_input_tokens") or 0
            if not (w1 or w5):
                w5 = use.get("cache_creation_input_tokens") or 0
            call = {
                "ts": ts,
                "model": model,
                "in": use.get("input_tokens") or 0,
                "out": use.get("output_tokens") or 0,
                "read": use.get("cache_read_input_tokens") or 0,
                "w5": w5,
                "w1": w1,
                "side": bool(row.get("isSidechain")),
            }
            # A message is logged once per content block with the same id: keep one.
            key = msg.get("id") or row.get("uuid")
            old = best.get(key)
            if old is None:
                best[key] = call
            else:
                first = min(old["ts"], call["ts"])
                if call["out"] >= old["out"]:
                    best[key] = call
                best[key]["ts"] = first
    return sorted(best.values(), key=lambda c: c["ts"])


def conversation(call: dict) -> int:
    """Tokens the model was shown on this call."""
    return call["in"] + call["read"] + call["w5"] + call["w1"]


def cost(call: dict) -> float:
    r = RATES.get(call["model"])
    if r is None:
        return 0.0
    return (call["in"] * r[0] + call["out"] * r[1] + call["read"] * r[2]
            + call["w5"] * r[3] + call["w1"] * r[4]) / 1e6


def write_cost(call: dict) -> float:
    r = RATES.get(call["model"])
    if r is None:
        return 0.0
    return (call["w5"] * r[3] + call["w1"] * r[4]) / 1e6


def is_cold(call: dict) -> bool:
    """More than half of the conversation was written to the cache: nothing was there to read."""
    size = conversation(call)
    return size > COLD_MIN_TOKENS and (call["w5"] + call["w1"]) > 0.5 * size


def collect(projects: str) -> tuple[list[dict], list[list[dict]]]:
    """(the head's calls, one list of calls per subagent) from every transcript found."""
    head: list[dict] = []
    agents: list[list[dict]] = []
    for main in sorted(glob.glob(os.path.join(projects, "*", "*.jsonl"))):
        calls = read_calls(main)
        head += [c for c in calls if not c["side"]]
        side = [c for c in calls if c["side"]]
        if side:
            agents.append(side)
        for sub in sorted(glob.glob(os.path.join(main[: -len(".jsonl")], "subagents", "*.jsonl"))):
            calls = read_calls(sub)
            if calls:
                agents.append(calls)
    head.sort(key=lambda c: c["ts"])
    return head, agents


def summarize(head: list[dict], agents: list[list[dict]], day: str) -> dict:
    def on_day(call: dict) -> bool:
        return call["ts"].astimezone(PT).date().isoformat() == day

    h = [c for c in head if on_day(c)]
    h_cold = [c for c in h if is_cold(c)]
    by_model: dict[str, float] = {}
    unpriced: set[str] = set()

    def tally(calls: list[dict]) -> None:
        for c in calls:
            by_model[c["model"]] = by_model.get(c["model"], 0.0) + cost(c)
            if c["model"] not in RATES:
                unpriced.add(c["model"])

    tally(h)
    rows = []
    for calls in agents:
        mine = [(i, c) for i, c in enumerate(calls) if on_day(c)]
        if not mine:
            continue
        tally([c for _, c in mine])
        cold = [c for i, c in mine if i > 0 and is_cold(c)]  # the first call of an agent is its start
        rows.append({
            "start_pt": calls[0]["ts"].astimezone(PT).strftime("%m-%d %H:%M"),
            "model": calls[0]["model"],
            "calls": len(mine),
            "usd": round(sum(cost(c) for _, c in mine), 2),
            "conversation_first_k": conversation(mine[0][1]) // 1000,
            "conversation_last_k": conversation(mine[-1][1]) // 1000,
            "cold_wakes": len(cold),
            "cold_usd": round(sum(write_cost(c) for c in cold), 2),
        })
    rows.sort(key=lambda r: -r["usd"])
    head_usd = sum(cost(c) for c in h)
    sub_usd = sum(r["usd"] for r in rows)
    read_usd = sum(c["read"] * RATES[c["model"]][2] / 1e6 for c in h if c["model"] in RATES)
    out_usd = sum(c["out"] * RATES[c["model"]][1] / 1e6 for c in h if c["model"] in RATES)
    return {
        "date": day,
        "est_usd": round(head_usd + sub_usd, 2),
        "head": {
            "calls": len(h),
            "usd": round(head_usd, 2),
            "conversation_avg_k": round(sum(conversation(c) for c in h) / len(h) / 1000) if h else 0,
            "conversation_max_k": max((conversation(c) for c in h), default=0) // 1000,
            "cache_read_usd": round(read_usd, 2),
            "cache_write_usd": round(sum(write_cost(c) for c in h), 2),
            "output_usd": round(out_usd, 2),
            "cold_starts": len(h_cold),
            "cold_usd": round(sum(write_cost(c) for c in h_cold), 2),
        },
        "subagents": {
            "agents": len(rows),
            "calls": sum(r["calls"] for r in rows),
            "usd": round(sub_usd, 2),
            "cold_wakes": sum(r["cold_wakes"] for r in rows),
            "cold_usd": round(sum(r["cold_usd"] for r in rows), 2),
            "largest": rows[:3],
        },
        "by_model_usd": {m: round(v, 2) for m, v in sorted(by_model.items())},
        "unpriced_models": sorted(unpriced),
    }


def line(s: dict) -> str:
    h, a = s["head"], s["subagents"]
    text = (f"usage {s['date']}: about ${s['est_usd']:.0f} at list prices. Head ${h['usd']:.0f}: "
            f"{h['calls']} calls, average conversation {h['conversation_avg_k']}k tokens, "
            f"{h['cold_starts']} cold starts (${h['cold_usd']:.0f}). Subagents ${a['usd']:.0f} in "
            f"{a['agents']} agents: {a['cold_wakes']} cold wakes (${a['cold_usd']:.0f})")
    if a["largest"]:
        top = a["largest"][0]
        text += (f"; the largest started {top['start_pt'][6:]} ({top['calls']} calls, ${top['usd']:.0f}, "
                 f"conversation {top['conversation_first_k']}k to {top['conversation_last_k']}k)")
    return text + "."


def append_row(path: str, row: dict) -> None:
    kept = []
    if os.path.exists(path):
        with open(path) as fh:
            for raw in fh:
                raw = raw.strip()
                if raw and json.loads(raw).get("date") != row["date"]:
                    kept.append(raw)
    kept.append(json.dumps(row, sort_keys=True))
    with open(path, "w") as fh:
        fh.write("\n".join(kept) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="Pacific date, YYYY-MM-DD (default: today)")
    ap.add_argument("--projects", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--append", help="ledger file to write the day's row to")
    ap.add_argument("--json", action="store_true", help="print the row instead of the line")
    args = ap.parse_args()
    day = args.date or datetime.now(PT).date().isoformat()
    head, agents = collect(args.projects)
    s = summarize(head, agents, day)
    s["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.append:
        append_row(args.append, s)
    print(json.dumps(s, indent=1, sort_keys=True) if args.json else line(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
