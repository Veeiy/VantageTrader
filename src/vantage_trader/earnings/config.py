"""Load and validate ``config/earnings.yaml``.

Every key has a default, so an empty (or absent default) config file yields a
working engine. Validation rules:

* Unknown keys are rejected (a typo must never silently fall back to a default).
* Hard caps from BLUEPRINT.md are enforced in code: a config may only TIGHTEN
  them, never loosen them (see ``HARD_CAPS``). ``TSLA`` is always blocklisted.
* ``sell_max_ratio`` must be < ``buy_min_ratio`` and both must sit inside the
  calibration bounds.

Any violation raises :class:`ConfigError`, which the CLI maps to exit code 2.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


class EngineInputError(ValueError):
    """Invalid input (snapshot, journal, config). CLI exit code 2."""


class ConfigError(EngineInputError):
    pass


DEFAULTS: dict[str, Any] = {
    # --- universe / filters ---
    "blocklist": ["TSLA"],
    "min_price": 10.0,
    "max_spread_pct": 0.12,
    "max_intraday_move": 0.05,
    # --- scoring ---
    "straddle_factor": 0.85,
    "min_history": 4,
    "history_lookback": 12,
    "sell_max_ratio": 0.85,
    "buy_min_ratio": 1.25,
    "min_ev_per_dollar_risk": 0.0,
    # --- structures ---
    "wing_widths_pct": [0.05, 0.075, 0.10, 0.125],
    # --- risk / sizing ---
    "max_open_positions": 1,
    "max_loss_abs": 700.0,
    "max_loss_bp_frac": 0.93,
    "max_quantity": 1,
    # --- order pricing ---
    "tick": 0.05,
    "step_small": 0.05,
    "step_large": 0.10,
    "step_threshold": 3.0,
    "credit_floor_mid_frac": 0.92,
    "debit_ceiling_mid_frac": 1.06,
    "cancel_by": "12:50 America/Los_Angeles",
    # --- circuit breaker ---
    "min_account_value": 400.0,
    "max_consecutive_max_loss": 2,
    "max_consecutive_losses": 3,
    "max_loss_tolerance": 0.90,
    "circuit_reset_ts": None,
    # --- exits ---
    "exit_min_minutes_since_open": 10,
    "straddle_take_profit": 0.50,
    "market_timezone": "America/New_York",
    # --- calibration ---
    "calibrate_min_trades": 8,
    "calibrate_prior_weight": 8,
    "sell_max_ratio_bounds": [0.70, 0.95],
    "buy_min_ratio_bounds": [1.15, 1.60],
    # --- paths ---
    "journal_path": "state/earnings/journal.jsonl",
}

# key -> (direction, limit). "max": value must be <= limit. "min": value must be >= limit.
HARD_CAPS: dict[str, tuple[str, float]] = {
    "max_loss_abs": ("max", 700.0),
    "max_loss_bp_frac": ("max", 0.93),
    "max_open_positions": ("max", 1),
    "max_spread_pct": ("max", 0.12),
    "min_price": ("min", 10.0),
    "min_account_value": ("min", 400.0),
    "max_consecutive_max_loss": ("max", 2),
    "max_consecutive_losses": ("max", 3),
    "cancel_by_latest_minutes": ("max", 12 * 60 + 50),  # virtual key, checked below
}
ALWAYS_BLOCKED = ("TSLA",)

_NUMERIC = {
    "min_price", "max_spread_pct", "max_intraday_move", "straddle_factor",
    "sell_max_ratio", "buy_min_ratio", "min_ev_per_dollar_risk", "max_loss_abs",
    "max_loss_bp_frac", "tick", "step_small", "step_large", "step_threshold",
    "credit_floor_mid_frac", "debit_ceiling_mid_frac", "min_account_value",
    "max_loss_tolerance", "straddle_take_profit",
}
_INT = {
    "min_history", "history_lookback", "max_open_positions", "max_quantity",
    "max_consecutive_max_loss", "max_consecutive_losses",
    "exit_min_minutes_since_open", "calibrate_min_trades", "calibrate_prior_weight",
}
_POSITIVE = {
    "min_price", "straddle_factor", "sell_max_ratio", "buy_min_ratio", "max_loss_abs",
    "max_loss_bp_frac", "tick", "step_small", "step_large", "step_threshold",
    "credit_floor_mid_frac", "debit_ceiling_mid_frac", "min_history", "history_lookback",
    "max_open_positions", "max_quantity", "max_consecutive_max_loss",
    "max_consecutive_losses", "max_spread_pct", "max_intraday_move", "max_loss_tolerance",
    "straddle_take_profit", "calibrate_min_trades",
}


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_cancel_by(value: str) -> tuple[int, int, str]:
    """'12:50 America/Los_Angeles' -> (12, 50, 'America/Los_Angeles')."""
    try:
        hhmm, tz = value.strip().split(None, 1)
        hh, mm = hhmm.split(":")
        h, m = int(hh), int(mm)
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError
    except (ValueError, AttributeError):
        raise ConfigError(f"cancel_by must look like 'HH:MM Area/City', got {value!r}")
    return h, m, tz.strip()


def validate(cfg: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(cfg) - set(DEFAULTS))
    if unknown:
        raise ConfigError(f"unknown config keys: {unknown}")
    out = copy.deepcopy(DEFAULTS)
    out.update({k: v for k, v in cfg.items()})

    for k in _NUMERIC:
        if not _is_number(out[k]):
            raise ConfigError(f"{k} must be a number, got {out[k]!r}")
        out[k] = float(out[k])
    for k in _INT:
        v = out[k]
        if not (_is_number(v) and float(v).is_integer()):
            raise ConfigError(f"{k} must be an integer, got {v!r}")
        out[k] = int(v)
    for k in _POSITIVE:
        if out[k] <= 0:
            raise ConfigError(f"{k} must be > 0, got {out[k]!r}")
    if out["min_ev_per_dollar_risk"] < 0:
        raise ConfigError("min_ev_per_dollar_risk must be >= 0")
    if out["calibrate_prior_weight"] < 0:
        raise ConfigError("calibrate_prior_weight must be >= 0")

    # blocklist
    bl = out["blocklist"]
    if not isinstance(bl, list) or not all(isinstance(s, str) for s in bl):
        raise ConfigError("blocklist must be a list of ticker strings")
    bl = [s.strip().upper() for s in bl]
    for s in ALWAYS_BLOCKED:
        if s not in bl:
            bl.append(s)
    out["blocklist"] = bl

    # wings
    w = out["wing_widths_pct"]
    if not isinstance(w, list) or not w or not all(_is_number(x) and 0 < x < 1 for x in w):
        raise ConfigError("wing_widths_pct must be a non-empty list of fractions in (0,1)")
    out["wing_widths_pct"] = sorted(float(x) for x in w)

    # fractions that must be <= 1
    for k in ("max_loss_bp_frac", "max_loss_tolerance", "credit_floor_mid_frac"):
        if out[k] > 1:
            raise ConfigError(f"{k} must be <= 1")
    if out["debit_ceiling_mid_frac"] < 1:
        raise ConfigError("debit_ceiling_mid_frac must be >= 1")

    # bounds
    for bk, tk in (("sell_max_ratio_bounds", "sell_max_ratio"), ("buy_min_ratio_bounds", "buy_min_ratio")):
        b = out[bk]
        if not (isinstance(b, list) and len(b) == 2 and all(_is_number(x) for x in b) and b[0] < b[1]):
            raise ConfigError(f"{bk} must be [low, high] with low < high")
        out[bk] = [float(b[0]), float(b[1])]
        if not (out[bk][0] <= out[tk] <= out[bk][1]):
            raise ConfigError(f"{tk}={out[tk]} outside {bk}={out[bk]}")
    if out["sell_max_ratio_bounds"] != DEFAULTS["sell_max_ratio_bounds"] and not (
        out["sell_max_ratio_bounds"][0] >= 0.70 and out["sell_max_ratio_bounds"][1] <= 0.95
    ):
        raise ConfigError("sell_max_ratio_bounds may only narrow [0.70, 0.95]")
    if out["buy_min_ratio_bounds"] != DEFAULTS["buy_min_ratio_bounds"] and not (
        out["buy_min_ratio_bounds"][0] >= 1.15 and out["buy_min_ratio_bounds"][1] <= 1.60
    ):
        raise ConfigError("buy_min_ratio_bounds may only narrow [1.15, 1.60]")
    if out["sell_max_ratio"] >= out["buy_min_ratio"]:
        raise ConfigError("sell_max_ratio must be < buy_min_ratio")

    # hard caps (config may only tighten)
    for k, (direction, limit) in HARD_CAPS.items():
        if k not in out:
            continue
        v = out[k]
        if direction == "max" and v > limit:
            raise ConfigError(f"{k}={v} exceeds hard cap {limit}")
        if direction == "min" and v < limit:
            raise ConfigError(f"{k}={v} is below hard floor {limit}")

    if not isinstance(out["cancel_by"], str):
        raise ConfigError("cancel_by must be a string like '12:50 America/Los_Angeles'")
    h, m, tz = parse_cancel_by(out["cancel_by"])
    if tz == "America/Los_Angeles" and h * 60 + m > HARD_CAPS["cancel_by_latest_minutes"][1]:
        raise ConfigError("cancel_by may not be later than 12:50 America/Los_Angeles")
    for k in ("market_timezone",):
        if not isinstance(out[k], str):
            raise ConfigError(f"{k} must be a string")
    _check_tz(out["market_timezone"])
    _check_tz(tz)
    if out["circuit_reset_ts"] is not None and not isinstance(out["circuit_reset_ts"], str):
        raise ConfigError("circuit_reset_ts must be null or an ISO timestamp string")
    if not isinstance(out["journal_path"], str) or not out["journal_path"]:
        raise ConfigError("journal_path must be a non-empty string")
    return out


def _check_tz(name: str) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"unknown timezone {name!r}")


def load_config(path: str | Path | None = None, *, must_exist: bool = True) -> dict[str, Any]:
    """Load YAML config and merge onto defaults. ``path=None`` -> pure defaults."""
    if path is None:
        return validate({})
    p = Path(path)
    if not p.exists():
        if must_exist:
            raise ConfigError(f"config file not found: {p}")
        return validate({})
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"config is not valid YAML: {e}")
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")
    return validate(raw)
