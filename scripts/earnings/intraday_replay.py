"""Replay of same-day iron flies from 30-minute option bars (proposal P017, rules v1.15).

Usage:
    PYTHONPATH=src python3 scripts/earnings/intraday_replay.py [folder] [--cost 12] [--json out.json]

``folder`` (default state/earnings/daytrade/replay) holds
    equity_30min.json   {"SYM": {"YYYY-MM-DD": {"HH:MM" (Pacific bar start): {"o","c","h","l"}}}}
    raw_<SYM>.jsonl     one line per session, written by the replay agents:
        {"symbol","date","K","spot_0730","straddle_0730","W","strikes":{"WC","WP"},
         "times_pt":[11 bar starts 07:30..12:30],
         "open":{"C":[..],"P":[..],"WC":[..],"WP":[..]},      # price at each bar start
         "last_close":{...}, "interp":{"C":[idx],...}, "parity_max": float}

The fly is sold at the 07:30 Pacific prices (body call + body put - wing call - wing put) and
bought back at a later bar start. Prices are prints at bar starts, not quotes: ``--cost`` is
the round-trip dollar cost per fly charged on top (eight single-leg orders on penny-wide
contracts; default 12).

What it reports
    * the result of a plain time exit at every bar start;
    * take-profit and stop rules checked at bar starts (a 30-minute grid: a real stop fills
      worse than the level, and a real take profit can trigger between bars);
    * results split by the premium ratio known at entry
      (straddle / spot) / mean |move from 07:30 to the close| over the 10 sessions before,
      by the size of the move before entry, and by name;
    * day-clustered statistics: the three names move together, so the unit is the day.

Nothing here places an order. The numbers feed config/earnings.yaml (intraday_* keys) and are
re-run as sessions accumulate.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path

TIMES = ["07:30", "08:00", "08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30"]
PARITY_TOL = {"SPY": 0.30, "QQQ": 0.30, "IWM": 0.12}     # dollars; see build()
MAX_CREDIT_OVER_WIDTH = 0.85
COST = {"SPY": 8.0, "QQQ": 8.0, "IWM": 5.0}             # round trip per fly: eight single-leg orders, penny-wide


def load(folder: Path) -> tuple[dict, list[dict]]:
    eq = json.loads((folder / "equity_30min.json").read_text())
    rows: list[dict] = []
    for p in sorted(folder.glob("raw_*.jsonl")):
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("error") or "open" not in r:
                continue
            rows.append(r)
    return eq, rows


def _val(r: dict, leg: str, i: int) -> float | None:
    v = r["open"][leg][i] if i < len(r["open"][leg]) else None
    return None if v is None else float(v)


def fly_cost(r: dict, i: int, bounded: bool = True) -> float | None:
    """Price of the fly (what it costs to buy back) at bar i; None when a leg is missing.

    A fly is worth between 0 and its wing width. Deep in-the-money legs trade rarely, so their
    bar-start prints can be stale and push the raw sum outside that range (IWM 2026-10-16:
    1.63 on a 1-wide fly). ``bounded`` clips it to [0, width]."""
    vals = [_val(r, leg, i) for leg in ("C", "P", "WC", "WP")]
    if any(v is None for v in vals):
        return None
    c, p, wc, wp = vals
    raw = c + p - wc - wp
    return min(max(raw, 0.0), float(r["W"])) if bounded else raw


def implied_spot(r: dict, i: int) -> float | None:
    """Stock price implied by the body call and put (parity on expiration day). The stock's
    own 30-minute bars are thin at some bar starts (SPY 2026-10-20 08:00), the options are not."""
    c, p = _val(r, "C", i), _val(r, "P", i)
    return None if c is None or p is None else float(r["K"]) + c - p


def build(eq: dict, rows: list[dict], lookback: int = 10) -> list[dict]:
    out = []
    for r in rows:
        sym, day = r["symbol"], r["date"]
        days = list(eq[sym].keys())
        if day not in days:
            continue
        di = days.index(day)
        bars = eq[sym][day]
        spot = bars["07:30"]["o"]
        k = float(r["K"])
        credit = fly_cost(r, 0, bounded=False)
        if credit is None:
            continue
        width = float(r["W"])
        straddle = _val(r, "C", 0) + _val(r, "P", 0)
        prior = days[max(0, di - lookback):di]
        moves_close = [abs(eq[sym][d]["12:30"]["c"] / eq[sym][d]["07:30"]["o"] - 1.0) for d in prior]
        moves_1230 = [abs(eq[sym][d]["12:30"]["o"] / eq[sym][d]["07:30"]["o"] - 1.0) for d in prior]
        prev_close = eq[sym][days[di - 1]]["12:30"]["c"] if di > 0 else None
        path = [fly_cost(r, i) for i in range(len(TIMES))]
        # Data quality. A body call minus a body put must equal stock minus strike on expiration
        # day. Where the bar-start prints disagree with the stock's bar by more than the tolerance
        # the prints are not from the same moment and that mark is not used.
        tol = PARITY_TOL.get(sym, 0.30)
        good = []
        for i, tm in enumerate(TIMES):
            c_, p_ = _val(r, "C", i), _val(r, "P", i)
            if path[i] is None or c_ is None or p_ is None:
                good.append(False)
                continue
            good.append(abs((c_ - p_) - (bars[tm]["o"] - k)) <= tol)
        interp = r.get("interp", {})
        n_interp = sum(len(interp.get(leg, [])) for leg in ("C", "P", "WC", "WP"))
        out.append({
            "symbol": sym, "date": day, "K": k, "spot": spot, "width": width,
            "straddle": straddle, "straddle_pct": straddle / spot,
            "credit": credit, "credit_over_width": credit / width if width else None,
            "max_loss_usd": (width - credit) * 100.0,
            # a 1x fly collects 0.52 to 0.78 of its width in this data; a credit at the full width
            # (IWM 2026-11-12) is a bad print, not a free trade
            "valid": 0 < credit <= MAX_CREDIT_OVER_WIDTH * width,
            "premium_ratio": (straddle / spot) / st.mean(moves_close) if len(moves_close) >= lookback else None,
            "premium_ratio_1230": (straddle / spot) / st.mean(moves_1230) if len(moves_1230) >= lookback else None,
            "premium_ratio_median": (straddle / spot) / st.median(moves_close) if len(moves_close) >= lookback else None,
            "gap": spot / prev_close - 1.0 if prev_close else None,
            "drive": spot / bars["06:30"]["o"] - 1.0,
            "range_pre": (max(bars[t]["h"] for t in ("06:30", "07:00")) - min(bars[t]["l"] for t in ("06:30", "07:00"))) / spot,
            "off_center": (spot - k) / straddle if straddle else None,
            "path": path, "good": good, "entry_good": good[0],
            "spots": [implied_spot(r, i) for i in range(len(TIMES))],
            "clipped": sum(1 for i in range(len(TIMES))
                           if fly_cost(r, i) is not None and abs(fly_cost(r, i) - fly_cost(r, i, bounded=False)) > 1e-9),
            "n_interp": n_interp, "parity_max": r.get("parity_max"),
        })
    return out


def cost_of(f: dict, cost: float | None) -> float:
    return COST.get(f["symbol"], 8.0) if cost is None else cost


def usable_mark(f: dict, i: int, strict: bool = False) -> int | None:
    """Bar i when its prints are usable, else the nearest usable bar (the next one first)."""
    n = len(f["path"])
    if f["good"][i]:
        return i
    if strict:
        return None
    for d in (1, -1, 2, -2):
        j = i + d
        if 1 <= j < n and f["good"][j]:
            return j
    return None


def pnl_at(f: dict, i: int, cost: float | None) -> float | None:
    j = usable_mark(f, i)
    if j is None:
        return None
    return (f["credit"] - f["path"][j]) * 100.0 - cost_of(f, cost)


def run_rule(f: dict, cost: float, t_exit: int, tp: float | None = None, stop: float | None = None,
             stop_slip: float = 0.0) -> tuple[float, str, int] | None:
    """Walk the bar starts after entry. tp: close when the profit before costs is at least
    tp x credit. stop: close when the loss before costs is at least stop x max loss.
    stop_slip: extra dollars lost on a stop (it fills past the level). Returns (pnl, why, bar)."""
    credit, ml = f["credit"], f["max_loss_usd"]
    cost = cost_of(f, cost)
    last = None
    for i in range(1, t_exit + 1):
        cc = f["path"][i]
        if cc is None or not f["good"][i]:
            continue
        gross = (credit - cc) * 100.0
        last = (gross - cost, "time", i)
        if tp is not None and gross >= tp * credit * 100.0:
            return gross - cost, "take_profit", i
        if stop is not None and -gross >= stop * ml:
            return gross - cost - stop_slip, "stop", i
    return last


def stats(vals: list[float]) -> dict:
    n = len(vals)
    if n == 0:
        return {"n": 0}
    m = st.mean(vals)
    sd = st.pstdev(vals) if n > 1 else 0.0
    se = (st.stdev(vals) / math.sqrt(n)) if n > 1 else None
    return {"n": n, "mean": round(m, 1), "median": round(st.median(vals), 1),
            "win_rate": round(sum(v > 0 for v in vals) / n, 3), "sd": round(sd, 1),
            "se": None if se is None else round(se, 1), "t": None if not se else round(m / se, 2),
            "total": round(sum(vals), 0), "worst": round(min(vals), 0), "best": round(max(vals), 0)}


def by_day(flies: list[dict], vals: list[float | None]) -> list[float]:
    """Mean result per day across the names traded that day (the day is the independent unit)."""
    d: dict[str, list[float]] = {}
    for f, v in zip(flies, vals):
        if v is not None:
            d.setdefault(f["date"], []).append(v)
    return [st.mean(x) for _, x in sorted(d.items())]


def line(label: str, s: dict) -> str:
    if not s.get("n"):
        return f"{label:<34} n=0"
    return (f"{label:<34} n={s['n']:<3} mean {s['mean']:>7.1f}  median {s['median']:>7.1f}  win {s['win_rate']*100:>5.1f}%"
            f"  sd {s['sd']:>6.1f}  t {s['t'] if s['t'] is not None else '-':>5}  total {s['total']:>7.0f}  worst {s['worst']:>6.0f}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default="state/earnings/daytrade/replay")
    ap.add_argument("--cost", type=float, default=None,
                    help="round-trip cost per fly; default: SPY 8, QQQ 8, IWM 5")
    ap.add_argument("--keep-bad-entries", action="store_true",
                    help="keep sessions whose 07:30 prints fail the parity check")
    ap.add_argument("--names", default=None, help="comma-separated subset of names")
    ap.add_argument("--from-date", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--max-loss", type=float, default=None, help="only flies with max loss at or under this")
    a = ap.parse_args(argv)
    eq, rows = load(Path(a.folder))
    every = [f for f in build(eq, rows) if f["valid"]]
    flies = every if a.keep_bad_entries else [f for f in every if f["entry_good"]]
    if a.names:
        flies = [f for f in flies if f["symbol"] in a.names.split(",")]
    if a.from_date:
        flies = [f for f in flies if f["date"] >= a.from_date]
    dropped = len(every) - len([f for f in every if f["entry_good"]])
    if a.max_loss is not None:
        flies = [f for f in flies if f["max_loss_usd"] <= a.max_loss]
    if not flies:
        print("no usable sessions", file=sys.stderr)
        return 1
    cost = a.cost
    out: dict = {"cost_usd": cost, "n_flies": len(flies), "n_days": len({f["date"] for f in flies}),
                 "names": sorted({f["symbol"] for f in flies})}
    out["entries_failing_parity"] = dropped
    cost_txt = "SPY 8, QQQ 8, IWM 5" if cost is None else f"{cost:.0f}"
    marks = sum(len(f["good"]) - 1 for f in flies)
    bad = sum(1 for f in flies for g in f["good"][1:] if not g)
    print(f"{len(flies)} flies, {out['n_days']} days, names {out['names']}, round-trip cost ${cost_txt} a fly; "
          f"{dropped} session(s) fail the parity check at entry ({'kept' if a.keep_bad_entries else 'dropped'}); "
          f"{bad} of {marks} later marks unusable")
    print(f"credit/width mean {st.mean(f['credit_over_width'] for f in flies):.3f}; "
          f"max loss mean ${st.mean(f['max_loss_usd'] for f in flies):.0f}; "
          f"straddle% mean {100 * st.mean(f['straddle_pct'] for f in flies):.3f}")

    print("\n== time exit at each bar start (all flies; then per-day means) ==")
    out["time_exit"] = {}
    for i in range(1, len(TIMES)):
        vals = [pnl_at(f, i, cost) for f in flies]
        v = [x for x in vals if x is not None]
        s, sd = stats(v), stats(by_day(flies, vals))
        out["time_exit"][TIMES[i]] = {"flies": s, "days": sd}
        print(line(f"exit {TIMES[i]}", s) + f"   | per day: mean {sd['mean']:>6.1f} t {sd['t']}")

    print("\n== by name, time exits ==")
    out["by_name"] = {}
    for sym in out["names"]:
        sub = [f for f in flies if f["symbol"] == sym]
        out["by_name"][sym] = {}
        for t in ("10:30", "11:00", "11:30", "12:00", "12:30"):
            i = TIMES.index(t)
            s = stats([x for x in (pnl_at(f, i, cost) for f in sub) if x is not None])
            out["by_name"][sym][t] = s
            print(line(f"{sym} exit {t}", s))

    print("\n== rules (take profit / stop checked at bar starts), then time exit ==")
    out["rules"] = {}
    for t in ("11:30", "12:00", "12:30"):
        ti = TIMES.index(t)
        for tp in (None, 0.15, 0.25, 0.35, 0.50):
            for stop in (None, 0.5, 0.75):
                res = [run_rule(f, cost, ti, tp, stop, stop_slip=10.0 if stop else 0.0) for f in flies]
                vals = [r[0] if r else None for r in res]
                v = [x for x in vals if x is not None]
                s, sd = stats(v), stats(by_day(flies, vals))
                why = {k: sum(1 for r in res if r and r[1] == k) for k in ("take_profit", "stop", "time")}
                key = f"tp={tp} stop={stop} time={t}"
                out["rules"][key] = {"flies": s, "days": sd, "exits": why}
                print(line(key, s) + f"   | day t {sd['t']}  exits {why}")

    def split(label: str, key: str, edges: list[float], t: str = "12:00", absolute: bool = False) -> None:
        ti = TIMES.index(t)
        print(f"\n== by {label} (time exit {t}) ==")
        out.setdefault("splits", {})[label] = {}
        have = [f for f in flies if f.get(key) is not None]
        bounds = [-math.inf] + edges + [math.inf]
        for lo, hi in zip(bounds[:-1], bounds[1:]):
            sub = [f for f in have if lo <= (abs(f[key]) if absolute else f[key]) < hi]
            s = stats([x for x in (pnl_at(f, ti, cost) for f in sub) if x is not None])
            name = f"{label} [{lo:.3g}, {hi:.3g})"
            out["splits"][label][f"{lo:.3g}..{hi:.3g}"] = s
            print(line(name, s))

    split("premium_ratio", "premium_ratio", [0.9, 1.0, 1.1, 1.25, 1.5])
    split("premium_ratio_median", "premium_ratio_median", [1.0, 1.25, 1.5, 2.0])
    split("abs gap from prior close", "gap", [0.003, 0.006, 0.010, 0.015], absolute=True)
    split("abs drive open to 07:30", "drive", [0.002, 0.004, 0.007], absolute=True)
    split("pre-entry range", "range_pre", [0.004, 0.006, 0.009])
    split("straddle_pct", "straddle_pct", [0.004, 0.005, 0.006, 0.008])
    split("abs off-center (spot-K)/straddle", "off_center", [0.05, 0.10], absolute=True)

    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
