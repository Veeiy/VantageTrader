"""Cap-level test for the same-day pilot (owner, 2026-11-16: "$150 is an extremely small cap.
Can you test it with different cap levels? Could be a buying power issue.").

Usage:
    PYTHONPATH=src python3 scripts/earnings/intraday_caps.py [folder] [--exit 11:00] [--json out.json]

Reads the replay folder that scripts/earnings/intraday_replay.py scores (90 same-day iron flies,
SPY, QQQ, IWM, 30 sessions) and answers three questions with those real prices:

  1. PER-TRADE CAP. For a max-loss cap C, each name is sized at floor(C / the fly's max loss)
     contracts (none when one contract is above C). What did a day of that look like: mean, swing,
     worst day, total, and the buying power it needs.
  2. BUDGET (the pilot's cumulative stop). Trading the replay in date order, and in 5,000 random
     orders of 20 trades, how often does a budget B stop the pilot by bad luck alone, and what is
     the result when it does not.
  3. WIDTH. The body straddle with no wings at all is the limit of ever wider wings (it is not a
     trade this account may place: undefined risk). If even that has no edge, a wider fly and a
     bigger cap buy swing, not profit.

Nothing here places an order.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import intraday_replay as ir  # noqa: E402

CAPS = [80, 150, 200, 300, 400, 600]
BUDGETS = [150, 300, 500, 800, None]


def stats(vals: list[float]) -> dict:
    n = len(vals)
    if not n:
        return {"n": 0}
    m, sd = st.mean(vals), (st.pstdev(vals) if n > 1 else 0.0)
    se = st.stdev(vals) / n ** 0.5 if n > 1 else None
    return {"n": n, "mean": round(m, 1), "sd": round(sd, 1), "t": None if not se else round(m / se, 2),
            "win_rate": round(sum(v > 0 for v in vals) / n, 3), "total": round(sum(vals)),
            "worst": round(min(vals)), "best": round(max(vals))}


def drawdown(vals: list[float]) -> float:
    peak = run = 0.0
    dd = 0.0
    for v in vals:
        run += v
        peak = max(peak, run)
        dd = min(dd, run - peak)
    return round(dd)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default="state/earnings/daytrade/replay")
    ap.add_argument("--exit", default="11:00")
    ap.add_argument("--json", default=None)
    ap.add_argument("--seed", type=int, default=20261116)
    a = ap.parse_args(argv)
    eq, rows = ir.load(Path(a.folder))
    flies = [f for f in ir.build(eq, rows) if f["valid"] and f["entry_good"]]
    ti = ir.TIMES.index(a.exit)
    for f in flies:
        f["pnl1"] = ir.pnl_at(f, ti, None)                # one contract, after costs
        f["cost1"] = ir.cost_of(f, None)
    flies = [f for f in flies if f["pnl1"] is not None]
    days = sorted({f["date"] for f in flies})
    out: dict = {"exit": a.exit, "flies": len(flies), "days": len(days)}
    print(f"{len(flies)} flies, {len(days)} sessions, exit {a.exit} PT, after costs (SPY 8, QQQ 8, IWM 5 a contract)\n")

    # ---- 1. per-trade cap, by name
    print("== 1. per-trade max-loss cap: contracts = floor(cap / max loss of one fly) ==")
    print(f"{'cap':>5} {'name':<5} {'days traded':>11} {'avg contracts':>13} {'avg risk':>9} {'mean/day':>9} {'sd':>7} {'t':>6} "
          f"{'worst day':>9} {'total':>7} {'max drawdown':>12} {'buying power':>12}")
    out["per_trade_cap"] = {}
    for cap in CAPS:
        for sym in sorted({f["symbol"] for f in flies}):
            vals, ns, risks, bps = [], [], [], []
            for f in sorted((f for f in flies if f["symbol"] == sym), key=lambda f: f["date"]):
                n = int(cap // f["max_loss_usd"])
                if n < 1:
                    continue
                vals.append(n * f["pnl1"])
                ns.append(n)
                risks.append(n * f["max_loss_usd"])
                # collateral less credit for n contracts, plus one in-the-money short at the wing (v1.9)
                bps.append(n * f["max_loss_usd"] + 1.1 * f["width"] * 100.0)
            s = stats(vals)
            row = dict(s, avg_contracts=round(st.mean(ns), 1) if ns else 0, avg_risk=round(st.mean(risks)) if risks else 0,
                       max_drawdown=drawdown(vals), buying_power_peak=round(max(bps)) if bps else 0)
            out["per_trade_cap"][f"{cap}:{sym}"] = row
            if s["n"]:
                print(f"{cap:>5} {sym:<5} {s['n']:>11} {row['avg_contracts']:>13} {row['avg_risk']:>9} {s['mean']:>9} {s['sd']:>7} "
                      f"{str(s['t']):>6} {s['worst']:>9} {s['total']:>7} {row['max_drawdown']:>12} {row['buying_power_peak']:>12}")
            else:
                print(f"{cap:>5} {sym:<5} {'0':>11}   (one contract is above the cap on every day)")
        print()

    # ---- 2. budget: in date order, then by resampling
    def one_a_day(cap: float, order: str) -> list[float]:
        """One fly a day: the name whose sized risk is closest to the cap ('fill') or IWM only ('iwm')."""
        seq = []
        for d in days:
            todays = [f for f in flies if f["date"] == d]
            best = None
            for f in todays:
                n = int(cap // f["max_loss_usd"])
                if n < 1 or (order == "iwm" and f["symbol"] != "IWM"):
                    continue
                risk = n * f["max_loss_usd"]
                if best is None or risk > best[0]:
                    best = (risk, n * f["pnl1"])
            if best:
                seq.append(best[1])
        return seq

    rng = random.Random(a.seed)
    print("== 2. budget (cumulative stop): one fly a day, sized to the cap ==")
    print(f"{'cap':>5} {'pick':<5} {'budget':>7} | date order: {'trades':>6} {'stopped':>8} {'result':>7} | 5,000 random 20-trade runs: "
          f"{'stopped':>8} {'mean':>6} {'p05':>6} {'p50':>6} {'p95':>6}")
    out["budget"] = {}
    for cap, pick in ((80, "iwm"), (150, "fill"), (200, "fill"), (300, "fill"), (400, "fill")):
        seq = one_a_day(cap, pick)
        for b in BUDGETS:
            run, n, stopped = 0.0, 0, False
            for v in seq:
                run += v
                n += 1
                if b is not None and run <= -b:
                    stopped = True
                    break
            finals, stops = [], 0
            for _ in range(5000):
                r = 0.0
                hit = False
                for v in rng.choices(seq, k=20):
                    r += v
                    if b is not None and r <= -b:
                        hit = True
                        break
                stops += hit
                finals.append(r)
            finals.sort()
            row = {"date_order": {"trades": n, "stopped": stopped, "result": round(run)},
                   "resampled": {"p_stopped": round(stops / 5000, 3), "mean": round(st.mean(finals)),
                                 "p05": round(finals[250]), "p50": round(finals[2500]), "p95": round(finals[4750])}}
            out["budget"][f"{cap}:{pick}:{b}"] = row
            print(f"{cap:>5} {pick:<5} {str(b):>7} |             {n:>6} {str(stopped):>8} {round(run):>7} |"
                  f"                              {row['resampled']['p_stopped']*100:>7.1f}% {row['resampled']['mean']:>6} "
                  f"{row['resampled']['p05']:>6} {row['resampled']['p50']:>6} {row['resampled']['p95']:>6}")
        print()

    # ---- 3. width: the body straddle with no wings (the limit of ever wider wings)
    print("== 3. width: the body straddle alone (not tradable here: undefined risk) against the 1x fly ==")
    raw = {(r["symbol"], r["date"]): r for r in rows}
    out["width"] = {}
    for sym in sorted({f["symbol"] for f in flies}) + ["ALL"]:
        sv, fv = [], []
        for f in flies:
            if sym != "ALL" and f["symbol"] != sym:
                continue
            r = raw[(f["symbol"], f["date"])]
            j = ir.usable_mark(f, ti)
            c0, p0 = r["open"]["C"][0], r["open"]["P"][0]
            cj, pj = r["open"]["C"][j], r["open"]["P"][j]
            sv.append(((c0 + p0) - (cj + pj)) * 100.0 - f["cost1"] / 2.0)      # four orders, not eight
            fv.append(f["pnl1"])
        s, fl = stats(sv), stats(fv)
        out["width"][sym] = {"straddle": s, "fly_1x": fl}
        print(f"{sym:<4} straddle: mean {s['mean']:>7} sd {s['sd']:>7} t {str(s['t']):>6} win {s['win_rate']*100:>5.1f}% worst {s['worst']:>6}"
              f"   | 1x fly: mean {fl['mean']:>6} sd {fl['sd']:>6} worst {fl['worst']:>5}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
