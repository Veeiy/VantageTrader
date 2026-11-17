"""Replay of the overnight iron fly: sold late on session P, bought back on the morning of D.

Usage:
    python3 scripts/earnings/overnight_replay.py [folder] [--cost 8] [--json out.json]

``folder`` (default state/earnings/daytrade/overnight) holds raw_<SYM>.jsonl written by the
agents (brief_overnight.txt). The stock's half-hour bars come from the same-day replay folder
(state/earnings/daytrade/replay/equity_30min.json).

Why this trade is tested: delta-hedged option returns are negative overnight and slightly
positive during the day (Muravyev and Ni, Journal of Financial Economics 2020), and this
project's own replay of 290 same-day flies found nothing to earn intraday. If option sellers
are paid anywhere on a one-day horizon, it is from the close to the next open.

Entry: the 12:30 Pacific prices on P (body call + body put - wings). Exit: the bar starts 06:30,
07:00, 07:30 and 08:00 Pacific on D. A fly is worth between 0 and its width, so the cost to
close is clipped to that range. Marks whose body prices do not fit the stock price (put-call
parity) are skipped. ``--cost`` is the round-trip cost per fly in dollars (eight single-leg
orders). Nothing here places an order.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

MORNING = ["06:30", "07:00", "07:30", "08:00"]
TOL = {"SPY": 0.35, "QQQ": 0.35, "IWM": 0.15}
COST = {"SPY": 8.0, "QQQ": 8.0, "IWM": 5.0}


def stats(vals: list[float]) -> dict:
    n = len(vals)
    if not n:
        return {"n": 0}
    m = st.mean(vals)
    se = st.stdev(vals) / n ** 0.5 if n > 1 else None
    return {"n": n, "mean": round(m, 1), "median": round(st.median(vals), 1), "se": None if se is None else round(se, 1),
            "t": None if not se else round(m / se, 2), "win_rate": round(sum(v > 0 for v in vals) / n, 3),
            "sd": round(st.pstdev(vals), 1) if n > 1 else 0.0, "total": round(sum(vals)), "worst": round(min(vals)),
            "best": round(max(vals))}


def build(folder: Path, eq: dict) -> list[dict]:
    out = []
    for p in sorted(folder.glob("raw_*.jsonl")):
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("error") or "entry" not in r:
                continue
            sym, d, pday, k, w = r["symbol"], r["date"], r["entry_date"], float(r["K"]), float(r["W"])
            e = r["entry"]
            try:
                credit = e["C"][0] + e["P"][0] - e["WC"][0] - e["WP"][0]
                straddle = e["C"][0] + e["P"][0]
            except TypeError:
                continue
            spot_e = eq[sym][pday]["12:30"]["o"]
            tol = TOL.get(sym, max(0.08, 0.0005 * spot_e))
            entry_ok = abs((e["C"][0] - e["P"][0]) - (spot_e - k)) <= tol
            marks, good, spots = [], [], []
            for i, t in enumerate(MORNING):
                m = r["morning_open"]
                vals = [m[leg][i] if i < len(m[leg]) else None for leg in ("C", "P", "WC", "WP")]
                bar = eq[sym][d].get(t)
                if any(v is None for v in vals) or bar is None:
                    marks.append(None), good.append(False), spots.append(None)
                    continue
                c_, p_, wc, wp = vals
                marks.append(min(max(c_ + p_ - wc - wp, 0.0), w))
                good.append(abs((c_ - p_) - (bar["o"] - k)) <= tol)
                spots.append(bar["o"])
            out.append({"symbol": sym, "date": d, "entry_date": pday, "K": k, "width": w, "credit": credit,
                        "straddle": straddle, "straddle_pct": straddle / spot_e, "max_loss_usd": (w - credit) * 100.0,
                        "valid": 0 < credit <= 0.85 * w, "entry_ok": entry_ok, "marks": marks, "good": good,
                        "gap": None if spots[0] is None else spots[0] / eq[sym][pday]["12:30"]["c"] - 1.0,
                        "straddle_morning": [None if r["morning_open"]["C"][i] is None or r["morning_open"]["P"][i] is None
                                             else r["morning_open"]["C"][i] + r["morning_open"]["P"][i]
                                             for i in range(len(MORNING))]})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default="state/earnings/daytrade/overnight")
    ap.add_argument("--equity", default="state/earnings/daytrade/replay/equity_30min.json")
    ap.add_argument("--cost", type=float, default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    eq = json.loads(Path(a.equity).read_text())
    every = build(Path(a.folder), eq)
    flies = [f for f in every if f["valid"] and f["entry_ok"]]
    if not flies:
        print("no usable items", file=sys.stderr)
        return 1
    out: dict = {"items": len(every), "usable": len(flies), "exits": {}}
    print(f"{len(every)} items, {len(flies)} with clean entry prints; "
          f"credit/width mean {st.mean(f['credit'] / f['width'] for f in flies):.3f}; "
          f"max loss mean ${st.mean(f['max_loss_usd'] for f in flies):.0f}; "
          f"straddle at entry {100 * st.mean(f['straddle_pct'] for f in flies):.2f}% of the price")
    for i, t in enumerate(MORNING):
        gross = [(f["credit"] - f["marks"][i]) * 100.0 for f in flies if f["good"][i]]
        net = [(f["credit"] - f["marks"][i]) * 100.0 - (COST.get(f["symbol"], 8.0) if a.cost is None else a.cost)
               for f in flies if f["good"][i]]
        sg, sn = stats(gross), stats(net)
        out["exits"][t] = {"before_costs": sg, "after_costs": sn}
        if sg["n"]:
            print(f"buy back {t} PT: n={sg['n']:<3} before costs mean {sg['mean']:>6} (se {sg['se']}, t {sg['t']}) win {sg['win_rate']*100:.0f}%"
                  f" | after costs mean {sn['mean']:>6} t {sn['t']} worst {sn['worst']} best {sn['best']}")
    # how much of the body straddle is gone by the morning, in the stock's absence of news
    decay = [1.0 - f["straddle_morning"][1] / f["straddle"] for f in flies if f["good"][1] and f["straddle_morning"][1]]
    if decay:
        out["straddle_change_to_0700"] = {"mean": round(st.mean(decay), 3), "median": round(st.median(decay), 3)}
        print(f"body straddle from 12:30 PT to 07:00 PT next morning: mean change {-100 * st.mean(decay):+.1f}%, "
              f"median {-100 * st.median(decay):+.1f}% (it is not centered any more after a gap)")
    small = [f for f in flies if f["gap"] is not None and abs(f["gap"]) < 0.005 and f["good"][1]]
    big = [f for f in flies if f["gap"] is not None and abs(f["gap"]) >= 0.005 and f["good"][1]]
    for label, sub in (("overnight move under 0.5%", small), ("overnight move 0.5% or more", big)):
        s = stats([(f["credit"] - f["marks"][1]) * 100.0 for f in sub])
        out.setdefault("by_gap", {})[label] = s
        if s["n"]:
            print(f"  {label}: n={s['n']} before costs mean {s['mean']} win {s['win_rate']*100:.0f}% worst {s['worst']}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
