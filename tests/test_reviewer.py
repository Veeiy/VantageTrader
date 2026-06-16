"""Tests for the Trade Reviewer parser, payload shape, and engine integration.

The Anthropic SDK is mocked end-to-end so these tests run offline and never
hit the real API.
"""
from __future__ import annotations

import json
import sys
import types
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from vantage_trader.agents.reviewer import (
    ReviewResult,
    candidate_to_payload,
    parse_review,
)
from vantage_trader.strategy.calendar import CalendarCandidate


# ---------------------------------------------------------------------------
# parse_review
# ---------------------------------------------------------------------------

def test_parse_review_clean_json():
    r = parse_review('{"verdict": "PASS", "reason": "looks fine"}')
    assert r.verdict == "PASS"
    assert r.reason == "looks fine"
    assert r.allow


def test_parse_review_soft_pass():
    r = parse_review('{"verdict":"SOFT_PASS","reason":"theta/$ marginal"}')
    assert r.verdict == "SOFT_PASS"
    assert r.allow


def test_parse_review_veto():
    r = parse_review('{"verdict":"VETO","reason":"IV term inverted hard"}')
    assert r.verdict == "VETO"
    assert not r.allow


def test_parse_review_strips_code_fence():
    text = '```json\n{"verdict": "PASS", "reason": "ok"}\n```'
    assert parse_review(text).verdict == "PASS"


def test_parse_review_extracts_from_prose():
    text = 'Sure! Here is my review:\n{"verdict": "VETO", "reason": "earnings inside long"}\nThanks!'
    assert parse_review(text).verdict == "VETO"


def test_parse_review_invalid_verdict_defaults_soft_pass():
    r = parse_review('{"verdict": "MAYBE", "reason": "idk"}')
    assert r.verdict == "SOFT_PASS"
    assert "reviewer-parse-error" in r.reason
    assert r.allow  # soft_pass allows entry


def test_parse_review_bad_json_defaults_soft_pass():
    r = parse_review("totally not json")
    assert r.verdict == "SOFT_PASS"
    assert "reviewer-parse-error" in r.reason


def test_parse_review_missing_verdict_defaults_soft_pass():
    r = parse_review('{"reason": "no verdict here"}')
    assert r.verdict == "SOFT_PASS"


def test_parse_review_lowercase_verdict_accepted():
    r = parse_review('{"verdict": "pass", "reason": "fine"}')
    assert r.verdict == "PASS"


# ---------------------------------------------------------------------------
# candidate_to_payload
# ---------------------------------------------------------------------------

def _make_candidate(**overrides) -> CalendarCandidate:
    defaults = dict(
        underlying="SPY",
        option_type="C",
        strike=520.0,
        long_expiration="2026-06-19",
        short_expiration="2026-05-20",
        long_mid=4.50,
        short_mid=2.20,
        debit=2.30,
        short_delta=0.48,
        short_theta=-0.42,
        long_iv=0.18,
        short_iv=0.22,
        short_open_interest=12000,
        long_open_interest=3400,
        bid_ask_spread_pct=0.04,
        theta_per_dollar=0.0018,
        score=0.0021,
        long_occ="SPY   260619C00520000",
        short_occ="SPY   260520C00520000",
        long_streamer=".SPY260619C520",
        short_streamer=".SPY260520C520",
        rationale="C K=520 short_delta=+0.48 theta/$=0.0018 debit=$230 liq=0.73",
    )
    defaults.update(overrides)
    return CalendarCandidate(**defaults)


def test_candidate_to_payload_includes_all_required_fields():
    cand = _make_candidate()
    payload = candidate_to_payload(cand, spot=518.20)
    expected_keys = {
        "underlying", "option_type", "strike", "spot",
        "short_expiration", "long_expiration",
        "short_delta", "short_theta", "long_iv", "short_iv",
        "debit", "debit_dollars", "score", "theta_per_dollar",
        "bid_ask_spread_pct", "short_open_interest", "long_open_interest",
        "rationale",
    }
    assert expected_keys.issubset(payload.keys())
    assert payload["debit_dollars"] == 230.0
    assert payload["spot"] == 518.20
    # Round-trip JSON-serialisable (default=str handles non-primitives).
    json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# AgentRuntime with a mocked SDK
# ---------------------------------------------------------------------------

class _FakeStream:
    """Mimics the SDK's session.events.stream context manager + iterator."""
    def __init__(self, events: list[Any]):
        self._events = events

    def __enter__(self):
        return iter(self._events)

    def __exit__(self, *_):
        return False


