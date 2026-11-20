"""P/L projection for an iron fly held through earnings, and the cross-check afterwards.

Brad, 2026-11-10: "Project the p/l factoring in the earnings iv crush. Then I want you to
cross check from where they open tomorrow so we can hone in on accurate projections."

Model (kept simple on purpose, so its errors can be measured):
  * Everything is priced from the TOTAL remaining standard deviation to expiry,
    ``sigma`` (a fraction of spot, e.g. 0.09), not from an annualised IV. That avoids
    calendar-day versus trading-day conventions. Black-Scholes with zero rates.
  * Before the report the front expiry holds the earnings jump plus ordinary ("ambient")
    movement. After the report only the ambient part is left. The ambient daily variance
    is read from the market: the forward variance between the front expiry and the next
    one, which contains no report.
  * Projection inputs that will be wrong, and are scored the next morning:
      1. the exit spot (how much of the after-hours move holds),
      2. the remaining ``sigma`` (the size of the IV crush),
      3. everything else: skew on the wings, stale quotes, fill versus mid.
    ``attribute`` splits the projection error into exactly those three parts.

Nothing here places orders or reads the market.
"""
from __future__ import annotations

import math
from typing import Any

from .config import EngineInputError


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def call_put(spot: float, strike: float, sigma: float) -> tuple[float, float]:
    """Black-Scholes call and put for total remaining stdev ``sigma`` (zero rates)."""
    if spot <= 0 or strike <= 0:
        raise EngineInputError("spot and strike must be positive")
    if sigma <= 0:
        return max(spot - strike, 0.0), max(strike - spot, 0.0)
    d1 = (math.log(spot / strike) + 0.5 * sigma * sigma) / sigma
    d2 = d1 - sigma
    call = spot * _cdf(d1) - strike * _cdf(d2)
    return call, call - spot + strike


def straddle(spot: float, strike: float, sigma: float) -> float:
    c, p = call_put(spot, strike, sigma)
    return c + p


def implied_sigma(spot: float, strike: float, straddle_price: float) -> float | None:
    """Total stdev that reproduces a straddle price; None when the price is below intrinsic."""
    intrinsic = abs(spot - strike)
    if straddle_price <= intrinsic + 1e-9:
        return None
    lo, hi = 1e-6, 5.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if straddle(spot, strike, mid) < straddle_price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def ambient_daily_variance(front_iv: float, front_days: float, back_iv: float, back_days: float,
                           trading_days_between: float) -> float:
    """Per-trading-day variance implied for the window between two expiries.

    ``front_iv`` / ``back_iv`` are annualised IVs on a calendar-day basis (as brokers quote
    them), ``front_days`` / ``back_days`` the calendar days to each expiry.
    """
    if back_days <= front_days or trading_days_between <= 0:
        raise EngineInputError("the back expiry must be later than the front one")
    fwd = back_iv * back_iv * back_days / 365.0 - front_iv * front_iv * front_days / 365.0
    if fwd <= 0:
        raise EngineInputError("term structure gives a non-positive forward variance")
    return fwd / trading_days_between


def fly_close_cost(spot: float, body: float, call_wing: float, put_wing: float, sigma: float,
                   wing_sigma_mult: float = 1.0) -> dict[str, float]:
    """Model mid prices of the four legs and the cost to close the short fly."""
    bc, bp = call_put(spot, body, sigma)
    wc, _ = call_put(spot, call_wing, sigma * wing_sigma_mult)
    _, wp = call_put(spot, put_wing, sigma * wing_sigma_mult)
    return {"body_call": bc, "body_put": bp, "wing_call": wc, "wing_put": wp,
            "close_cost": bc + bp - wc - wp}


