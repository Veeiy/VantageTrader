"""Tests for the Post-Mortem Journalist and the journal infrastructure.

Mocks the Anthropic SDK end-to-end; no network calls.
"""
from __future__ import annotations

import json
import sys
import types
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from vantage_trader.agents.journalist import _extract_markdown
from vantage_trader.strategy.calendar import CalendarCandidate

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# _extract_markdown
# ---------------------------------------------------------------------------

def test_extract_markdown_plain():
    md = "# Daily Report -- 2026-06-16\n\nAll good."
    assert _extract_markdown(md, "2026-06-16") == md


def test_extract_markdown_strips_fence():
    raw = "```markdown\n# Daily Report -- 2026-06-16\n\nbody\n```"
    assert _extract_markdown(raw, "2026-06-16") == "# Daily Report -- 2026-06-16\n\nbody"


def test_extract_markdown_empty_falls_back():
    out = _extract_markdown("", "2026-06-16")
    assert "Daily Report" in out
    assert "2026-06-16" in out


# ---------------------------------------------------------------------------
# Fake Anthropic SDK
# ---------------------------------------------------------------------------

class _FakeStream:
    def __init__(self, events):
        self._events = events

    def __enter__(self):
        return iter(self._events)

    def __exit__(self, *_):
        return False


def _fake_event(etype: str, **kw):
    e = types.SimpleNamespace(type=etype)
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def _make_fake_anthropic_module(stream_events, agent_id="agt_test", env_id="env_test"):
    fake_mod = types.ModuleType("anthropic")

    class FakeAnthropic:
        instances = []

        def __init__(self, api_key=None):
            self.api_key = api_key
            self.sent_events = []
            FakeAnthropic.instances.append(self)

            self.beta = types.SimpleNamespace()
            self.beta.agents = MagicMock()
            self.beta.agents.create = MagicMock(
                return_value=types.SimpleNamespace(id=agent_id, version=1)
            )
            self.beta.environments = MagicMock()
            self.beta.environments.create = MagicMock(
                return_value=types.SimpleNamespace(id=env_id)
            )
            self.beta.sessions = MagicMock()
            self.beta.sessions.create = MagicMock(
                return_value=types.SimpleNamespace(id="sess_test")
            )
            self.beta.sessions.events = MagicMock()
            self.beta.sessions.events.stream = MagicMock(
                return_value=_FakeStream(stream_events)
            )

            def _send(session_id, *, events):
                self.sent_events.append((session_id, events))
            self.beta.sessions.events.send = MagicMock(side_effect=_send)

    fake_mod.Anthropic = FakeAnthropic
    return fake_mod


@pytest.fixture
def install_fake_anthropic(monkeypatch):
    def _install(stream_events):
        mod = _make_fake_anthropic_module(stream_events)
        monkeypatch.setitem(sys.modules, "anthropic", mod)
        return mod
    return _install


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------

async def test_generate_report_sends_payload_and_returns_markdown(install_fake_anthropic):
    mod = install_fake_anthropic([
        _fake_event("agent.message", content=[
            types.SimpleNamespace(type="text", text="# Daily Report -- 2026-06-16\n\nProfit $42 on 1 trade.\n")
        ]),
        _fake_event("session.status_idle"),
    ])

    from vantage_trader.agents.journalist import generate_report, register_journalist
    from vantage_trader.agents.runtime import AgentRuntime

    rt = AgentRuntime(api_key="sk-test")
    await register_journalist(rt, model="claude-opus-4-7")
    events = [{"ts": "2026-06-16T10:00:00-04:00", "kind": "open", "underlying": "SPY"}]
    report = await generate_report(rt, date="2026-06-16", events=events, still_open=[])
    assert report.date == "2026-06-16"
    assert "Daily Report -- 2026-06-16" in report.markdown
    # Verify the user message contained today's data
    client = mod.Anthropic.instances[-1]
    sent = client.sent_events
    assert len(sent) == 1
    user_text = sent[0][1][0]["content"][0]["text"]
    assert "2026-06-16" in user_text
    assert "SPY" in user_text


async def test_generate_report_unwraps_fenced_markdown(install_fake_anthropic):
    install_fake_anthropic([
        _fake_event("agent.message", content=[
            types.SimpleNamespace(type="text", text="```markdown\n# Daily Report -- 2026-06-16\n\nbody\n```")
        ]),
        _fake_event("session.status_idle"),
    ])

    from vantage_trader.agents.journalist import generate_report, register_journalist
    from vantage_trader.agents.runtime import AgentRuntime

    rt = AgentRuntime(api_key="sk-test")
    await register_journalist(rt, model="claude-opus-4-7")
    report = await generate_report(rt, date="2026-06-16", events=[], still_open=[])
    assert report.markdown == "# Daily Report -- 2026-06-16\n\nbody"


