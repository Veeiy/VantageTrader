"""Position sizing.

cap      = min(max_loss_abs, max_loss_bp_frac * buying_power)   (hard caps: $700, 0.93)
quantity = min(max_quantity, floor(cap / max_loss_per_unit))
quantity == 0 -> no trade (reason returned).
"""
from __future__ import annotations

import math
from typing import Any


def risk_cap(buying_power: float, cfg: dict[str, Any]) -> float:
    if buying_power is None or buying_power <= 0:
        return 0.0
    return round(min(cfg["max_loss_abs"], cfg["max_loss_bp_frac"] * buying_power), 2)


def quantity_for(max_loss_per_unit: float, cap: float, cfg: dict[str, Any]) -> tuple[int, str | None]:
    if cap <= 0:
        return 0, "no_buying_power"
    if max_loss_per_unit is None or max_loss_per_unit <= 0:
        return 0, "invalid_max_loss"
    q = min(cfg["max_quantity"], math.floor(cap / max_loss_per_unit + 1e-9))
    if q <= 0:
        return 0, "max_loss_exceeds_cap"
    return int(q), None
