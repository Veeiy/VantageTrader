"""Tick rounding and limit-price ladders for entry orders.

Credit (iron fly):
    limit_start = mid rounded to nearest tick
    limit_floor = max(W - cap/(100*qty), natural, credit_floor_mid_frac*mid), rounded UP
    -> no trade if limit_floor > limit_start.
    Because the floor is never below ``W - cap/(100*qty)``, the worst-case fill keeps
    (W - fill) * 100 * qty <= cap.

Debit (long straddle):
    limit_start = mid rounded to nearest tick
    limit_floor = min(natural, debit_ceiling_mid_frac*mid, cap/(100*qty)), rounded DOWN
    (``limit_floor`` is the WORST acceptable debit, i.e. the ceiling.)
    -> no trade if limit_floor < limit_start.

limit_step = step_small (0.05) when limit_start < step_threshold (3.00) else step_large (0.10).
"""
from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any


def _round(x: float, tick: float, mode: str) -> float:
    # Quantize to 1e-9 first so float noise (13.350000000000001) does not bump a tick.
    d = Decimal(repr(float(x))).quantize(Decimal("1e-9"), rounding=ROUND_HALF_UP)
    t = Decimal(repr(float(tick)))
    q = (d / t).quantize(Decimal("1"), rounding=mode)
    return float(q * t)


def round_nearest(x: float, tick: float = 0.05) -> float:
    return round(_round(x, tick, ROUND_HALF_UP), 4)


def round_up(x: float, tick: float = 0.05) -> float:
    return round(_round(x, tick, ROUND_CEILING), 4)


def round_down(x: float, tick: float = 0.05) -> float:
    return round(_round(x, tick, ROUND_FLOOR), 4)


def limit_step(price: float, cfg: dict[str, Any]) -> float:
    return cfg["step_small"] if price < cfg["step_threshold"] else cfg["step_large"]


def credit_limits(mid: float, natural: float, width: float, cap: float, qty: int,
                  cfg: dict[str, Any]) -> tuple[float, float, float] | None:
    """Return (limit_start, limit_floor, limit_step) or None when no fillable range."""
    tick = cfg["tick"]
    start = round_nearest(mid, tick)
    floor = round_up(max(width - cap / (100.0 * qty), natural, cfg["credit_floor_mid_frac"] * mid), tick)
    if start <= 0 or floor > start or start >= width:
        return None
    return start, floor, limit_step(start, cfg)


def debit_limits(mid: float, natural: float, cap: float, qty: int,
                 cfg: dict[str, Any]) -> tuple[float, float, float] | None:
    """Return (limit_start, limit_floor=worst debit, limit_step) or None."""
    tick = cfg["tick"]
    start = round_nearest(mid, tick)
    worst = round_down(min(natural, cfg["debit_ceiling_mid_frac"] * mid, cap / (100.0 * qty)), tick)
    if start <= 0 or worst < start:
        return None
    return start, worst, limit_step(start, cfg)
