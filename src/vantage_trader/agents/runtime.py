"""Managed Agents SDK wrapper.

Wraps the (sync) `anthropic.Anthropic` client so our async engine can use
Managed Agents without blocking the event loop. One `AgentRuntime` instance
owns:

  * a single `environment` (cloud or self-hosted; created lazily, or reused
    via env id)
  * a registry of agent ids keyed by role (e.g. "reviewer")

Each `run()` call opens a one-shot session, sends a single user message,
streams events until `session.status_idle`, and returns the concatenated
agent text. No conversational memory across calls -- the engine drives
the trading loop, agents just answer focused questions.

Environment types:
  * `cloud`       - Anthropic-managed sandbox container, configurable network
                    policy. The full toolset's bash/file ops run in their
                    cloud.
  * `self_hosted` - Tool execution runs on YOUR host (a worker process polls
                    the queue and runs tool calls locally). Anthropic still
                    runs the model + orchestration. See README for the
                    two-process setup.

Requires `anthropic>=0.45`. The SDK sets the `managed-agents-2026-04-01`
beta header automatically.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger(__name__)

EnvType = Literal["cloud", "self_hosted"]


@dataclass
class AgentSpec:
    """Definition of one role on the agent team."""
    key: str                             # local registry key, e.g. "reviewer"
    name: str                            # display name in the Anthropic console
    model: str                           # e.g. "claude-opus-4-7"
    system: str                          # system prompt
    tools: list[dict[str, Any]] = field(default_factory=list)


class AgentRuntime:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        environment_id: str | None = None,
        environment_name: str = "vantage-trader",
        env_type: EnvType = "cloud",
        networking: str = "unrestricted",
    ) -> None:
        # The SDK client is built lazily on first use so constructing a
        # runtime is free -- callers (e.g. the engine) can instantiate one
        # eagerly under `agents.enabled: true` without paying for the
        # import or requiring `anthropic` to be installed until an agent
        # actually runs.
        self._api_key = api_key
        self._client: Any | None = None
        self._environment_id = environment_id
        self._environment_name = environment_name
        self._env_type: EnvType = env_type
        self._networking = networking
        self._agent_ids: dict[str, str] = {}
        self._env_lock = asyncio.Lock()
        self._register_locks: dict[str, asyncio.Lock] = {}

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self._api_key) if self._api_key else Anthropic()
        return self._client

    # ---- environment ------------------------------------------------------

    def _env_config(self) -> dict[str, Any]:
        if self._env_type == "self_hosted":
            return {"type": "self_hosted"}
        return {"type": "cloud", "networking": {"type": self._networking}}

    async def ensure_environment(self) -> str:
        async with self._env_lock:
            if self._environment_id:
                return self._environment_id
            client = self._get_client()
            config = self._env_config()
            env = await asyncio.to_thread(
                lambda: client.beta.environments.create(
                    name=self._environment_name,
                    config=config,
                )
            )
            self._environment_id = env.id
            log.info(
                "created managed-agents environment id=%s type=%s",
                env.id, self._env_type,
            )
            if self._env_type == "self_hosted":
                log.info(
                    "next step: generate an environment key in the Anthropic Console "
                    "for env id %s, set ANTHROPIC_ENVIRONMENT_ID and "
                    "ANTHROPIC_ENVIRONMENT_KEY in .env, and run "
                    "`python -m vantage_trader worker` in a second terminal.",
                    env.id,
                )
            return env.id

    # ---- agent registration ----------------------------------------------

    async def register(self, spec: AgentSpec, *, agent_id: str | None = None) -> str:
        """Register an agent under `spec.key`. If `agent_id` is provided, reuse it;
        otherwise create a new agent and store its id.
        """
        lock = self._register_locks.setdefault(spec.key, asyncio.Lock())
        async with lock:
            if spec.key in self._agent_ids:
                return self._agent_ids[spec.key]
            if agent_id:
                self._agent_ids[spec.key] = agent_id
                log.info("registered managed agent key=%s id=%s (reused)", spec.key, agent_id)
                return agent_id
            client = self._get_client()
            agent = await asyncio.to_thread(
                lambda: client.beta.agents.create(
                    name=spec.name,
                    model=spec.model,
                    system=spec.system,
                    tools=spec.tools,
                )
            )
            self._agent_ids[spec.key] = agent.id
            log.info("created managed agent key=%s id=%s", spec.key, agent.id)
            return agent.id

    def agent_id(self, key: str) -> str | None:
        return self._agent_ids.get(key)

    # ---- one-shot session run --------------------------------------------

    async def run(self, *, key: str, user_message: str, title: str) -> str:
        """Open a session for the agent registered under `key`, send one user
        message, stream events until idle, and return the concatenated text
        from `agent.message` events.
        """
        agent_id = self._agent_ids.get(key)
        if not agent_id:
            raise RuntimeError(f"agent {key!r} not registered; call register() first")
        env_id = await self.ensure_environment()

        client = self._get_client()
        return await asyncio.to_thread(self._run_session_sync, client, agent_id, env_id, user_message, title)

    def _run_session_sync(self, client: Any, agent_id: str, env_id: str, user_message: str, title: str) -> str:
        session = client.beta.sessions.create(
            agent=agent_id,
            environment_id=env_id,
            title=title,
        )
        chunks: list[str] = []
        with client.beta.sessions.events.stream(session.id) as stream:
            client.beta.sessions.events.send(
                session.id,
                events=[{
                    "type": "user.message",
                    "content": [{"type": "text", "text": user_message}],
                }],
            )
            for event in stream:
                etype = getattr(event, "type", None)
                if etype == "agent.message":
                    for block in event.content:
                        if getattr(block, "type", None) == "text":
                            chunks.append(block.text)
                elif etype == "agent.tool_use":
                    log.debug("agent tool_use: %s", getattr(event, "name", "?"))
                elif etype == "session.status_idle":
                    break
        return "".join(chunks)