def project(pos: dict[str, Any]) -> dict[str, Any]:
    """Scenario grid for one fly.

    ``pos`` keys: symbol, body, call_wing, put_wing, credit, quantity, close (entry-day
    close), spot_base (after-hours price), spots (list), sigma_base, sigmas (list),
    optional wing_sigma_mult, slippage_usd (expected cost of exiting versus mid, total).
    """
    need = ("symbol", "body", "call_wing", "put_wing", "credit", "quantity", "spot_base", "sigma_base")
    missing = [k for k in need if pos.get(k) is None]
    if missing:
        raise EngineInputError(f"projection input is missing {missing}")
    qty, credit = float(pos["quantity"]), float(pos["credit"])
    mult = float(pos.get("wing_sigma_mult", 1.0))
    slip = float(pos.get("slippage_usd", 0.0))

    def pnl(spot: float, sigma: float) -> tuple[float, float]:
        cc = fly_close_cost(spot, pos["body"], pos["call_wing"], pos["put_wing"], sigma, mult)["close_cost"]
        return cc, (credit - cc) * 100.0 * qty

    base_cc, base_pnl = pnl(float(pos["spot_base"]), float(pos["sigma_base"]))
    spots = [float(s) for s in pos.get("spots") or [pos["spot_base"]]]
    sigmas = [float(s) for s in pos.get("sigmas") or [pos["sigma_base"]]]
    grid = []
    for s in spots:
        row = {"spot": round(s, 4)}
        for sg in sigmas:
            row[f"sigma_{sg:.3f}"] = round(pnl(s, sg)[1], 2)
        grid.append(row)
    all_pnls = [v for r in grid for k, v in r.items() if k != "spot"]
    return {
        "symbol": pos["symbol"], "quantity": qty, "credit": credit,
        "structure": {"body": pos["body"], "call_wing": pos["call_wing"], "put_wing": pos["put_wing"]},
        "base": {"spot": float(pos["spot_base"]), "sigma": float(pos["sigma_base"]),
                 "legs": {k: round(v, 4) for k, v in fly_close_cost(
                     float(pos["spot_base"]), pos["body"], pos["call_wing"], pos["put_wing"],
                     float(pos["sigma_base"]), mult).items()},
                 "close_cost": round(base_cc, 4), "pnl_mid_usd": round(base_pnl, 2),
                 "pnl_after_slippage_usd": round(base_pnl - slip, 2)},
        "grid_pnl_mid_usd": grid,
        "range_pnl_mid_usd": [round(min(all_pnls), 2), round(max(all_pnls), 2)],
        "assumptions": {"wing_sigma_mult": mult, "slippage_usd": slip},
    }


def attribute(pos: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    """Split the projection error into spot, vol and the rest.

    ``pos`` is the projection input. ``actual`` keys: spot (at the exit read), straddle_mid
    (body call + body put mids), close_cost_mid (all four legs at mid), and optionally
    fill_debit (what was actually paid to close).
    """
    for k in ("spot", "straddle_mid", "close_cost_mid"):
        if actual.get(k) is None:
            raise EngineInputError(f"actual is missing {k}")
    qty, credit = float(pos["quantity"]), float(pos["credit"])
    mult = float(pos.get("wing_sigma_mult", 1.0))
    body, cw, pw = pos["body"], pos["call_wing"], pos["put_wing"]
    s0, g0 = float(pos["spot_base"]), float(pos["sigma_base"])
    s1 = float(actual["spot"])
    g1 = implied_sigma(s1, body, float(actual["straddle_mid"]))

    def cost(spot: float, sigma: float) -> float:
        return fly_close_cost(spot, body, cw, pw, sigma, mult)["close_cost"]

    projected = cost(s0, g0)
    spot_only = cost(s1, g0)
    model_actual = cost(s1, g1) if g1 is not None else None
    to_usd = 100.0 * qty
    actual_mid = float(actual["close_cost_mid"])
    out: dict[str, Any] = {
        "symbol": pos["symbol"],
        "projected": {"spot": s0, "sigma": g0, "close_cost": round(projected, 4),
                      "pnl_mid_usd": round((credit - projected) * to_usd, 2)},
        "actual": {"spot": s1, "sigma_implied": round(g1, 4) if g1 is not None else None,
                   "close_cost_mid": round(actual_mid, 4), "pnl_mid_usd": round((credit - actual_mid) * to_usd, 2)},
        "error_usd": round((projected - actual_mid) * to_usd, 2),   # actual P/L minus projected P/L
        "from_spot_usd": round((projected - spot_only) * to_usd, 2),
        "from_vol_usd": round((spot_only - model_actual) * to_usd, 2) if model_actual is not None else None,
        "from_skew_and_quotes_usd": round((model_actual - actual_mid) * to_usd, 2) if model_actual is not None else None,
        "ratios": {
            "sigma_actual_over_projected": round(g1 / g0, 4) if g1 is not None and g0 > 0 else None,
        },
    }
    if pos.get("close") and pos.get("spot_base"):
        ah, close = float(pos["spot_base"]), float(pos["close"])
        if abs(ah - close) > 1e-9:
            out["ratios"]["share_of_after_hours_move_kept"] = round((s1 - close) / (ah - close), 4)
    if actual.get("fill_debit") is not None:
        fill = float(actual["fill_debit"])
        out["fill"] = {"debit": fill, "pnl_usd": round((credit - fill) * to_usd, 2),
                       "slippage_vs_mid_usd": round((fill - actual_mid) * to_usd, 2)}
    return out
