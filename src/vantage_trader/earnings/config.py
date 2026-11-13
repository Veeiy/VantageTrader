"""Load and validate ``config/earnings.yaml``.

Every key has a default, so an empty (or absent default) config file yields a
working engine. Validation rules:

* Unknown keys are rejected (a typo must never silently fall back to a default).
* Hard caps are enforced in code: a config may only TIGHTEN them, never loosen them
  (see ``HARD_CAPS``). ``TSLA`` is always blocklisted. Since P004 (2026-11-11) the caps
  carry the live rules v1.1-v1.5 (docs/earnings/RULES_CHANGELOG.md): total risk cap
  min($1,000, 0.93 x account value) across ALL open positions, ATM spread <= 25% with a
  $350 max loss above 12%, intraday move 5% (7% with a sector move), regime guard 1.25x,
  edge ratio <= 0.85 (<= 0.70 "tight"), >= 4 past moves, contracts by risk (v1.7 and v1.8:
  a target max loss per name, up to ``max_quantity`` contracts; the one-contract limit is
  gone). There is no limit on the number of open positions (v1.4).
* ``sell_max_ratio`` must be < ``buy_min_ratio`` and both must sit inside the
  calibration bounds.
* ``cancel_by`` may use any timezone; it is converted to America/Los_Angeles (checked on
  both a winter and a summer reference date) and must be <= 12:50 PT.
* ``market_holidays``: ISO dates on which NYSE is closed (default: 2026-2027 NYSE full
  closures). Used to find the next trading day for BMO entry timing.
* ``market_early_closes``: ISO dates with a 13:00 ET close; an entry whose expiry falls on
  one is skipped (bad_expiry). Default includes 2027-12-24 as requested, even though that
  date is also a full closure (Christmas observed) in ``market_holidays``.
* ``exit_slippage_reserve`` (USD per unit, in [0, 100], default 50): budget held back at
  entry (max_loss_worst <= risk_cap - reserve*qty) and spent at exit (closing debit of a
  credit structure may reach W + reserve/100). Realised loss <= max_loss_worst + reserve*qty
  <= risk_cap.

Any violation raises :class:`ConfigError`, which the CLI maps to exit code 2.
"""
from __future__ import annotations

import copy
from datetime import date, datetime
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
    "max_spread_pct": 0.25,          # v1.1: ATM bid-ask <= 25% of mid
    "wide_spread_pct": 0.12,         # v1.1: above this the trade's max loss is capped ...
    "wide_spread_max_loss": 350.0,   # ... at this many USD
    "max_intraday_move": 0.05,
    "max_intraday_move_sector": 0.07,  # v1.1: 5-7% only with a same-direction sector move, no stock news
    "regime_mult": 1.25,             # v1.1: 20-session avg |daily move| must be < this x avg earnings move
    # --- scoring ---
    "straddle_factor": 0.85,
    "min_history": 4,
    "history_lookback": 12,
    "sell_max_ratio": 0.85,
    "tight_max_ratio": 0.70,         # v1.5: edge ratio at or under this may be entered early
    "near_miss_max_ratio": 1.10,     # v1.10: edge ratio above sell_max_ratio and up to this is tradable at reduced size
    "near_miss_size_frac": 0.5,      # v1.10: share of the name target and of the name cap a near-miss name may use
    "buy_min_ratio": 1.25,           # long straddles are OFF (P010): this only labels "long_straddle_off"
    "min_ev_per_dollar_risk": 0.0,
    # --- structures ---
    "wing_widths_pct": [0.05, 0.075, 0.10, 0.125],
    # --- risk / sizing ---
    "max_loss_abs": 1000.0,          # 2026-11-11: total risk cap min($1,000, 0.93 x account value)
    "max_loss_bp_frac": 0.93,
    "max_quantity": 10,              # v1.7: most contracts one name may hold (hard cap 10)
    "name_risk_frac": 0.20,          # v1.8: max loss one name should carry, as a share of account value (was 0.12 in v1.7)
    "name_risk_cap": 350.0,          # max loss per name at the credit floor (owner limit, hard cap $350)
    "early_tranche_frac": 0.5,       # v1.7: share of the name target that may be entered before the final window
    "add_center_frac": 0.25,         # v1.7: an add needs spot within this x body straddle of the body strike
    "final_window_start": "11:30 America/Los_Angeles",  # v1.7: from here a name may be entered at full size
    "exit_buyback_mult": 1.1,        # v1.9: one in-the-money short leg at the wing (x width x 100) must fit the buying power left after entry
    "exit_slippage_reserve": 50.0,
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
    # --- calendar ---
    "market_holidays": [
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
        "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
        "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
        "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
    ],
    "market_early_closes": ["2026-11-27", "2026-12-24", "2027-11-26", "2027-12-24"],
    "max_expiry_days_after_report": 7,
    # --- paths ---
    "journal_path": "state/earnings/journal.jsonl",
}


