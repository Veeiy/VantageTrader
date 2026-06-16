"""VantageTrader CLI.

Usage:
    python -m vantage_trader run                 # run the engine (dry-run unless config says otherwise)
    python -m vantage_trader scan-once           # one-shot: scan, print candidates, exit
    python -m vantage_trader accounts            # list accounts visible to the session
    python -m vantage_trader daily-report        # run the Post-Mortem Journalist for today (cron-friendly)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date

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


if __name__ == "__main__":
    main()
