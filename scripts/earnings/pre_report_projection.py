"""Pre-report P/L projection for short iron flies held through an earnings report.

Usage: PYTHONPATH=src python3 scripts/earnings/pre_report_projection.py positions.json calibration.json [seed]

It draws the report move for each name, prices every fly at the planned exit and prints one JSON
object: per name and for the whole book the mean, the median, quantiles and the chance of a profit.
Nothing here places orders or reads the market. The constants come from the calibration file,
which the daily reflection updates from scored results (state/earnings/projection_calibration.json).
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np

_erf = np.vectorize(math.erf)


def _cdf(x):
    return 0.5 * (1.0 + _erf(x / math.sqrt(2.0)))


def call_put(spot, strike, sigma):
    """Black-Scholes call and put for total remaining stdev sigma, zero rates (as projection.call_put)."""
    d1 = (np.log(spot / strike) + 0.5 * sigma * sigma) / sigma
    call = spot * _cdf(d1) - strike * _cdf(d1 - sigma)
    return call, call - spot + strike


def close_cost(spot, p, sigma, wing_mult):
    bc, bp = call_put(spot, p["body"], sigma)
    wc, _ = call_put(spot, p["call_wing"], sigma * wing_mult)
    _, wp = call_put(spot, p["put_wing"], sigma * wing_mult)
    return bc + bp - wc - wp


def ambient_sigma(p, cal):
    fwd = p["back_iv"] ** 2 * p["back_days"] / 365.0 - p["front_iv"] ** 2 * p["front_days"] / 365.0
    daily_var = fwd / p["trading_days_between"]
    return math.sqrt(daily_var * p["days_left_at_exit"]), math.sqrt(daily_var)


def move_scale(p, cal):
    """Expected absolute report move: the name's own history blended with what names like it realise."""
    hist = float(np.mean(np.abs(p["hist_moves"])))
    market = cal["realized_over_implied"] * 0.85 * p["straddle_pct"]
    w = cal["blend_weight_history"]
    return w * hist + (1.0 - w) * market, hist, market


def summarise(x, max_loss):
    q = np.quantile(x, [0.05, 0.10, 0.25, 0.50, 0.75, 0.90])
    tail = x[x <= q[0]]
    return {"mean": round(float(x.mean()), 1), "median": round(float(q[3]), 1),
            "p_profit": round(float((x > 0).mean()), 3),
            "band_50": [round(float(q[2]), 1), round(float(q[4]), 1)],
            "band_80": [round(float(q[1]), 1), round(float(q[5]), 1)],
            "p05": round(float(q[0]), 1), "mean_of_worst_5pct": round(float(tail.mean()), 1),
            "p_loss_over_half_max": round(float((x < -0.5 * max_loss).mean()), 3), "max_loss": max_loss}


def main(argv):
    positions = json.load(open(argv[1]))
    cal = json.load(open(argv[2]))
    cal = cal.get("constants", cal)     # the calibration file keeps its constants in a block of that name
    rng = np.random.default_rng(int(argv[3]) if len(argv) > 3 else 20261117)
    n = int(cal.get("draws", 100000))
    market = rng.normal(0.0, cal["market_sigma_close_to_exit"], n)
    out, book = {"names": {}, "calibration_used": cal, "draws": n}, np.zeros(n)
    for p in positions:
        s, hist, mkt = move_scale(p, cal)
        base_amb, daily_vol = ambient_sigma(p, cal)
        sigma_base = base_amb * cal["sigma_multiplier"]
        move = s * rng.standard_t(cal["t_dof"], n) / cal["t_abs_mean"] + p["beta"] * market
        spot = p["close"] * np.maximum(1.0 + move, 0.05)
        sigma = sigma_base * np.exp(rng.normal(0.0, cal["sigma_uncertainty_log"], n))
        width = max(p["call_wing"] - p["body"], p["body"] - p["put_wing"])
        cost = np.clip(close_cost(spot, p, sigma, cal["wing_sigma_mult"]), 0.0, width)
        pnl = ((p["credit"] - cost) * 100.0 - p["slippage_usd_per_fly"]) * p["quantity"]
        max_loss = round((width - p["credit"]) * 100.0 * p["quantity"], 1)
        rec = summarise(pnl, max_loss)
        grid = {}
        for m in (-0.10, -0.08, -0.06, -0.04, -0.02, 0.0, 0.02, 0.04, 0.06, 0.08, 0.10):
            c = float(np.clip(close_cost(np.array([p["close"] * (1 + m)]), p, np.array([sigma_base]), cal["wing_sigma_mult"]), 0, width)[0])
            grid[f"{m:+.0%}"] = round(((p["credit"] - c) * 100.0 - p["slippage_usd_per_fly"]) * p["quantity"], 1)
        rec.update({"quantity": p["quantity"], "credit": p["credit"], "close": p["close"],
                    "expected_abs_move": round(s, 4), "from_history": round(hist, 4), "from_options": round(mkt, 4),
                    "ambient_daily_vol": round(daily_vol, 4), "sigma_base_at_exit": round(sigma_base, 4),
                    "slippage_usd_per_fly": p["slippage_usd_per_fly"], "pnl_by_move_at_base_sigma": grid,
                    "zero_line_moves": [k for k, v in grid.items() if v > 0][:1] + [k for k, v in grid.items() if v > 0][-1:]})
        out["names"][p["symbol"]] = rec
        book += pnl
    total_max = round(sum(v["max_loss"] for v in out["names"].values()), 1)
    out["book"] = summarise(book, total_max)
    out["book"]["p_loss_over_500"] = round(float((book < -500).mean()), 3)
    out["book"]["sum_of_name_means"] = round(sum(v["mean"] for v in out["names"].values()), 1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv)
