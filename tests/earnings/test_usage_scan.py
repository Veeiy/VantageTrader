"""scripts/earnings/usage_scan.py: a wake after the cache has expired is counted as cold."""
import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "earnings" / "usage_scan.py"


def _load():
    spec = importlib.util.spec_from_file_location("usage_scan", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(mid, ts, model, read=0, w5=0, w1=0, out=100):
    usage = {"input_tokens": 10, "output_tokens": out, "cache_read_input_tokens": read,
             "cache_creation_input_tokens": w5 + w1,
             "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}}
    return json.dumps({"type": "assistant", "timestamp": ts,
                       "message": {"id": mid, "model": model, "usage": usage}})


def _transcripts(tmp_path):
    proj = tmp_path / "proj"
    subs = proj / "abc" / "subagents"
    subs.mkdir(parents=True)
    (proj / "abc.jsonl").write_text("\n".join([
        _row("h1", "2026-11-17T15:00:00Z", "claude-fable-5-2", w1=200_000),         # cold start
        _row("h2", "2026-11-17T15:01:00Z", "claude-fable-5-2", read=200_000, w1=1_000),
        _row("h2", "2026-11-17T15:01:02Z", "claude-fable-5-2", read=200_000, w1=1_000),  # same message, second block
        _row("h3", "2026-11-18T15:00:00Z", "claude-fable-5-2", read=200_000),       # another day
    ]) + "\n")
    (subs / "agent-x.jsonl").write_text("\n".join([
        _row("s1", "2026-11-17T15:00:00Z", "claude-opus-5-5", w5=80_000),           # the agent's start
        _row("s2", "2026-11-17T15:04:00Z", "claude-opus-5-5", read=80_000, w5=2_000),   # inside the cache
        _row("s3", "2026-11-17T15:12:00Z", "claude-opus-5-5", w5=85_000),           # 8 minutes later: cold
    ]) + "\n")
    return proj.parent


def test_a_wake_after_the_cache_expired_is_cold_and_priced_as_a_write(tmp_path):
    mod = _load()
    head, agents = mod.collect(str(_transcripts(tmp_path)))
    s = mod.summarize(head, agents, "2026-11-17")
    assert s["head"]["calls"] == 2                      # the repeated block is one call
    assert s["head"]["cold_starts"] == 1
    assert s["head"]["cold_usd"] == 3.2                 # 200k tokens at $16 a million
    sub = s["subagents"]
    assert (sub["agents"], sub["calls"], sub["cold_wakes"]) == (1, 3, 1)
    assert sub["cold_usd"] == 0.42                      # 85k tokens at $5 a million; the start is not a wake
    assert "1 cold wakes" in mod.line(s)


def test_the_ledger_keeps_one_row_a_day(tmp_path):
    mod = _load()
    ledger = tmp_path / "usage.jsonl"
    mod.append_row(str(ledger), {"date": "2026-11-17", "est_usd": 1.0})
    mod.append_row(str(ledger), {"date": "2026-11-18", "est_usd": 2.0})
    mod.append_row(str(ledger), {"date": "2026-11-17", "est_usd": 3.0})
    rows = [json.loads(x) for x in ledger.read_text().splitlines()]
    assert [(r["date"], r["est_usd"]) for r in rows] == [("2026-11-18", 2.0), ("2026-11-17", 3.0)]
