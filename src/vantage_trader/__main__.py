"""VantageTrader CLI.

Usage:
    python -m vantage_trader run                 # run the engine (dry-run unless config says otherwise)
    python -m vantage_trader scan-once           # one-shot: scan, print candidates, exit
    python -m vantage_trader accounts            # list accounts visible to the session
    python -m vantage_trader daily-report        # run the Post-Mortem Journalist for today (cron-friendly)
    python -m vantage_trader worker              # run the self-hosted Managed Agents worker (long-running)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from .config import load_credentials, load_strategy_config
from .engine import Engine
from .logging_setup import configure_logging
from .tastytrade.client import TastytradeClient

log = logging.getLogger("vantage_trader")


def _make_client(creds) -> TastytradeClient:
    return TastytradeClient(
        client_secret=creds.client_secret,
        refresh_token=creds.refresh_token,
        environment=creds.environment,
    )


async def _run() -> None:
    creds = load_credentials()
    cfg = load_strategy_config()
    dry_run = bool(cfg.get("dry_run", True))
    async with _make_client(creds) as client:
        engine = Engine(client=client, creds=creds, config=cfg, dry_run=dry_run)
        await engine.run_forever()


async def _scan_once() -> None:
    creds = load_credentials()
    cfg = load_strategy_config()
    async with _make_client(creds) as client:
        engine = Engine(client=client, creds=creds, config=cfg, dry_run=True)
        await engine.scan_and_enter()


async def _accounts() -> None:
    creds = load_credentials()
    async with _make_client(creds) as client:
        for acct in await client.list_accounts():
            log.info(
                "%s  type=%s  nickname=%s",
                acct.get("account-number"),
                acct.get("account-type-name"),
                acct.get("nickname"),
            )


async def _daily_report(target: date | None) -> None:
    creds = load_credentials()
    cfg = load_strategy_config()
    async with _make_client(creds) as client:
        engine = Engine(client=client, creds=creds, config=cfg, dry_run=True)
        report = await engine.generate_daily_report(target=target)
        log.info("report written: %s", report.path_written)


async def _worker() -> None:
    """Long-running self-hosted Managed Agents worker.

    Polls the work queue for the configured environment, downloads skills,
    runs tool calls (bash, file ops, etc.) in `workdir`, and posts results
    back to Anthropic. Authenticates with ANTHROPIC_ENVIRONMENT_KEY (not
    your API key -- the env key is queue-scoped).

    Generated once-per-environment in the Anthropic Console; see README.
    """
    load_dotenv()
    cfg = load_strategy_config()
    agents_cfg = cfg.get("agents") or {}
    env_cfg = agents_cfg.get("environment") or {}

    if env_cfg.get("type", "cloud") != "self_hosted":
        raise RuntimeError(
            "agents.environment.type must be 'self_hosted' to run a worker. "
            "Set it in config.yaml, or run sessions against a cloud "
            "environment (no worker needed there)."
        )

    env_id = env_cfg.get("id") or os.environ.get("ANTHROPIC_ENVIRONMENT_ID")
    env_key = os.environ.get("ANTHROPIC_ENVIRONMENT_KEY")
    workdir = Path(env_cfg.get("workdir", "./workspace")).resolve()

    if not env_id:
        raise RuntimeError(
            "Set ANTHROPIC_ENVIRONMENT_ID (in .env) or agents.environment.id "
            "in config.yaml. Create the environment with `python -m "
            "vantage_trader daily-report` once, then copy the id it logs."
        )
    if not env_key:
        raise RuntimeError(
            "Set ANTHROPIC_ENVIRONMENT_KEY in .env. Generate one in the "
            "Anthropic Console under Workspace > Environments > "
            f"{env_id} > Generate environment key."
        )

    workdir.mkdir(parents=True, exist_ok=True)
    log.info("worker starting env=%s workdir=%s", env_id, workdir)

    # Imported lazily so the rest of the CLI works without the SDK installed.
    from anthropic import AsyncAnthropic
    from anthropic.lib.environments import EnvironmentWorker

    async with AsyncAnthropic(auth_token=env_key) as client:
        await EnvironmentWorker(
            client,
            environment_id=env_id,
            environment_key=env_key,
            workdir=str(workdir),
        ).run()


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(prog="vantage_trader")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="Run the engine loop")
    sub.add_parser("scan-once", help="Scan & log candidates once, then exit (always dry-run)")
    sub.add_parser("accounts", help="List accounts on the session")
    p_report = sub.add_parser(
        "daily-report",
        help="Run the Post-Mortem Journalist agent for a trading day",
    )
    p_report.add_argument(
        "--date",
        help="Trading day in YYYY-MM-DD (defaults to today in ET)",
        default=None,
    )
    sub.add_parser(
        "worker",
        help="Long-running self-hosted Managed Agents worker (polls the queue, "
             "runs tool calls locally). Required when agents.environment.type "
             "is self_hosted.",
    )
    args = parser.parse_args()

    if args.cmd == "run":
        asyncio.run(_run())
    elif args.cmd == "scan-once":
        asyncio.run(_scan_once())
    elif args.cmd == "accounts":
        asyncio.run(_accounts())
    elif args.cmd == "daily-report":
        target = date.fromisoformat(args.date) if args.date else None
        asyncio.run(_daily_report(target))
    elif args.cmd == "worker":
        asyncio.run(_worker())


if __name__ == "__main__":
    main()
