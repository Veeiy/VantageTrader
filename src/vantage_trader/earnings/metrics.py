"""Live metrics dataset (``state/earnings/live_metrics.jsonl``): read and summarise.

The journal is the ledger. This file holds the numbers around each trade (signal,
fill quality, outcome) so the rules can be calibrated on live results. Schema:
``docs/earnings/LIVE_METRICS.md``. Nothing here places orders or writes files.

Record types (``record``): ``entry``, ``adjust``, ``exit``, ``paper``.
A trade is closed when it has an ``exit`` record. ``adjust`` records (partial close,
trim) and exits tagged ``rebalance`` are left out of edge statistics and reported
separately as execution cost.
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from .config import EngineInputError

RECORDS = {"entry", "adjust", "exit", "paper"}
WIDE_SPREAD = 0.12  # ATM bid-ask / mid above this is the "wide" band (v1.1)


def read_metrics(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for n, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise EngineInputError(f"live metrics line {n} is not valid JSON: {e}")
        if not isinstance(obj, dict) or obj.get("record") not in RECORDS or not obj.get("trade_id"):
            raise EngineInputError(f"live metrics line {n}: missing trade_id or unknown record")
        out.append(obj)
    return out


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _avg(xs: list[float | None], nd: int = 4) -> float | None:
    vals = [x for x in xs if x is not None]
    return round(mean(vals), nd) if vals else None


def _block(rec: dict[str, Any], key: str) -> dict[str, Any]:
    b = rec.get(key)
    return b if isinstance(b, dict) else {}


def _execution_stats(recs: list[dict[str, Any]]) -> dict[str, Any]:
    ex = [_block(r, "execution") for r in recs]
    return {
        "n": len(recs),
        "avg_fill_vs_mid": _avg([_num(e.get("fill_vs_mid")) for e in ex]),
        "avg_seconds_to_fill": _avg([_num(e.get("seconds_first_order_to_last_fill")) for e in ex], 1),
        "avg_reprices": _avg([_num(e.get("reprices")) for e in ex], 2),
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    live = [r for r in records if r.get("live", True) and r.get("record") != "paper"]
    entries = {r["trade_id"]: r for r in live if r["record"] == "entry"}
    exits = {r["trade_id"]: r for r in live if r["record"] == "exit"}
    adjusts = [r for r in live if r["record"] == "adjust"]
    paper = [r for r in records if r.get("record") == "paper" or r.get("live") is False]

    # entry fill quality, overall and by spread band / tick size
    ent = list(entries.values())
    tight = [r for r in ent if (_num(_block(r, "signal").get("atm_spread_pct")) or 0.0) < WIDE_SPREAD]
    wide = [r for r in ent if (_num(_block(r, "signal").get("atm_spread_pct")) or 0.0) >= WIDE_SPREAD]
    by_tick: dict[str, list[dict[str, Any]]] = {}
    for r in ent:
        by_tick.setdefault(str(_block(r, "execution").get("tick")), []).append(r)

    # outcomes: closed trades, rebalances excluded from edge statistics
    closed = [(entries.get(tid), x) for tid, x in exits.items()]
    scored = [(e, x) for e, x in closed if x.get("tag") != "rebalance"
              and _block(x, "verdict").get("exit_reason") != "rebalance"]
    pnls = [_num(x.get("pnl_usd")) for _, x in scored]
    pnl_vals = [p for p in pnls if p is not None]
    roi, edges = [], []
    for e, x in scored:
        sig = _block(e or {}, "signal")
        rm, im, er = _num(x.get("realized_move")), _num(sig.get("implied_move")), _num(sig.get("edge_ratio"))
        if rm is not None and im:
            roi.append(abs(rm) / im)
            if er:
                edges.append(er)
    bias = round(mean(roi) / mean(edges), 4) if roi and edges and len(roi) == len(edges) and mean(edges) > 0 else None

    trades = []
    for tid, e in sorted(entries.items(), key=lambda kv: str(kv[1].get("ts"))):
        x = exits.get(tid)
        risk, exe, sig = _block(e, "risk"), _block(e, "execution"), _block(e, "signal")
        qty, max_loss = e.get("quantity"), risk.get("max_loss_usd")
        for a in adjusts:  # later adjust records win (file order)
            if a.get("trade_id") != tid:
                continue
            if a.get("open_quantity") is not None:
                qty = a["open_quantity"]
            if _block(a, "risk").get("max_loss_usd") is not None:
                max_loss = _block(a, "risk")["max_loss_usd"]
        trades.append({
            "trade_id": tid, "symbol": e.get("symbol"), "kind": e.get("kind"), "quantity": qty,
            "edge_ratio": sig.get("edge_ratio"), "fill_credit": exe.get("fill_credit"),
            "fill_vs_mid": exe.get("fill_vs_mid"), "max_loss_usd": max_loss,
            "status": "closed" if x else "open",
            "pnl_usd": x.get("pnl_usd") if x else None,
            "realized_move": x.get("realized_move") if x else None,
        })

    return {
        "counts": {"entries": len(entries), "closed": len(exits), "open": len(entries) - len(exits),
                   "adjusts": len(adjusts), "paper": len(paper)},
        "entry_execution": {
            "all": _execution_stats(ent),
            "tight_spread": _execution_stats(tight),
            "wide_spread": _execution_stats(wide),
            "by_tick": {k: _execution_stats(v) for k, v in sorted(by_tick.items())},
        },
        "exit_execution": _execution_stats([x for _, x in closed]),
        "outcomes": {
            "n": len(scored),
            "wins": sum(1 for p in pnl_vals if p > 0),
            "win_rate": round(sum(1 for p in pnl_vals if p > 0) / len(pnl_vals), 4) if pnl_vals else None,
            "total_pnl_usd": round(sum(pnl_vals), 2) if pnl_vals else None,
            "avg_pnl_usd": _avg(pnls, 2),
            "avg_realized_over_implied": _avg(roi),
            "avg_edge_ratio": _avg(edges),
            "edge_bias": bias,  # >1: moves were bigger than the edge ratio forecast
        },
        "adjust_cost_usd": round(sum(_num(a.get("pnl_usd")) or 0.0 for a in adjusts), 2),
        "paper": {
            "n": len(paper),
            "pnl_mid_usd": round(sum(_num(r.get("pnl_mid_usd")) or 0.0 for r in paper), 2),
            "pnl_natural_usd": round(sum(_num(r.get("pnl_natural_usd")) or 0.0 for r in paper), 2),
            "scored": sum(1 for r in paper if _num(r.get("pnl_mid_usd")) is not None),
        },
        "trades": trades,
    }


# ---------------------------------------------------------------- paper desk import

PAPER_NEVER = {"TSLA"}   # never TSLA, on paper either


def _paper_key(rec: dict[str, Any]) -> tuple[Any, ...]:
    return (rec.get("trade_id"), rec.get("ts"), "mark" in rec, bool(rec.get("result")))


def import_paper(desk_path: str | Path, metrics_path: str | Path) -> dict[str, Any]:
    """Append the records a read-only paper-desk agent wrote to the live metrics dataset.

    The desk writes one JSON object per line. Only ``paper`` records with ``live`` false are
    taken. A line already in the dataset (same trade_id, ts and stage) is skipped, so the
    import can be run again. Bad lines are reported, never appended.
    """
    dp = Path(desk_path)
    if not dp.exists():
        raise EngineInputError(f"paper desk file not found: {desk_path}")
    have = {_paper_key(r) for r in read_metrics(metrics_path) if r.get("record") == "paper"}
    added: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    skipped = 0
    for n, line in enumerate(dp.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            rejected.append({"line": n, "reason": f"not valid JSON: {e}"})
            continue
        why = None
        if not isinstance(rec, dict):
            why = "not an object"
        elif rec.get("record") != "paper":
            why = "record is not 'paper'"
        elif rec.get("live") is not False:
            why = "live must be false"
        elif not isinstance(rec.get("trade_id"), str) or not rec["trade_id"].strip():
            why = "trade_id missing"
        elif not isinstance(rec.get("symbol"), str) or not rec["symbol"].strip():
            why = "symbol missing"
        elif rec["symbol"].strip().upper() in PAPER_NEVER:
            why = "symbol is never traded, on paper either"
        elif not isinstance(rec.get("ts"), str) or not rec["ts"].strip():
            why = "ts missing"
        elif any(k in rec and _num(rec[k]) is None for k in ("pnl_mid_usd", "pnl_natural_usd")):
            why = "pnl fields must be numbers"
        if why:
            rejected.append({"line": n, "reason": why})
            continue
        key = _paper_key(rec)
        if key in have:
            skipped += 1
            continue
        have.add(key)
        added.append(rec)
    if added:
        mp = Path(metrics_path)
        mp.parent.mkdir(parents=True, exist_ok=True)
        with mp.open("a") as f:
            for rec in added:
                f.write(json.dumps(rec) + "\n")
    results = [r for r in added if r.get("result")]
    return {"file": str(desk_path), "added": len(added), "skipped_duplicates": skipped, "rejected": rejected,
            "results_added": len(results),
            "pnl_mid_usd": round(sum(_num(r.get("pnl_mid_usd")) or 0.0 for r in results), 2),
            "pnl_natural_usd": round(sum(_num(r.get("pnl_natural_usd")) or 0.0 for r in results), 2)}

