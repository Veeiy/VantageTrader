"""P070 / H015: does the exit-priced average sort earnings flies? (PLAN.md section 9, item 5)

    PYTHONPATH=src python3 scripts/earnings/exit_priced_test.py derived.jsonl [...]
        [--cap 600] [--scale 1.31] [--cost 0.07] [--json out.json]

The pass bar was written on 2026-11-21 and the method note on 2026-11-28, both before the
first run on real records (PLAN.md). For every clean replay event:

  the fly      the one the fly table calls "as traded": wings aimed at 1.5x the entry
               straddle, stepped in until the max loss fits the cap, never under 0.9x
  the result   that fly at its first exit bar, after the cost (a share of the credit)
  projection   each of the name's own past report moves (signed, point in time) applied to
               the entry price; the fly priced there with the stdev that should be left at
               the exit; the close cost held between zero and the width; the average, after
               the same cost
  stdev left   scale x regime20 x sqrt(sessions left). regime20 is the mean absolute daily
               move over the 20 sessions before the entry day. The live check reads this
               from the next expiry; the replay has no back-month prices.
  blocked      projected average at or under zero

Pass: blocked events average at least $10 a fly worse than kept ones, with a t of 2 or more
clustered by report date, AND kept events average more than the whole sample. A blocked side
under 15 events is too thin to pass. Rows at other scales, caps or with the stdev the market
really showed afterwards are description only.

Nothing here places orders or reads the market.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from earnings_fly_table import capped, mult  # noqa: E402
from vantage_trader.earnings.config import DEFAULTS  # noqa: E402
from vantage_trader.earnings.replay import call_put  # noqa: E402

AIM = 1.5
MIN_HISTORY = 4
MIN_SIDE = 15
PASS_DIFF_USD = 10.0
PASS_T = 2.0
HOLIDAYS = set(DEFAULTS["market_holidays"])


def sessions_left(x: str, expiry: str) -> int:
    """Sessions from the exit day through the expiry, both counted; a half day is one."""
    d, end, n = date.fromisoformat(x), date.fromisoformat(expiry), 0
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in HOLIDAYS:
            n += 1
        d += timedelta(days=1)
    return n


def first_bar(f: dict) -> str | None:
    return "b1" if "b1" in f else ("b2" if "b2" in f else None)


def project(r: dict, f: dict, sigma_exit: float, cost: float) -> float | None:
    """Average P/L of fly ``f`` at the exit over the name's past moves, after the cost (USD)."""
    moves = (r.get("history") or {}).get("moves") or []
    if not moves or sigma_exit is None or sigma_exit <= 0:
        return None
    k, w, credit, s0 = r["K"], f["width"], f["credit"], r["S_entry"]
    gw = sigma_exit * mult(r, f["m"], "exit")
    total = 0.0
    for m in moves:
        spot = s0 * max(1.0 + m, 0.05)
        c, p = call_put(spot, k, sigma_exit)
        close = c + p - call_put(spot, k + w, gw)[0] - call_put(spot, k - w, gw)[1]
        total += (credit - min(max(close, 0.0), w)) * 100.0
    return total / len(moves) - cost * credit * 100.0


def build(rows: list[dict], cap: float | None, scale: float, cost: float, oracle: bool = False) -> tuple[list[dict], dict]:
    """One record per usable event, and the count dropped for each reason."""
    drop = {"clean": 0, "no_fly_under_cap": 0, "no_exit_price": 0, "under_4_past_moves": 0, "no_regime20": 0,
            "no_post_stdev": 0}
    out = []
    for r in rows:
        if not (r.get("status") == "ok" and r.get("clean")):
            continue
        drop["clean"] += 1
        f = capped(r, AIM, cap)
        if f is None:
            drop["no_fly_under_cap"] += 1
            continue
        bar = first_bar(f)
        if bar is None:
            drop["no_exit_price"] += 1
            continue
        if len((r.get("history") or {}).get("moves") or []) < MIN_HISTORY:
            drop["under_4_past_moves"] += 1
            continue
        if oracle:
            sig = r.get(f"sigma_post_{bar}")
            if not sig:
                drop["no_post_stdev"] += 1
                continue
        else:
            if not r.get("regime20"):
                drop["no_regime20"] += 1
                continue
            sig = scale * r["regime20"] * math.sqrt(sessions_left(r["X"], r["expiry"]))
        proj = project(r, f, sig, cost)
        out.append({"symbol": r["symbol"], "report_date": r["report_date"], "X": r["X"], "expiry": r["expiry"],
                    "edge_ratio": r.get("edge_ratio"), "m": round(f["m"], 3), "credit": round(f["credit"], 4),
                    "max_loss": round(f["max_loss"], 1), "sigma_exit": round(sig, 5),
                    "sigma_post": r.get(f"sigma_post_{bar}"), "projected": round(proj, 2),
                    "result": round(f[bar] - cost * f["credit"] * 100.0, 2), "blocked": proj <= 0.0})
    drop["used"] = len(out)
    return out, drop