# ---------------------------------------------------------------------------
# Engine journal: append, read, date-filter
# ---------------------------------------------------------------------------

@dataclass
class _StubCreds:
    client_secret: str = ""
    refresh_token: str = ""
    account_number: str = "5WT00000"
    environment: str = "sandbox"


def _base_config(*, agents_enabled: bool = True, journalist_enabled: bool = True) -> dict[str, Any]:
    return {
        "underlyings": ["SPY"],
        "entry": {
            "short_dte_min": 0, "short_dte_max": 0,
            "long_dte_min": 30, "long_dte_max": 60,
            "short_delta_min": 0.40, "short_delta_max": 0.55,
            "direction": "auto",
            "max_debit_per_spread": 250,
            "min_open_interest_short": 500, "min_open_interest_long": 100,
            "max_bid_ask_spread_pct": 0.15,
            "iv_rank_max": 60,
            "skip_if_earnings_within_days": 2,
            "min_theta_per_dollar": 0.0005,
        },
        "management": {
            "profit_target_pct": 0.25, "stop_loss_pct": 0.50,
            "close_short_minutes_before_close": 15,
            "underlying_drift_strikes": 2, "close_long_at_dte": 14,
        },
        "risk": {
            "max_concurrent_spreads": 3, "max_total_debit": 1000,
            "max_spreads_per_underlying": 1,
        },
        "schedule": {
            "manage_every_seconds": 30,
            "entry_window_start": "10:00", "entry_window_end": "11:30",
        },
        "agents": {
            "enabled": agents_enabled,
            "reviewer": {"enabled": False},
            "journalist": {
                "enabled": journalist_enabled,
                "model": "claude-opus-4-7",
            },
        },
    }


def _make_candidate(**overrides) -> CalendarCandidate:
    defaults = dict(
        underlying="SPY", option_type="C", strike=520.0,
        long_expiration="2026-07-18", short_expiration="2026-06-16",
        long_mid=4.50, short_mid=2.20, debit=2.30,
        short_delta=0.48, short_theta=-0.42,
        long_iv=0.18, short_iv=0.22,
        short_open_interest=12000, long_open_interest=3400,
        bid_ask_spread_pct=0.04,
        theta_per_dollar=0.0018, score=0.0021,
        long_occ="SPY   260718C00520000", short_occ="SPY   260616C00520000",
        long_streamer=".SPY260718C520", short_streamer=".SPY260616C520",
        rationale="C K=520 short_delta=+0.48",
    )
    defaults.update(overrides)
    return CalendarCandidate(**defaults)


async def test_open_writes_journal_entry(install_fake_anthropic, monkeypatch, tmp_path):
    # Reviewer disabled; agents enabled only for journalist. No SDK call should happen here.
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))
    monkeypatch.chdir(tmp_path)

    from vantage_trader.engine import Engine, JOURNAL_FILE

    client = MagicMock()

    async def fake_get_equity_quote(symbol):
        return {"bid": "518.10", "ask": "518.30", "last": "518.20"}
    client.get_equity_quote = fake_get_equity_quote

    cfg = _base_config()
    # Disable agents so reviewer isn't consulted and SDK isn't instantiated.
    cfg["agents"]["enabled"] = False
    engine = Engine(client=client, creds=_StubCreds(), config=cfg, dry_run=True)

    async def fake_submit(order, label):
        pass
    engine._submit = fake_submit  # type: ignore[method-assign]

    await engine._open_spread(_make_candidate())

    entries = engine._read_journal(JOURNAL_FILE)
    assert len(entries) == 1
    e = entries[0]
    assert e["kind"] == "open"
    assert e["underlying"] == "SPY"
    assert e["strike"] == 520.0
    assert e["debit_paid"] == 230.0
    assert e["reviewer_verdict"] is None  # reviewer was disabled


async def test_open_records_reviewer_verdict(install_fake_anthropic, monkeypatch, tmp_path):
    install_fake_anthropic([
        _fake_event("agent.message", content=[
            types.SimpleNamespace(type="text", text='{"verdict": "SOFT_PASS", "reason": "theta marginal"}')
        ]),
        _fake_event("session.status_idle"),
    ])
    monkeypatch.chdir(tmp_path)

    from vantage_trader.engine import Engine, JOURNAL_FILE

    client = MagicMock()
    async def fake_get_equity_quote(symbol):
        return {"bid": "518.10", "ask": "518.30", "last": "518.20"}
    client.get_equity_quote = fake_get_equity_quote

    cfg = _base_config()
    cfg["agents"]["reviewer"] = {"enabled": True, "model": "claude-opus-4-7", "veto_enforced": False}
    engine = Engine(client=client, creds=_StubCreds(), config=cfg, dry_run=True)

    async def fake_submit(order, label):
        pass
    engine._submit = fake_submit  # type: ignore[method-assign]

    await engine._open_spread(_make_candidate())

    entries = engine._read_journal(JOURNAL_FILE)
    assert len(entries) == 1
    assert entries[0]["reviewer_verdict"] == "SOFT_PASS"
    assert entries[0]["reviewer_reason"] == "theta marginal"


