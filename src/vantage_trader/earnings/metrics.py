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

RECORDS = {"entry", "adjust", "exit", "paper", "shadow_exit"}  # shadow_exit: a later mark of a closed fly (exit timing, 2026-11-18)
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


def round_trip_cost(entry: dict[str, Any] | None, exit_: dict[str, Any] | None) -> float | None:
    """Cost against mid of one closed trade, as a share of its entry credit (fees left out).

    Entry: ``fill_vs_mid`` = fill / mid, so the credit given up is fill * (1 / fvm - 1).
    Exit: ``fill_vs_mid`` = mid / fill, so the debit overpaid is fill * (1 - fvm).
    A fill better than mid counts as a negative cost. None when a number is missing.
    The earnings replay assumes 7% (``docs/earnings/PLAN.md``, "Costs").
    """
    e, x = _block(entry or {}, "execution"), _block(exit_ or {}, "execution")
    credit, fe = _num(e.get("fill_credit")), _num(e.get("fill_vs_mid"))
    debit, fx = _num(x.get("fill_debit")), _num(x.get("fill_vs_mid"))
    if fx is None and debit:
        # Exits recorded since 2026-11-17 carry the mid at the read, not the ratio (P055 heal).
        mid = _num(x.get("close_cost_mid_at_read"))
        fx = mid / debit if mid is not None else None
    if credit is None or fe is None or debit is None or fx is None or credit <= 0 or fe <= 0:
        return None
    return round((credit * (1.0 / fe - 1.0) + debit * (1.0 - fx)) / credit, 4)


def _cost_stats(pairs: list[tuple[dict[str, Any] | None, dict[str, Any]]]) -> dict[str, Any]:
    vals = [c for c in (round_trip_cost(e, x) for e, x in pairs) if c is not None]
    return {"n": len(vals), "avg_share_of_credit": _avg(vals),
            "min": min(vals) if vals else None, "max": max(vals) if vals else None}


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
            "round_trip_cost": round_trip_cost(e, x) if x else None,
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
        # cost against mid of a whole round trip, as a share of the entry credit
        "round_trip_cost": {
            "all": _cost_stats(closed),
            "earnings": _cost_stats([(e, x) for e, x in closed if (e or {}).get("kind") == "earnings"]),
        },
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


def _paper_reject_reason(rec: Any) -> str | None:
    """Why a desk line is not taken into the dataset; None when it is good."""
    if not isinstance(rec, dict):
        return "not an object"
    if rec.get("record") != "paper":
        return "record is not 'paper'"
    if rec.get("live") is not False:
        return "live must be false"
    if not isinstance(rec.get("trade_id"), str) or not rec["trade_id"].strip():
        return "trade_id missing"
    if not isinstance(rec.get("symbol"), str) or not rec["symbol"].strip():
        return "symbol missing"
    if rec["symbol"].strip().upper() in PAPER_NEVER:
        return "symbol is never traded, on paper either"
    if not isinstance(rec.get("ts"), str) or not rec["ts"].strip():
        return "ts missing"
    if any(k in rec and _num(rec[k]) is None for k in ("pnl_mid_usd", "pnl_natural_usd")):
        return "pnl fields must be numbers"
    return None


def _is_paper_opening(rec: dict[str, Any]) -> bool:
    return (rec.get("record") == "paper" and not rec.get("result") and "mark" not in rec
            and _num(rec.get("max_loss_usd")) is not None)


def paper_floors(opening: dict[str, Any] | None) -> tuple[float, float] | None:
    """The worst a paper structure can do in dollars, at the mid and at the natural.

    ``max_loss_usd`` is the width less the mid credit. The natural credit is smaller, so the
    natural floor is lower by the difference (``max_loss_natural_usd`` when the record has it).
    """
    ml = _num((opening or {}).get("max_loss_usd"))
    if ml is None or ml <= 0:
        return None
    nat = _num(opening.get("max_loss_natural_usd"))
    if nat is None:
        cm, cn = _num(opening.get("credit_mid")), _num(opening.get("credit_natural"))
        qty = _num(opening.get("quantity")) or 1.0
        nat = ml + (cm - cn) * 100 * qty if cm is not None and cn is not None and cm >= cn else ml
    return -ml, -max(nat, ml)


PAPER_PNL_FIELDS = ("pnl_mid_usd", "pnl_natural_usd")


def cap_paper_result(rec: dict[str, Any], opening: dict[str, Any] | None) -> list[str]:
    """Floor a paper result at its structure's max loss (P094, 2026-11-25).

    Deep in-the-money legs quote wide at the mark, and a result priced from those quotes can
    read worse than the fly can lose (AMD 2026-11-25: -428.50 against a max loss of 373.50).
    The quoted figure is kept under ``<field>_quoted``; the names of the capped fields are
    returned and written to ``capped_at_max_loss``.
    """
    floors = paper_floors(opening if opening is not None else rec)
    if floors is None:
        return []
    capped: list[str] = []
    for field, floor in zip(PAPER_PNL_FIELDS, floors):
        v = _num(rec.get(field))
        if v is not None and v < floor - 0.005:
            rec[field + "_quoted"] = v
            rec[field] = round(floor, 2)
            capped.append(field)
    if capped:
        rec["capped_at_max_loss"] = capped
        if "pnl_mid_usd" in capped and "pnl_pct_of_max_loss" in rec:
            rec["pnl_pct_of_max_loss"] = -1.0
    return capped


def import_paper(desk_path: str | Path, metrics_path: str | Path) -> dict[str, Any]:
    """Append the records a read-only paper-desk agent wrote to the live metrics dataset.

    The desk writes one JSON object per line. Only ``paper`` records with ``live`` false are
    taken. A line already in the dataset (same trade_id, ts and stage) is skipped, so the
    import can be run again. Bad lines are reported, never appended. A result worse than its
    structure's max loss is floored there (``cap_paper_result``).
    """
    dp = Path(desk_path)
    if not dp.exists():
        raise EngineInputError(f"paper desk file not found: {desk_path}")
    existing = read_metrics(metrics_path)
    have = {_paper_key(r) for r in existing if r.get("record") == "paper"}
    openings = {r.get("trade_id"): r for r in existing if _is_paper_opening(r)}
    capped = 0
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
        why = _paper_reject_reason(rec)
        if why:
            rejected.append({"line": n, "reason": why})
            continue
        key = _paper_key(rec)
        if key in have:
            skipped += 1
            continue
        have.add(key)
        if _is_paper_opening(rec):
            openings[rec["trade_id"]] = rec
        elif rec.get("result") and cap_paper_result(rec, openings.get(rec["trade_id"])):
            capped += 1
        added.append(rec)
    if added:
        mp = Path(metrics_path)
        mp.parent.mkdir(parents=True, exist_ok=True)
        with mp.open("a") as f:
            for rec in added:
                f.write(json.dumps(rec) + "\n")
    results = [r for r in added if r.get("result")]
    return {"file": str(desk_path), "added": len(added), "skipped_duplicates": skipped, "rejected": rejected,
            "results_added": len(results), "results_capped_at_max_loss": capped,
            "pnl_mid_usd": round(sum(_num(r.get("pnl_mid_usd")) or 0.0 for r in results), 2),
            "pnl_natural_usd": round(sum(_num(r.get("pnl_natural_usd")) or 0.0 for r in results), 2)}

