"""Position sizing.

cap      = min(max_loss_abs, max_loss_bp_frac * account_value)   (hard caps: $1,000, 0.93)
           This is the TOTAL risk cap across ALL open positions (earnings and non-earnings),
           max loss plus exit reserves (RULES_CHANGELOG v1.3 and the 2026-11-11 decision).
           It is computed from account value, not buying power: buying power already drops
           by the collateral of open positions and would count them twice (v1.3).
budget   = cap - open_risk_usd (max loss + exit reserves of the positions already open)

Contracts per name (v1.7, owner 2026-11-11: "you can open more contracts for one ticker if
it meets the criteria. or want to scale in as well."): size by risk, not by count.

target   = min(name_risk_cap, name_risk_frac * account_value)   ($350 hard cap; 0.20 since v1.8)
           the max loss one name should carry, at the credit floor. It is a target, not
           a ceiling: contracts are rounded to the NEAREST whole number, so a name lands
           on either side of it. The ceilings are name_risk_cap and the budget.
planned  = NEW contracts: (target - max loss already held) / max loss of one contract,
           rounded to the nearest whole number (one contract is always allowed on a name
           with nothing held), and never more than fits
             name_risk_cap with what is held (rounded down),
             the budget, max loss + reserve of the new contracts (rounded down),
             max_quantity contracts on the name.
now      = planned in the final window. Before it (phase "early") only what keeps the
           name at or under early_tranche_frac of the target, rounded DOWN (one contract
           is still allowed on a name with nothing held): an early fly can drift off its
           body strike before the report, so the rest waits for the final window.
planned == 0 -> no trade (the binding limit is returned as the reason).
"""
from __future__ import annotations

import math
from typing import Any

EPS = 1e-9


def risk_cap(account_value: float, cfg: dict[str, Any]) -> float:
    if account_value is None or account_value <= 0:
        return 0.0
    return round(min(cfg["max_loss_abs"], cfg["max_loss_bp_frac"] * account_value), 2)


def risk_budget(account_value: float, open_risk_usd: float, cfg: dict[str, Any]) -> float:
    """What is left of the total risk cap after the positions already open."""
    return round(max(risk_cap(account_value, cfg) - max(open_risk_usd, 0.0), 0.0), 2)


def name_target(account_value: float, cfg: dict[str, Any]) -> float:
    """Max loss one name should carry: a share of the account, never above name_risk_cap."""
    if account_value is None or account_value <= 0:
        return 0.0
    return round(min(cfg["name_risk_cap"], cfg["name_risk_frac"] * account_value), 2)


def max_quantity(closed_live_trades: int, cfg: dict[str, Any]) -> int:
    """Most contracts one name may hold. The one-contract data phase ended with v1.7."""
    return int(cfg["max_quantity"])


def plan(max_loss_per_unit: float, reserve_per_unit: float, account_value: float,
         open_risk_usd: float, cfg: dict[str, Any], *, held_qty: int = 0,
         held_max_loss: float = 0.0, phase: str = "final") -> dict[str, Any]:
    """How many contracts to add on one name: in total (``planned``) and at this check-in (``now``).

    ``max_loss_per_unit`` is the max loss of one new contract at the credit floor.
    ``open_risk_usd`` already includes the tranche held on this name, if any.
    """
    if phase not in ("early", "final"):
        raise ValueError(f"phase must be 'early' or 'final', got {phase!r}")
    target = name_target(account_value, cfg)
    budget = risk_budget(account_value, open_risk_usd, cfg)
    out: dict[str, Any] = {"target": target, "name_cap": cfg["name_risk_cap"], "budget": budget,
                           "held_qty": int(held_qty), "held_max_loss": round(float(held_max_loss), 2),
                           "phase": phase, "planned": 0, "now": 0, "later": 0, "limits": {}, "binding": None}
    ml = max_loss_per_unit
    if ml is None or ml <= 0:
        out["binding"] = "invalid_max_loss"
        return out
    if budget <= 0:
        out["binding"] = "no_buying_power"
        return out
    first = held_qty <= 0
    by_target = math.floor((target - held_max_loss) / ml + 0.5 + EPS)   # nearest whole number
    if first and by_target < 1:
        by_target = 1                     # one contract is allowed up to name_risk_cap
    limits = {
        "name_target_reached": by_target,
        "name_risk_cap": math.floor((cfg["name_risk_cap"] - held_max_loss) / ml + EPS),
        "max_loss_exceeds_cap": math.floor(budget / (ml + max(reserve_per_unit, 0.0)) + EPS),
        "max_quantity": int(cfg["max_quantity"]) - int(held_qty),
    }
    out["limits"] = dict(limits)
    binding = min(limits, key=lambda k: limits[k])
    planned = max(0, limits[binding])
    out["planned"] = planned
    if planned == 0:
        out["binding"] = binding
        return out
    if phase == "final":
        now = planned
    else:
        now = math.floor((cfg["early_tranche_frac"] * target - held_max_loss) / ml + EPS)
        if first and now < 1:
            now = 1
        now = max(0, min(now, planned))
    out["now"], out["later"] = now, planned - now
    out["binding"] = "early_tranche_full" if now == 0 else binding
    return out


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