def row(evs: list[dict]) -> dict:
    n = len(evs)
    if n == 0:
        return {"n": 0}
    xs = [e["result"] for e in evs]
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    worst = min(evs, key=lambda e: e["result"])
    return {"n": n, "wins": sum(1 for x in xs if x > 0), "mean": round(mean, 1),
            "se": round(sd / math.sqrt(n), 1) if n > 1 else None,
            "worst": f"{worst['symbol']} {worst['report_date']} {worst['result']:+.0f}",
            "dates": len({e["report_date"] for e in evs})}


def clustered_diff(evs: list[dict]) -> dict:
    """Kept minus blocked, with a standard error clustered by report date (CR1).

    OLS of the result on a constant and the kept flag; the slope is the difference of means.
    """
    n = len(evs)
    kept = [e for e in evs if not e["blocked"]]
    blocked = [e for e in evs if e["blocked"]]
    if not kept or not blocked:
        return {"diff": None, "se": None, "t": None, "clusters": len({e["report_date"] for e in evs})}
    mk = sum(e["result"] for e in kept) / len(kept)
    mb = sum(e["result"] for e in blocked) / len(blocked)
    # X'X for regressors (1, d) and its inverse
    nk = len(kept)
    det = n * nk - nk * nk
    inv = [[nk / det, -nk / det], [-nk / det, n / det]]
    groups: dict[str, list[float]] = {}
    for e in evs:
        d = 0.0 if e["blocked"] else 1.0
        u = e["result"] - (mk if d else mb)
        g = groups.setdefault(e["report_date"], [0.0, 0.0])
        g[0] += u
        g[1] += u * d
    meat = [[0.0, 0.0], [0.0, 0.0]]
    for a, b in groups.values():
        meat[0][0] += a * a
        meat[0][1] += a * b
        meat[1][0] += b * a
        meat[1][1] += b * b
    g_n = len(groups)
    adj = (g_n / (g_n - 1)) * ((n - 1) / (n - 2)) if g_n > 1 and n > 2 else 1.0
    # slope variance = (inv * meat * inv)[1][1]
    tmp = [inv[1][0] * meat[0][0] + inv[1][1] * meat[1][0], inv[1][0] * meat[0][1] + inv[1][1] * meat[1][1]]
    var = adj * (tmp[0] * inv[0][1] + tmp[1] * inv[1][1])
    se = math.sqrt(var) if var > 0 else 0.0
    diff = mk - mb
    return {"diff": round(diff, 1), "se": round(se, 1), "t": round(diff / se, 2) if se else None, "clusters": g_n}


def verdict(evs: list[dict]) -> dict:
    allr, kept, blocked = row(evs), row([e for e in evs if not e["blocked"]]), row([e for e in evs if e["blocked"]])
    cd = clustered_diff(evs)
    enough = blocked.get("n", 0) >= MIN_SIDE and kept.get("n", 0) >= MIN_SIDE
    c1 = cd["diff"] is not None and cd["diff"] >= PASS_DIFF_USD and cd["t"] is not None and cd["t"] >= PASS_T
    c2 = kept.get("n", 0) > 0 and kept["mean"] > allr["mean"]
    return {"all": allr, "kept": kept, "blocked": blocked, "kept_minus_blocked": cd,
            "blocked_side_big_enough": enough, "diff_10_and_t_2": c1, "kept_beats_whole_sample": c2,
            "passes": bool(enough and c1 and c2)}


