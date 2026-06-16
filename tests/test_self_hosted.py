"""Tests for the self-hosted Managed Agents path.

Covers AgentRuntime's env-type branch (cloud vs. self_hosted), engine
config plumbing (env id env-var fallback), and the worker CLI's preflight
guards. The EnvironmentWorker itself isn't exercised end-to-end -- that's
an integration test against a real Anthropic environment.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest


# Shared fake-Anthropic helpers (mirrors test_journalist.py; kept inline so
# each test file is independently readable).

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
            self.last_env_create_kwargs = None
            FakeAnthropic.instances.append(self)

            self.beta = types.SimpleNamespace()
            self.beta.agents = MagicMock()
            self.beta.agents.create = MagicMock(
                return_value=types.SimpleNamespace(id=agent_id, version=1)
            )
            self.beta.environments = MagicMock()

            def _env_create(**kwargs):
                self.last_env_create_kwargs = kwargs
                return types.SimpleNamespace(id=env_id)
            self.beta.environments.create = MagicMock(side_effect=_env_create)

            self.beta.sessions = MagicMock()
            self.beta.sessions.create = MagicMock(
                return_value=types.SimpleNamespace(id="sess_test")
            )
            self.beta.sessions.events = MagicMock()
            self.beta.sessions.events.stream = MagicMock(
                return_value=_FakeStream(stream_events)
            )
            self.beta.sessions.events.send = MagicMock()

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
# AgentRuntime env-type branch
# ---------------------------------------------------------------------------

async def test_runtime_creates_self_hosted_environment(install_fake_anthropic):
    mod = install_fake_anthropic([_fake_event("session.status_idle")])

    from vantage_trader.agents.runtime import AgentRuntime

    rt = AgentRuntime(api_key="sk-test", env_type="self_hosted")
    await rt.ensure_environment()

    client = mod.Anthropic.instances[-1]
    kwargs = client.last_env_create_kwargs
    assert kwargs["config"] == {"type": "self_hosted"}


async def test_runtime_creates_cloud_environment_by_default(install_fake_anthropic):
    mod = install_fake_anthropic([_fake_event("session.status_idle")])

    from vantage_trader.agents.runtime import AgentRuntime

    rt = AgentRuntime(api_key="sk-test")
    await rt.ensure_environment()

    client = mod.Anthropic.instances[-1]
    kwargs = client.last_env_create_kwargs
    assert kwargs["config"]["type"] == "cloud"
    assert kwargs["config"]["networking"]["type"] == "unrestricted"


async def test_runtime_self_hosted_with_existing_env_id_skips_create(install_fake_anthropic):
    mod = install_fake_anthropic([])

    from vantage_trader.agents.runtime import AgentRuntime

    rt = AgentRuntime(
        api_key="sk-test",
        env_type="self_hosted",
        environment_id="env_existing",
    )
    assert await rt.ensure_environment() == "env_existing"
    # Lazy init: no client touched at all when env id is preset.
    assert mod.Anthropic.instances == []


# ---------------------------------------------------------------------------
# Engine plumbing
# ---------------------------------------------------------------------------

@dataclass
class _StubCreds:
    client_secret: str = ""
    refresh_token: str = ""
    account_number: str = "5WT00000"
    environment: str = "sandbox"


def _engine_cfg(env_section: dict[str, Any]) -> dict[str, Any]:
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
            "enabled": True,
            "environment": env_section,
            "reviewer": {"enabled": False},
            "journalist": {"enabled": True, "model": "claude-opus-4-7"},
        },
    }


def test_engine_picks_up_self_hosted_env_type(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))

    from vantage_trader.engine import Engine

    cfg = _engine_cfg({"type": "self_hosted", "id": "env_from_config"})
    engine = Engine(client=MagicMock(), creds=_StubCreds(), config=cfg, dry_run=True)
    assert engine.agent_runtime is not None
    assert engine.agent_runtime._env_type == "self_hosted"
    assert engine.agent_runtime._environment_id == "env_from_config"


def test_engine_falls_back_to_env_var_for_self_hosted_id(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))
    monkeypatch.setenv("ANTHROPIC_ENVIRONMENT_ID", "env_from_envvar")

    from vantage_trader.engine import Engine

    # No id in config; should fall back to env var.
    cfg = _engine_cfg({"type": "self_hosted"})
    engine = Engine(client=MagicMock(), creds=_StubCreds(), config=cfg, dry_run=True)
    assert engine.agent_runtime._environment_id == "env_from_envvar"


def test_engine_cloud_env_does_not_read_env_var(monkeypatch, tmp_path):
    """Cloud envs should NOT silently adopt ANTHROPIC_ENVIRONMENT_ID -- that's
    a self-hosted-specific knob and mixing them up has been a real footgun."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))
    monkeypatch.setenv("ANTHROPIC_ENVIRONMENT_ID", "env_self_hosted")

    from vantage_trader.engine import Engine

    cfg = _engine_cfg({"type": "cloud"})
    engine = Engine(client=MagicMock(), creds=_StubCreds(), config=cfg, dry_run=True)
    assert engine.agent_runtime._environment_id is None


# ---------------------------------------------------------------------------
# Worker CLI guards
# ---------------------------------------------------------------------------

def _write_config(path, env_section: dict[str, Any]) -> None:
    import yaml
    path.write_text(yaml.safe_dump(_engine_cfg(env_section)))


async def test_worker_rejects_cloud_env(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {"type": "cloud"})
    monkeypatch.setenv("VANTAGE_CONFIG", str(cfg_path))
    monkeypatch.setenv("ANTHROPIC_ENVIRONMENT_ID", "env_x")
    monkeypatch.setenv("ANTHROPIC_ENVIRONMENT_KEY", "key_x")

    from vantage_trader.__main__ import _worker

    with pytest.raises(RuntimeError, match="self_hosted"):
        await _worker()


async def test_worker_requires_env_id(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {"type": "self_hosted"})
    monkeypatch.setenv("VANTAGE_CONFIG", str(cfg_path))
    monkeypatch.delenv("ANTHROPIC_ENVIRONMENT_ID", raising=False)
    monkeypatch.setenv("ANTHROPIC_ENVIRONMENT_KEY", "key_x")

    from vantage_trader.__main__ import _worker

    with pytest.raises(RuntimeError, match="ANTHROPIC_ENVIRONMENT_ID"):
        await _worker()


async def test_worker_requires_env_key(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {"type": "self_hosted", "id": "env_x"})
    monkeypatch.setenv("VANTAGE_CONFIG", str(cfg_path))
    monkeypatch.delenv("ANTHROPIC_ENVIRONMENT_KEY", raising=False)

    from vantage_trader.__main__ import _worker

    with pytest.raises(RuntimeError, match="ANTHROPIC_ENVIRONMENT_KEY"):
        await _worker()
