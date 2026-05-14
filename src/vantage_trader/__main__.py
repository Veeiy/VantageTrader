"""VantageTrader CLI.

Usage:
    python -m vantage_trader run                 # run the engine (dry-run unless config says otherwise)
    python -m vantage_trader scan-once           # one-shot: scan, print candidates, exit
    python -m vantage_trader accounts            # list accounts visible to the session
"""
from __future__ import annotations

import argparse
import asyncio
import logging

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


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(prog="vantage_trader")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="Run the engine loop")
    sub.add_parser("scan-once", help="Scan & log candidates once, then exit (always dry-run)")
    sub.add_parser("accounts", help="List accounts on the session")
    args = parser.parse_args()

    if args.cmd == "run":
        asyncio.run(_run())
    elif args.cmd == "scan-once":
        asyncio.run(_scan_once())
    elif args.cmd == "accounts":
        asyncio.run(_accounts())


if __name__ == "__main__":
    main()