def _fake_event(etype: str, **kw) -> Any:
    e = types.SimpleNamespace(type=etype)
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def _make_fake_anthropic_module(stream_events: list[Any], agent_id: str = "agt_test", env_id: str = "env_test") -> Any:
    """Build a fake `anthropic` module exposing the minimal Managed Agents surface."""
    fake_mod = types.ModuleType("anthropic")

    class FakeAnthropic:
        instances: list["FakeAnthropic"] = []

        def __init__(self, api_key: str | None = None):
            self.api_key = api_key
            self.sent_events: list[Any] = []
            FakeAnthropic.instances.append(self)

            # beta.agents.create
            self.beta = types.SimpleNamespace()
            self.beta.agents = MagicMock()
            self.beta.agents.create = MagicMock(
                return_value=types.SimpleNamespace(id=agent_id, version=1)
            )

            # beta.environments.create
            self.beta.environments = MagicMock()
            self.beta.environments.create = MagicMock(
                return_value=types.SimpleNamespace(id=env_id)
            )

            # beta.sessions.create
            self.beta.sessions = MagicMock()
            self.beta.sessions.create = MagicMock(
                return_value=types.SimpleNamespace(id="sess_test")
            )

            # beta.sessions.events.stream / send
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
    """Returns a function that installs a fake anthropic module with given stream events."""
    installed: list[Any] = []

    def _install(stream_events: list[Any]) -> Any:
        mod = _make_fake_anthropic_module(stream_events)
        monkeypatch.setitem(sys.modules, "anthropic", mod)
        installed.append(mod)
        return mod

    return _install


async def test_runtime_run_concatenates_agent_text_until_idle(install_fake_anthropic):
    events = [
        _fake_event("agent.message", content=[types.SimpleNamespace(type="text", text='{"verdict": "PASS",')]),
        _fake_event("agent.tool_use", name="ignored"),
        _fake_event("agent.message", content=[types.SimpleNamespace(type="text", text=' "reason": "ok"}')]),
        _fake_event("session.status_idle"),
        # Anything after idle must NOT be consumed.
        _fake_event("agent.message", content=[types.SimpleNamespace(type="text", text="LEAK")]),
    ]
    install_fake_anthropic(events)

    from vantage_trader.agents.runtime import AgentRuntime, AgentSpec

    rt = AgentRuntime(api_key="sk-test")
    await rt.register(AgentSpec(key="reviewer", name="r", model="claude-opus-4-7", system="s"))
    text = await rt.run(key="reviewer", user_message="hi", title="t")
    assert text == '{"verdict": "PASS", "reason": "ok"}'
    assert "LEAK" not in text


async def test_runtime_register_idempotent(install_fake_anthropic):
    mod = install_fake_anthropic([_fake_event("session.status_idle")])

    from vantage_trader.agents.runtime import AgentRuntime, AgentSpec

    rt = AgentRuntime(api_key="sk-test")
    spec = AgentSpec(key="reviewer", name="r", model="claude-opus-4-7", system="s")
    id1 = await rt.register(spec)
    id2 = await rt.register(spec)
    assert id1 == id2
    fake_client = mod.Anthropic.instances[-1]
    assert fake_client.beta.agents.create.call_count == 1


async def test_runtime_register_with_existing_agent_id_skips_create(install_fake_anthropic):
    mod = install_fake_anthropic([])

    from vantage_trader.agents.runtime import AgentRuntime, AgentSpec

    rt = AgentRuntime(api_key="sk-test")
    spec = AgentSpec(key="reviewer", name="r", model="claude-opus-4-7", system="s")
    assert await rt.register(spec, agent_id="agt_existing") == "agt_existing"
    # Lazy SDK init: reusing an agent id doesn't require touching the SDK at all.
    assert mod.Anthropic.instances == []


async def test_runtime_environment_reused(install_fake_anthropic):
    mod = install_fake_anthropic([_fake_event("session.status_idle")])

    from vantage_trader.agents.runtime import AgentRuntime, AgentSpec

    rt = AgentRuntime(api_key="sk-test")
    await rt.register(AgentSpec(key="reviewer", name="r", model="m", system="s"))
    await rt.run(key="reviewer", user_message="a", title="t1")
    await rt.run(key="reviewer", user_message="b", title="t2")
    fake_client = mod.Anthropic.instances[-1]
    # Environment created once even across multiple runs.
    assert fake_client.beta.environments.create.call_count == 1
    # But sessions are created per-run.
    assert fake_client.beta.sessions.create.call_count == 2


async def test_review_end_to_end_returns_parsed_verdict(install_fake_anthropic):
    install_fake_anthropic([
        _fake_event("agent.message", content=[
            types.SimpleNamespace(type="text", text='{"verdict": "VETO", "reason": "IV inverted"}')
        ]),
        _fake_event("session.status_idle"),
    ])

    from vantage_trader.agents.reviewer import register_reviewer, review
    from vantage_trader.agents.runtime import AgentRuntime

    rt = AgentRuntime(api_key="sk-test")
    await register_reviewer(rt, model="claude-opus-4-7")
    result = await review(rt, candidate_to_payload(_make_candidate(), spot=519.0))
    assert result.verdict == "VETO"
    assert result.reason == "IV inverted"
    assert not result.allow