def norm_symbol(s: Any) -> str:
    """Canonical ticker form used everywhere (blocklist, positions, journal)."""
    return str(s if s is not None else "").strip().upper()

# key -> (direction, limit). "max": value must be <= limit. "min": value must be >= limit.
HARD_CAPS: dict[str, tuple[str, float]] = {
    "max_loss_abs": ("max", 1000.0),
    "max_loss_bp_frac": ("max", 0.93),
    "max_spread_pct": ("max", 0.25),
    "wide_spread_pct": ("max", 0.12),
    "wide_spread_max_loss": ("max", 350.0),
    "max_quantity": ("max", 10),
    "name_risk_frac": ("max", 0.27),    # the $350 name cap is the binding owner limit
    "name_risk_cap": ("max", 350.0),
    "near_miss_max_ratio": ("max", 1.10),   # v1.10: the reduced-size tier may not reach further
    "near_miss_size_frac": ("max", 0.5),    # ... and may not be sized above half
    "early_tranche_frac": ("max", 1.0),
    "add_center_frac": ("max", 0.5),
    "exit_buyback_mult": ("min", 1.0),   # the exit check may only be made stricter
    "min_price": ("min", 10.0),
    "min_account_value": ("min", 400.0),
    "max_consecutive_max_loss": ("max", 2),
    "max_consecutive_losses": ("max", 3),
    "cancel_by_latest_minutes": ("max", 12 * 60 + 50),  # virtual key, checked below
}
ALWAYS_BLOCKED = ("TSLA",)