def spearman(evs: list[dict]) -> float | None:
    n = len(evs)
    if n < 3:
        return None

    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2.0 + 1.0
            i = j + 1
        return out

    a, b = ranks([e["projected"] for e in evs]), ranks([e["result"] for e in evs])
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    return round(cov / math.sqrt(va * vb), 3) if va > 0 and vb > 0 else None


def line(label: str, v: dict) -> str:
    a, k, b, d = v["all"], v["kept"], v["blocked"], v["kept_minus_blocked"]

    def side(x: dict) -> str:
        return f"n={x['n']} mean {x['mean']:+} (se {x['se']}) worst {x['worst']}" if x.get("n") else "n=0"

    return (f"{label}: all {side(a)} | kept {side(k)} | blocked {side(b)} | kept minus blocked {d['diff']} "
            f"(clustered se {d['se']}, t {d['t']}, {d['clusters']} report dates) | passes: {v['passes']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--cap", type=float, default=600.0)
    ap.add_argument("--scale", type=float, default=1.31)
    ap.add_argument("--cost", type=float, default=0.07)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    rows = []
    for f in a.files:
        rows += [json.loads(x) for x in Path(f).read_text().splitlines() if x.strip()]
    evs, drop = build(rows, a.cap, a.scale, a.cost)
    head = verdict(evs)
    out = {"files": [str(f) for f in a.files], "cap_usd": a.cap, "scale": a.scale, "cost_share": a.cost,
           "counts": drop, "headline": head, "spearman_projected_vs_result": spearman(evs), "description": {}}
    print(f"clean {drop['clean']}; used {drop['used']} (no fly under the cap {drop['no_fly_under_cap']}, no exit price "
          f"{drop['no_exit_price']}, under {MIN_HISTORY} past moves {drop['under_4_past_moves']}, no regime20 {drop['no_regime20']})")
    print("VERDICT " + line(f"cap ${a.cap:.0f}, scale {a.scale}", head))
    print(f"  bar: blocked side at least {MIN_SIDE}: {head['blocked_side_big_enough']}; kept minus blocked >= ${PASS_DIFF_USD:.0f} "
          f"with t >= {PASS_T}: {head['diff_10_and_t_2']}; kept beats the whole sample: {head['kept_beats_whole_sample']}")
    print(f"  rank correlation, projected against result: {out['spearman_projected_vs_result']}")
    print("\nDescription only (not a second try):")
    for label, kw in (("scale 1.05", {"scale": 1.05}), ("scale 1.43", {"scale": 1.43}),
                      ("cap $436", {"cap": 436.0}), ("no cap", {"cap": None}),
                      ("stdev as the market showed it after the report", {"oracle": True})):
        e2, d2 = build(rows, kw.get("cap", a.cap), kw.get("scale", a.scale), a.cost, kw.get("oracle", False))
        v2 = verdict(e2)
        out["description"][label] = {"counts": d2, **v2, "spearman": spearman(e2)}
        print("  " + line(label, v2))
    # the same filter inside the names the edge ratio lets through, and the ratio's own split
    passed = [e for e in evs if e["edge_ratio"] is not None and e["edge_ratio"] <= 0.85]
    out["description"]["inside edge ratio at or under 0.85"] = verdict(passed)
    print("  " + line("inside edge ratio at or under 0.85", out["description"]["inside edge ratio at or under 0.85"]))
    by_ratio = [dict(e, blocked=not (e["edge_ratio"] is not None and e["edge_ratio"] <= 0.85)) for e in evs]
    out["description"]["the edge ratio's own split (kept = at or under 0.85)"] = verdict(by_ratio)
    print("  " + line("the edge ratio's own split (kept = at or under 0.85)",
                      out["description"]["the edge ratio's own split (kept = at or under 0.85)"]))
    # how close the stdev proxy came to what the market showed (a check of the input, not of the filter)
    ratios = sorted(e["sigma_exit"] / e["sigma_post"] for e in evs if e.get("sigma_post"))
    if ratios:
        q = lambda p: round(ratios[min(len(ratios) - 1, int(p * len(ratios)))], 2)  # noqa: E731
        out["proxy_over_actual_stdev"] = {"n": len(ratios), "p25": q(0.25), "median": q(0.5), "p75": q(0.75)}
        print(f"  stdev proxy over the stdev the market showed: n={len(ratios)} median {q(0.5)} (quartiles {q(0.25)} to {q(0.75)})")
    out["events"] = evs
    if a.json:
        a.json.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
