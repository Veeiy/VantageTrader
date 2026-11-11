"""Position sizing.

cap      = min(max_loss_abs, max_loss_bp_frac * account_value)   (hard caps: $1,000, 0.93)
           This is the TOTAL risk cap across ALL open positions (earnings and non-earnings),
           max loss plus exit reserves (RULES_CHANGELOG v1.3 and the 2026-11-11 decision).
           It is computed from account value, not buying power: buying power already drops
           by the collateral of open positions and would count them twice (v1.3).
budget   = cap - open_risk_usd (max loss + exit reserves of the positions already open)
quantity = min(max_quantity, floor(budget / max_loss_per_unit)), and 1 while fewer than
           ``data_phase_trades`` (10) live trades are closed (v1.3 data phase).
quantity == 0 -> no trade (reason returned).
"""
from __future__ import annotations

import math
from typing import Any


def risk_cap(account_value: float, cfg: dict[str, Any]) -> float:
    if account_value is None or account_value <= 0:
        return 0.0
    return round(min(cfg["max_loss_abs"], cfg["max_loss_bp_frac"] * account_value), 2)


def risk_budget(account_value: float, open_risk_usd: float, cfg: dict[str, Any]) -> float:
    """What is left of the total risk cap after the positions already open."""
    return round(max(risk_cap(account_value, cfg) - max(open_risk_usd, 0.0), 0.0), 2)


def max_quantity(closed_live_trades: int, cfg: dict[str, Any]) -> int:
    """Contracts per earnings name: 1 during the data phase (v1.3), else ``max_quantity``."""
    if closed_live_trades < cfg["data_phase_trades"]:
        return min(1, cfg["max_quantity"])
    return cfg["max_quantity"]


def quantity_for(max_loss_per_unit: float, cap: float, cfg: dict[str, Any],
                 limit: int | None = None) -> tuple[int, str | None]:
    if cap <= 0:
        return 0, "no_buying_power"
    if max_loss_per_unit is None or max_loss_per_unit <= 0:
        return 0, "invalid_max_loss"
    q = min(cfg["max_quantity"] if limit is None else limit, math.floor(cap / max_loss_per_unit + 1e-9))
    if q <= 0:
        return 0, "max_loss_exceeds_cap"
    return int(q), None