_NUMERIC = {
    "min_price", "max_spread_pct", "max_intraday_move", "straddle_factor",
    "wide_spread_pct", "wide_spread_max_loss", "max_intraday_move_sector", "regime_mult",
    "tight_max_ratio", "name_risk_frac", "name_risk_cap", "early_tranche_frac", "add_center_frac",
    "exit_buyback_mult", "near_miss_max_ratio", "near_miss_size_frac",
    "sell_max_ratio", "buy_min_ratio", "min_ev_per_dollar_risk", "max_loss_abs",
    "max_loss_bp_frac", "tick", "step_small", "step_large", "step_threshold",
    "credit_floor_mid_frac", "debit_ceiling_mid_frac", "min_account_value",
    "max_loss_tolerance", "straddle_take_profit", "exit_slippage_reserve",
}
_INT = {
    "min_history", "history_lookback", "max_quantity",
    "max_consecutive_max_loss", "max_consecutive_losses",
    "exit_min_minutes_since_open", "calibrate_min_trades", "calibrate_prior_weight",
    "max_expiry_days_after_report",
}
_POSITIVE = {
    "min_price", "straddle_factor", "sell_max_ratio", "buy_min_ratio", "max_loss_abs",
    "max_loss_bp_frac", "tick", "step_small", "step_large", "step_threshold",
    "credit_floor_mid_frac", "debit_ceiling_mid_frac", "min_history", "history_lookback",
    "max_quantity", "max_consecutive_max_loss", "wide_spread_pct", "wide_spread_max_loss",
    "max_intraday_move_sector", "regime_mult", "tight_max_ratio",
    "name_risk_frac", "name_risk_cap", "early_tranche_frac", "add_center_frac", "exit_buyback_mult",
    "near_miss_max_ratio", "near_miss_size_frac",
    "max_consecutive_losses", "max_spread_pct", "max_intraday_move", "max_loss_tolerance",
    "straddle_take_profit", "calibrate_min_trades", "max_expiry_days_after_report",
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
    bl = [norm_symbol(s) for s in bl]
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
    if out["tight_max_ratio"] > out["sell_max_ratio"]:
        raise ConfigError("tight_max_ratio must be <= sell_max_ratio")
    # v1.10: the near-miss tier sits between the sell gate and the long-straddle label.
    # near_miss_max_ratio == sell_max_ratio switches the tier off.
    if out["near_miss_max_ratio"] < out["sell_max_ratio"]:
        raise ConfigError("near_miss_max_ratio must be >= sell_max_ratio (equal switches the tier off)")
    if out["near_miss_max_ratio"] >= out["buy_min_ratio"]:
        raise ConfigError("near_miss_max_ratio must be < buy_min_ratio")
    if out["wide_spread_pct"] > out["max_spread_pct"]:
        raise ConfigError("wide_spread_pct must be <= max_spread_pct")
    if out["max_intraday_move"] > out["max_intraday_move_sector"]:
        raise ConfigError("max_intraday_move must be <= max_intraday_move_sector")

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
    _check_tz(tz)
    if cancel_by_la_minutes(out["cancel_by"]) > HARD_CAPS["cancel_by_latest_minutes"][1]:
        raise ConfigError("cancel_by may not be later than 12:50 America/Los_Angeles")
    if not isinstance(out["final_window_start"], str):
        raise ConfigError("final_window_start must be a string like '11:30 America/Los_Angeles'")
    _check_tz(parse_cancel_by(out["final_window_start"])[2])
    if cancel_by_la_minutes(out["final_window_start"]) >= cancel_by_la_minutes(out["cancel_by"]):
        raise ConfigError("final_window_start must be earlier than cancel_by")
    for k in ("market_timezone",):
        if not isinstance(out[k], str):
            raise ConfigError(f"{k} must be a string")
    _check_tz(out["market_timezone"])
    for k in ("market_holidays", "market_early_closes"):
        lst = out[k]
        if not isinstance(lst, list):
            raise ConfigError(f"{k} must be a list of YYYY-MM-DD dates")
        try:
            out[k] = sorted({date.fromisoformat(str(d)).isoformat() for d in lst})
        except ValueError:
            raise ConfigError(f"{k} entries must be YYYY-MM-DD dates")
    if not (0.0 <= out["exit_slippage_reserve"] <= 100.0):
        raise ConfigError("exit_slippage_reserve must be within [0, 100] USD per unit")
    if out["circuit_reset_ts"] is not None and not isinstance(out["circuit_reset_ts"], str):
        raise ConfigError("circuit_reset_ts must be null or an ISO timestamp string")
    if not isinstance(out["journal_path"], str) or not out["journal_path"]:
        raise ConfigError("journal_path must be a non-empty string")
    return out


def cancel_by_la_minutes(value: str) -> int:
    """Latest Los Angeles wall-clock minute-of-day the cancel_by time maps to
    (checked in January and July so DST differences between zones are covered)."""
    from zoneinfo import ZoneInfo

    h, m, tz = parse_cancel_by(value)
    la = ZoneInfo("America/Los_Angeles")
    worst = 0
    for ref in (date(2026, 1, 15), date(2026, 7, 15)):
        t = datetime(ref.year, ref.month, ref.day, h, m, tzinfo=ZoneInfo(tz)).astimezone(la)
        mins = t.hour * 60 + t.minute + (24 * 60 if t.date() > ref else 0) - (24 * 60 if t.date() < ref else 0)
        worst = max(worst, mins)
    return worst


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
