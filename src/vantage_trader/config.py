from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass
class Credentials:
    client_secret: str
    refresh_token: str
    account_number: str
    environment: str  # 'sandbox' | 'live'


def load_credentials() -> Credentials:
    load_dotenv()
    env = os.getenv("TASTY_ENV", "sandbox").lower()
    client_secret = os.getenv("TASTY_CLIENT_SECRET")
    refresh_token = os.getenv("TASTY_REFRESH_TOKEN")
    account = os.getenv("TASTY_ACCOUNT_NUMBER")
    missing = [
        name for name, val in [
            ("TASTY_CLIENT_SECRET", client_secret),
            ("TASTY_REFRESH_TOKEN", refresh_token),
            ("TASTY_ACCOUNT_NUMBER", account),
        ] if not val
    ]
    if missing:
        raise RuntimeError(
            f"Missing required env vars: {', '.join(missing)}. "
            "Copy .env.example to .env and fill them in. See README for how to "
            "generate a Personal OAuth Grant on tastytrade."
        )
    if env not in ("sandbox", "live"):
        raise RuntimeError(f"TASTY_ENV must be 'sandbox' or 'live' (got {env!r})")
    return Credentials(
        client_secret=client_secret,  # type: ignore[arg-type]
        refresh_token=refresh_token,  # type: ignore[arg-type]
        account_number=account,        # type: ignore[arg-type]
        environment=env,
    )


def load_strategy_config(path: str | os.PathLike | None = None) -> dict[str, Any]:
    p = Path(path or os.getenv("VANTAGE_CONFIG", "config.yaml"))
    if not p.exists():
        raise FileNotFoundError(
            f"Strategy config not found at {p}. Copy config.example.yaml -> config.yaml."
        )
    with p.open("r") as f:
        cfg = yaml.safe_load(f) or {}
    _validate_strategy_config(cfg)
    return cfg


def _validate_strategy_config(cfg: dict[str, Any]) -> None:
    required_top = ["underlyings", "entry", "management", "risk"]
    for key in required_top:
        if key not in cfg:
            raise ValueError(f"config.yaml missing required section: {key}")
    if not cfg["underlyings"]:
        raise ValueError("config.yaml: 'underlyings' is empty")
    for k in ("short_dte_min", "short_dte_max", "long_dte_min", "long_dte_max"):
        if k not in cfg["entry"]:
            raise ValueError(f"config.yaml entry.{k} is required")
    if cfg["entry"]["short_dte_min"] > cfg["entry"]["short_dte_max"]:
        raise ValueError("short_dte_min must be <= short_dte_max")
    if cfg["entry"]["long_dte_min"] > cfg["entry"]["long_dte_max"]:
        raise ValueError("long_dte_min must be <= long_dte_max")