def test_filter_by_date(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from vantage_trader.engine import Engine

    entries = [
        {"ts": "2026-06-16T10:00:00-04:00", "kind": "open"},
        {"ts": "2026-06-16T15:45:00-04:00", "kind": "close"},
        {"ts": "2026-06-15T10:00:00-04:00", "kind": "open"},
        {"ts": "bad-timestamp", "kind": "close"},  # silently dropped
    ]
    today = Engine._filter_by_date(entries, date(2026, 6, 16))
    assert len(today) == 2
    assert {e["kind"] for e in today} == {"open", "close"}


# ---------------------------------------------------------------------------
# generate_daily_report end-to-end (engine API)
# ---------------------------------------------------------------------------

async def test_generate_daily_report_writes_markdown_file(install_fake_anthropic, monkeypatch, tmp_path):
    install_fake_anthropic([
        _fake_event("agent.message", content=[
            types.SimpleNamespace(type="text", text="# Daily Report -- 2026-06-16\n\nP&L +$57.50 on 1 trade.\n")
        ]),
        _fake_event("session.status_idle"),
    ])
    monkeypatch.chdir(tmp_path)

    # Seed journal with a close from today (ET).
    from vantage_trader.engine import Engine, JOURNAL_FILE, REPORTS_DIR

    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(tz=ET).date().isoformat()
    JOURNAL_FILE.write_text(json.dumps({
        "ts": f"{today}T15:45:00-04:00",
        "kind": "close",
        "underlying": "SPY", "option_type": "C", "strike": 520.0,
        "debit_paid": 230.0, "close_value": 287.5,
        "pnl_dollars": 57.5, "pnl_pct": 0.25,
        "reason": "profit target hit",
        "opened_at": f"{today}T10:05:00-04:00",
    }) + "\n")

    client = MagicMock()
    engine = Engine(client=client, creds=_StubCreds(), config=_base_config(), dry_run=True)

    report = await engine.generate_daily_report()

    assert report.path_written is not None
    out = REPORTS_DIR / f"{today}.md"
    assert out.exists()
    assert "Daily Report" in out.read_text()
    assert "P&L +$57.50" in out.read_text()


async def test_generate_daily_report_filters_by_date(install_fake_anthropic, monkeypatch, tmp_path):
    """Journalist should receive only events from the target date."""
    mod = install_fake_anthropic([
        _fake_event("agent.message", content=[
            types.SimpleNamespace(type="text", text="# Daily Report -- 2026-06-15\n\nbody\n")
        ]),
        _fake_event("session.status_idle"),
    ])
    monkeypatch.chdir(tmp_path)

    from vantage_trader.engine import Engine, JOURNAL_FILE

    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL_FILE.write_text(
        json.dumps({"ts": "2026-06-15T10:00:00-04:00", "kind": "open", "underlying": "SPY"}) + "\n"
        + json.dumps({"ts": "2026-06-16T10:00:00-04:00", "kind": "open", "underlying": "QQQ"}) + "\n"
    )

    client = MagicMock()
    engine = Engine(client=client, creds=_StubCreds(), config=_base_config(), dry_run=True)
    await engine.generate_daily_report(target=date(2026, 6, 15))

    fake = mod.Anthropic.instances[-1]
    sent_user_text = fake.sent_events[0][1][0]["content"][0]["text"]
    assert "SPY" in sent_user_text
    assert "QQQ" not in sent_user_text


async def test_generate_daily_report_errors_when_journalist_disabled(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))

    from vantage_trader.engine import Engine

    cfg = _base_config(agents_enabled=True, journalist_enabled=False)
    client = MagicMock()
    engine = Engine(client=client, creds=_StubCreds(), config=cfg, dry_run=True)

    with pytest.raises(RuntimeError, match="journalist.enabled"):
        await engine.generate_daily_report()


async def test_generate_daily_report_errors_when_agents_disabled(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))

    from vantage_trader.engine import Engine

    cfg = _base_config(agents_enabled=False, journalist_enabled=True)
    client = MagicMock()
    engine = Engine(client=client, creds=_StubCreds(), config=cfg, dry_run=True)

    with pytest.raises(RuntimeError, match="agents.enabled"):
        await engine.generate_daily_report()