# ---------------------------------------------------------------------------
# Engine integration: reviewer veto blocks submission only when enforced
# ---------------------------------------------------------------------------

@dataclass
class _StubCreds:
    client_secret: str = ""
    refresh_token: str = ""
    account_number: str = "5WT00000"
    environment: str = "sandbox"


def _engine_config(*, reviewer_enabled: bool, veto_enforced: bool) -> dict[str, Any]:
    return {
        "underlyings": ["SPY"],
        "entry": {
            "short_dte_min": 0, "short_dte_max": 0,
            "long_dte_min": 30, "long_dte_max": 60,
            "short_delta_min": 0.40, "short_delta_max": 0.55,
            "direction": "auto",
            "max_debit_per_spread": 250,
            "min_open_interest_short": 500,
            "min_open_interest_long": 100,
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
        "risk": {"max_concurrent_spreads": 3, "max_total_debit": 1000, "max_spreads_per_underlying": 1},
        "schedule": {"manage_every_seconds": 30, "entry_window_start": "10:00", "entry_window_end": "11:30"},
        "agents": {
            "enabled": reviewer_enabled,
            "reviewer": {
                "enabled": reviewer_enabled,
                "model": "claude-opus-4-7",
                "veto_enforced": veto_enforced,
            },
        },
    }


async def test_engine_veto_enforced_blocks_submission(install_fake_anthropic, monkeypatch, tmp_path):
    install_fake_anthropic([
        _fake_event("agent.message", content=[
            types.SimpleNamespace(type="text", text='{"verdict": "VETO", "reason": "structural"}')
        ]),
        _fake_event("session.status_idle"),
    ])

    # Don't let the engine write to the repo's state/ dir.
    monkeypatch.chdir(tmp_path)

    from vantage_trader.engine import Engine

    client = MagicMock()
    # _get_spot uses get_equity_quote
    async def fake_get_equity_quote(symbol):
        return {"bid": "518.10", "ask": "518.30", "last": "518.20"}
    client.get_equity_quote = fake_get_equity_quote

    engine = Engine(
        client=client,
        creds=_StubCreds(),
        config=_engine_config(reviewer_enabled=True, veto_enforced=True),
        dry_run=True,
    )

    # Spy on _submit; with a VETO and veto_enforced=true it must not be called.
    submitted: list[Any] = []
    async def fake_submit(order, label):
        submitted.append((order, label))
    engine._submit = fake_submit  # type: ignore[method-assign]

    await engine._open_spread(_make_candidate())
    assert submitted == []
    assert engine.open_spreads == []


async def test_engine_veto_advisory_logs_but_submits(install_fake_anthropic, monkeypatch, tmp_path):
    install_fake_anthropic([
        _fake_event("agent.message", content=[
            types.SimpleNamespace(type="text", text='{"verdict": "VETO", "reason": "structural"}')
        ]),
        _fake_event("session.status_idle"),
    ])
    monkeypatch.chdir(tmp_path)

    from vantage_trader.engine import Engine

    client = MagicMock()
    async def fake_get_equity_quote(symbol):
        return {"bid": "518.10", "ask": "518.30", "last": "518.20"}
    client.get_equity_quote = fake_get_equity_quote

    engine = Engine(
        client=client,
        creds=_StubCreds(),
        config=_engine_config(reviewer_enabled=True, veto_enforced=False),
        dry_run=True,
    )

    submitted: list[Any] = []
    async def fake_submit(order, label):
        submitted.append((order, label))
    engine._submit = fake_submit  # type: ignore[method-assign]

    await engine._open_spread(_make_candidate())
    assert len(submitted) == 1   # VETO is advisory -> still submitted
    assert engine.open_spreads and engine.open_spreads[0].underlying == "SPY"


async def test_engine_reviewer_disabled_skips_agent_call(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    # Ensure even if `anthropic` is missing, engine works when agents disabled.
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))

    from vantage_trader.engine import Engine

    client = MagicMock()
    async def fake_get_equity_quote(symbol):
        return {"bid": "518.10", "ask": "518.30", "last": "518.20"}
    client.get_equity_quote = fake_get_equity_quote

    engine = Engine(
        client=client,
        creds=_StubCreds(),
        config=_engine_config(reviewer_enabled=False, veto_enforced=True),
        dry_run=True,
    )
    assert engine.agent_runtime is None

    submitted: list[Any] = []
    async def fake_submit(order, label):
        submitted.append((order, label))
    engine._submit = fake_submit  # type: ignore[method-assign]

    await engine._open_spread(_make_candidate())
    assert len(submitted) == 1
