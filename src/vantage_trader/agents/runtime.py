"""Managed Agents SDK wrapper.

Wraps the (sync) `anthropic.Anthropic` client so our async engine can use
Managed Agents without blocking the event loop. One `AgentRuntime` instance
owns:

  * a single cloud `environment` (created lazily, or reused via env id)
  * a registry of agent ids keyed by role (e.g. "reviewer")

Each `run()` call opens a one-shot session, sends a single user message,
streams events until `session.status_idle`, and returns the concatenated
agent text. No conversational memory across calls -- the engine drives
the trading loop, agents just answer focused questions.

Requires `anthropic>=0.45`. The SDK sets the `managed-agents-2026-04-01`
beta header automatically.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


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
        networking: str = "unrestricted",
    ) -> None:
        # Imported lazily so the rest of the bot still works without the SDK installed
        # when agents are disabled.
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key) if api_key else Anthropic()
        self._environment_id = environment_id
        self._environment_name = environment_name
        self._networking = networking
        self._agent_ids: dict[str, str] = {}
        self._env_lock = asyncio.Lock()
        self._register_locks: dict[str, asyncio.Lock] = {}

    # ---- environment ------------------------------------------------------

    async def ensure_environment(self) -> str:
        async with self._env_lock:
            if self._environment_id:
                return self._environment_id
            env = await asyncio.to_thread(
                lambda: self._client.beta.environments.create(
                    name=self._environment_name,
                    config={"type": "cloud", "networking": {"type": self._networking}},
                )
            )
            self._environment_id = env.id
            log.info("created managed-agents environment id=%s", env.id)
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
            agent = await asyncio.to_thread(
                lambda: self._client.beta.agents.create(
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

        return await asyncio.to_thread(self._run_session_sync, agent_id, env_id, user_message, title)

    def _run_session_sync(self, agent_id: str, env_id: str, user_message: str, title: str) -> str:
        client = self._client
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
