"""Weekly calibration from closed trades. Proposes a config diff; NEVER writes config.

Per-structure stats: trades, win_rate, avg_pnl, total_pnl, avg realized/implied
(|realized_move| / implied_move), avg entry edge_ratio.

Threshold update (only when total closed trades >= ``calibrate_min_trades``, 8):
  edge_ratio is the engine's forecast of |realized|/implied. For each side
  (sell = credit structures -> sell_max_ratio; buy = debit structures -> buy_min_ratio):
      bias   = mean(|realized|/implied) / mean(edge_ratio)    (>1: moves bigger than forecast)
      raw    = current / bias
      weight = n_side / (n_side + calibrate_prior_weight)     (shrink toward current)
      new    = clamp(current + weight*(raw - current), bounds), rounded to 0.01
  bounds: sell_max_ratio in [0.70, 0.95], buy_min_ratio in [1.15, 1.60].
  A side with no usable trades keeps its threshold.
"""
from __future__ import annotations

from statistics import mean
from typing import Any

from . import journal as jr


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _usable(t: dict[str, Any]) -> bool:
    return bool(t.get("implied_move")) and t.get("realized_move") is not None and bool(t.get("edge_ratio"))


def structure_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for s in sorted({str(t.get("structure")) for t in trades}):
        ts = [t for t in trades if str(t.get("structure")) == s]
        pnls = [t["pnl"] for t in ts if t["pnl"] is not None]
        ri = [abs(t["realized_move"]) / t["implied_move"] for t in ts if _usable(t)]
        er = [t["edge_ratio"] for t in ts if t.get("edge_ratio")]
        out[s] = {
            "trades": len(ts),
            "win_rate": round(sum(1 for t in ts if t["pnl"] is not None and t["pnl"] > 0) / len(ts), 4),
            "avg_pnl": round(mean(pnls), 2) if pnls else None,
            "total_pnl": round(sum(pnls), 2) if pnls else None,
            "avg_realized_over_implied": round(mean(ri), 4) if ri else None,
            "avg_edge_ratio": round(mean(er), 4) if er else None,
        }
    return out


def _propose(current: float, side: list[dict[str, Any]], bounds: list[float], prior: int) -> tuple[float, dict[str, Any]]:
    use = [t for t in side if _usable(t)]
    if not use:
        return current, {"n": 0, "bias": None}
    ri = mean(abs(t["realized_move"]) / t["implied_move"] for t in use)
    er = mean(t["edge_ratio"] for t in use)
    bias = ri / er if er > 0 else 1.0
    if bias <= 0:
        return current, {"n": len(use), "bias": round(bias, 4)}
    raw = current / bias
    w = len(use) / (len(use) + prior) if (len(use) + prior) > 0 else 1.0
    new = round(_clamp(current + w * (raw - current), bounds[0], bounds[1]), 2)
    return new, {"n": len(use), "bias": round(bias, 4), "raw": round(raw, 4), "weight": round(w, 4)}


def calibrate(events: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    trades = jr.closed_trades(events)
    n = len(trades)
    current = {"sell_max_ratio": cfg["sell_max_ratio"], "buy_min_ratio": cfg["buy_min_ratio"]}
    result: dict[str, Any] = {
        "closed_trades": n, "min_required": cfg["calibrate_min_trades"],
        "stats": structure_stats(trades), "current": current, "proposed": dict(current),
        "diff": {}, "details": {}, "writes_config": False,
        "bounds": {"sell_max_ratio": cfg["sell_max_ratio_bounds"], "buy_min_ratio": cfg["buy_min_ratio_bounds"]},
    }
    if n < cfg["calibrate_min_trades"]:
        result["reason"] = f"need >= {cfg['calibrate_min_trades']} closed trades before moving thresholds (have {n})"
        return result
    sells = [t for t in trades if t["direction"] == "credit"]
    buys = [t for t in trades if t["direction"] == "debit"]
    prior = cfg["calibrate_prior_weight"]
    s_new, s_det = _propose(cfg["sell_max_ratio"], sells, cfg["sell_max_ratio_bounds"], prior)
    b_new, b_det = _propose(cfg["buy_min_ratio"], buys, cfg["buy_min_ratio_bounds"], prior)
    result["proposed"] = {"sell_max_ratio": s_new, "buy_min_ratio": b_new}
    result["details"] = {"sell_max_ratio": s_det, "buy_min_ratio": b_det}
    for k, v in result["proposed"].items():
        if abs(v - current[k]) >= 0.005:
            result["diff"][k] = {"from": current[k], "to": v}
    result["reason"] = "proposed diff (apply manually)" if result["diff"] else "no change warranted"
    return result
