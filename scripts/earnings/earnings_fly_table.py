"""Earnings replay: what an iron fly keeps, by wing width, exit bar and cost.

    PYTHONPATH=src python3 scripts/earnings/earnings_fly_table.py [derived.jsonl ...]
        [--cap 350] [--cost 0.07] [--json out.json]

Reads the derived replay records (default: the combined sample of 2026-11-11) and prices a
model fly at 1x, 1.5x and 2x the entry straddle on EVERY clean event, the same way
``vantage_trader/earnings/replay.py`` prices its 1x and 2x flies: real body prices, wings
from the body's implied stdev times a wing multiplier. The multiplier follows each record's
own batch: 1.0 for events collected by the lite method (no wing prints), the calibration
fitted on real wing prints for the others (interpolated between 1x and 2x).

Why this script exists (2026-11-16): the table of 2026-11-11 compared the 10:00 ET exit with
the 10:30 ET exit on different sets of events. Two or three events have no 10:00 print, and
one of them (FTNT, 2026-10-28) is the largest loss in the sample. So the 10:00 numbers left
the worst event out. Here every row says which events it holds:

  first   the first exit bar that has a price: 10:00 ET, else 10:30 ET. Every clean event.
  b1      10:00 ET only (events with a 10:00 price)
  b2      10:30 ET only
  paired  events that have both, and the difference between the two exits on the same events

``--cap`` adds the fly as the rules trade it: wings aimed at the multiple, stepped in until the
max loss fits the cap, never closer than 0.9x the straddle; an event that does not fit is
skipped. Costs are a share of the entry credit (the replay's 7% unless ``--cost`` says so).
Nothing here places orders.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from vantage_trader.earnings.replay import call_put  # noqa: E402

DEFAULT = [REPO / "state/earnings/replay/2026-11-11_batch2/combined_derived.jsonl"]
# wing / body implied-stdev multipliers fitted on real wing prints (combined_summary.json)
MULT = {1.0: {"entry": 1.008, "exit": 1.0068}, 2.0: {"entry": 1.0185, "exit": 1.0893}}
MIN_WIDTH = 0.9            # rules v1.13: never closer than 0.9x the straddle
WIDTHS = (1.0, 1.5, 2.0)


def mult(r: dict, m: float, leg: str) -> float:
    if (r.get("fly1") or {}).get("synthetic_strikes"):
        return 1.0                               # lite method: the engine priced these at 1.0
    a, b = MULT[1.0][leg], MULT[2.0][leg]
    return a + (min(max(m, 1.0), 2.0) - 1.0) * (b - a)


def fly(r: dict, m: float) -> dict | None:
    """Model fly with wings m x the entry straddle from the body. None when it cannot be priced."""
    se, s0, k, g0 = r.get("straddle_entry"), r.get("S_entry"), r.get("K"), r.get("sigma_pre")
    if not se or not s0 or not k or g0 is None:
        return None
    w = m * se
    cs, ps = k + w, k - w
    if ps <= 0:
        return None
    ge = g0 * mult(r, m, "entry")
    credit = se - call_put(s0, cs, ge)[0] - call_put(s0, ps, ge)[1]
    out = {"m": m, "width": w, "credit": credit, "max_loss": (w - credit) * 100.0}
    for x in ("b1", "b2"):
        sx, spot = r.get(f"straddle_{x}"), r.get(f"S_{x}")
        if sx is None or not spot:
            continue
        gx = (r.get(f"sigma_post_{x}") or 0.0) * mult(r, m, "exit")
        close = sx - call_put(spot, cs, gx)[0] - call_put(spot, ps, gx)[1]
        out[x] = (credit - min(max(close, 0.0), w)) * 100.0
    return out


def capped(r: dict, m: float, cap: float | None) -> dict | None:
    """The widest fly at or under m x the straddle whose max loss fits the cap (not under 0.9x)."""
    f = fly(r, m)
    if f is None:
        return None
    if cap is None or f["max_loss"] <= cap:
        return f
    lo = fly(r, MIN_WIDTH)
    if lo is None or lo["max_loss"] > cap:
        return None
    a, b = MIN_WIDTH, m                       # max loss grows with the width
    for _ in range(40):
        mid = 0.5 * (a + b)
        g = fly(r, mid)
        if g is not None and g["max_loss"] <= cap:
            a = mid
        else:
            b = mid
    return fly(r, a)


def stats(xs: list[float]) -> dict:
    n = len(xs)
    if n == 0:
        return {"n": 0}
    mean = sum(xs) / n
    sd = st.stdev(xs) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n > 1 else 0.0
    return {"n": n, "wins": sum(1 for x in xs if x > 0), "mean": round(mean, 1), "median": round(st.median(xs), 1),
            "sd": round(sd, 1), "se": round(se, 1), "t": round(mean / se, 2) if se else None,
            "worst": round(min(xs)), "best": round(max(xs))}


def table(flies: list[dict], cost: float) -> dict:
    """Rows by exit set for one list of priced flies (one fly per event)."""
    def net(f: dict, x: str) -> float:
        return f[x] - cost * f["credit"] * 100.0

    def first(f: dict) -> str | None:
        return "b1" if "b1" in f else ("b2" if "b2" in f else None)

    has_first = [f for f in flies if first(f)]
    both = [f for f in flies if "b1" in f and "b2" in f]
    credit = [f["credit"] * 100.0 for f in has_first]
    gross = [f[first(f)] for f in has_first]
    out = {
        "first": {"before_costs": stats(gross), "after_costs": stats([net(f, first(f)) for f in has_first])},
        "b1": {"before_costs": stats([f["b1"] for f in flies if "b1" in f]),
               "after_costs": stats([net(f, "b1") for f in flies if "b1" in f])},
        "b2": {"before_costs": stats([f["b2"] for f in flies if "b2" in f]),
               "after_costs": stats([net(f, "b2") for f in flies if "b2" in f])},
        "paired_b1_minus_b2": stats([f["b1"] - f["b2"] for f in both]),
        "avg_credit_usd": round(sum(credit) / len(credit), 1) if credit else None,
        "avg_max_loss_usd": round(sum(f["max_loss"] for f in has_first) / len(has_first), 1) if has_first else None,
        "avg_width_over_straddle": round(sum(f["m"] for f in has_first) / len(has_first), 2) if has_first else None,
    }
    if credit and sum(credit) > 0:
        # the cost, as a share of the credit, at which the average fly keeps nothing
        out["breakeven_cost_share"] = round(sum(gross) / sum(credit), 4)
        out["after_costs_by_share"] = {f"{c:.2f}": round(sum(g - c * k for g, k in zip(gross, credit)) / len(gross), 1)
                                       for c in (0.03, 0.05, 0.07, 0.09)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--cap", type=float, default=350.0)
    ap.add_argument("--cost", type=float, default=0.07)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    rows = []
    for f in (a.files or DEFAULT):
        rows += [json.loads(line) for line in Path(f).read_text().splitlines() if line.strip()]
    clean = [r for r in rows if r.get("status") == "ok" and r.get("clean")]
    out: dict = {"clean_events": len(clean), "cost_share": a.cost, "cap_usd": a.cap, "widths": {}, "capped": {}}

    ss = {x: [r[f"short_straddle_pnl_{x}_usd"] for r in clean if r.get(f"short_straddle_pnl_{x}_usd") is not None]
          for x in ("b1", "b2")}
    frac = {x: [r[f"short_straddle_pnl_{x}_usd"] / (r["straddle_entry"] * 100.0) for r in clean
                if r.get(f"short_straddle_pnl_{x}_usd") is not None and r.get("straddle_entry")] for x in ("b1", "b2")}
    first_frac = [(r.get("short_straddle_pnl_b1_usd") if r.get("short_straddle_pnl_b1_usd") is not None
                   else r.get("short_straddle_pnl_b2_usd")) / (r["straddle_entry"] * 100.0)
                  for r in clean if r.get("straddle_entry") and (r.get("short_straddle_pnl_b1_usd") is not None
                                                                  or r.get("short_straddle_pnl_b2_usd") is not None)]
    out["short_straddle"] = {"b1_usd": stats(ss["b1"]), "b2_usd": stats(ss["b2"]),
                             "b1_share_of_straddle": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in _fr(frac["b1"]).items()},
                             "b2_share_of_straddle": _fr(frac["b2"]), "first_share_of_straddle": _fr(first_frac)}

    for m in WIDTHS:
        out["widths"][str(m)] = table([f for f in (fly(r, m) for r in clean) if f], a.cost)
        out["capped"][str(m)] = table([f for f in (capped(r, m, a.cap) for r in clean) if f], a.cost)

    print(f"{len(clean)} clean events. Costs = {a.cost:.0%} of the entry credit. One contract a fly.")
    s = out["short_straddle"]["first_share_of_straddle"]
    print(f"short straddle, first exit bar: n={s['n']} wins={s['wins']} mean {s['mean']:+.3f} of the straddle (se {s['se']}, t {s['t']})")
    for label, key in (("every clean event, no cap", "widths"), (f"as traded: stepped in to a max loss of ${a.cap:.0f}", "capped")):
        print(f"\n== {label}")
        for m in WIDTHS:
            t = out[key][str(m)]
            f_, b1, b2, pd = t["first"], t["b1"], t["b2"], t["paired_b1_minus_b2"]
            print(f"wings {m}x: first exit n={f_['after_costs']['n']} wins {f_['before_costs']['wins']} "
                  f"before costs {f_['before_costs']['mean']:+} after {f_['after_costs']['mean']:+} "
                  f"(se {f_['after_costs']['se']}, t {f_['after_costs']['t']}, worst {f_['after_costs']['worst']}) | "
                  f"10:00 only n={b1['after_costs']['n']} {b1['after_costs']['mean']:+} | 10:30 only n={b2['after_costs']['n']} "
                  f"{b2['after_costs']['mean']:+} | paired 10:00 minus 10:30 {pd['mean']:+} (se {pd['se']}) | "
                  f"credit ${t['avg_credit_usd']} max loss ${t['avg_max_loss_usd']} width {t['avg_width_over_straddle']}x | "
                  f"breakeven cost {t.get('breakeven_cost_share')} | after costs at 3/5/7/9%: {t.get('after_costs_by_share')}")
    # the per-name cap, swept: the same aim, stepped in to each cap
    out["cap_sweep"] = {}
    print("\n== the per-name max-loss cap, swept (first exit bar, after costs)")
    for m in (1.5, 2.0):
        for cap in (250.0, 300.0, 350.0, 400.0, 500.0, None):
            t = table([f for f in (capped(r, m, cap) for r in clean) if f], a.cost)
            ac = t["first"]["after_costs"]
            key = f"{m}x_cap_{'none' if cap is None else int(cap)}"
            out["cap_sweep"][key] = {"n": ac["n"], "mean": ac["mean"], "se": ac["se"], "t": ac["t"], "worst": ac["worst"],
                                     "avg_max_loss_usd": t["avg_max_loss_usd"], "avg_width_over_straddle": t["avg_width_over_straddle"],
                                     "breakeven_cost_share": t.get("breakeven_cost_share")}
            print(f"aim {m}x, cap {'none' if cap is None else '$' + str(int(cap)):>5}: n={ac['n']:<3} after costs {ac['mean']:+6} "
                  f"(se {ac['se']}, t {ac['t']}) worst {ac['worst']:>6} | avg max loss ${t['avg_max_loss_usd']} width {t['avg_width_over_straddle']}x "
                  f"breakeven cost {t.get('breakeven_cost_share')}")
    # cross-check against the engine's own stored 1x and 2x model flies
    eng = {}
    for n in ("1", "2"):
        for x in ("b1", "b2"):
            v = [(r[f"fly{n}"]["model"][f"pnl_{x}_usd"] - a.cost * r[f"fly{n}"]["model"]["credit"] * 100.0) for r in clean
                 if ((r.get(f"fly{n}") or {}).get("model") or {}).get(f"pnl_{x}_usd") is not None]
            eng[f"fly{n}_{x}"] = {"n": len(v), "mean": round(sum(v) / len(v), 2)}
    out["engine_cross_check"] = eng
    print("\nengine's stored flies after costs (listed strikes in batch 1):", eng)
    if a.json:
        a.json.write_text(json.dumps(out, indent=1))


def _fr(xs: list[float]) -> dict:
    n = len(xs)
    if n < 2:
        return {"n": n}
    mean = sum(xs) / n
    se = st.stdev(xs) / math.sqrt(n)
    return {"n": n, "wins": sum(1 for x in xs if x > 0), "mean": round(mean, 4), "se": round(se, 4), "t": round(mean / se, 2)}


if __name__ == "__main__":
    main()
