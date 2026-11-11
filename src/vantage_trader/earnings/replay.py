"""Replay of past earnings events with real option prices: derive and summarise.

Why: live trades give two or three observations a day. Replaying past reports from the
broker's option price history gives dozens in one evening (proposal P007).

Division of labour (``docs/earnings/REPLAY.md``): read-only agents collect RAW prices for
each event, one JSON object per event. Every derived number (credit, close cost, P/L, edge
ratio, gates) is computed here, so no result depends on an agent's arithmetic.

Raw record (one per event)::

    {"symbol", "K", "w1c_strike", "w1p_strike", "w2c_strike", "w2p_strike",
     "stock": {"entry", "x_open", "b1", "b2"},
     "legs": {"kc"|"kp"|"w1c"|"w1p"|"w2c"|"w2p": {"entry", "b1", "b2", "interp": [...]}},
     "quality", "status": "ok"|"no_weekly"|"no_data"}

``entry`` = close of the entry day's last 30-minute bar; ``b1`` / ``b2`` = close of the exit
day's first / second 30-minute bar.

What the first replay (2026-11-10) taught us about the data, and how it is handled here:
  * Option bars are LAST TRADES with no volume and no reliable "interpolated" flag. A bar
    with no trade shows 0.01. So a print at or below ``PLACEHOLDER`` is treated as "no
    price", never as a price.
  * At-the-money prints are mostly usable; wing prints are sparse and often stale. The
    headline fly result therefore uses REAL body prices and MODEL wings: wings are priced
    from the body's implied total stdev times a multiplier calibrated on the wing prints
    that do exist (``calibrate_wings``). The all-printed-prices variant is kept as a
    cross-check (``traded``).
  * A body print can be stale too. Two guards: each leg is floored at intrinsic value, and
    put-call parity is checked; events that fail it are flagged and left out of the
    ``clean`` statistics.

Known limits, stated in every summary: no bid-ask cost; the spread gate and the news gate
cannot be replayed; one contract per event filled at the printed prices.

Nothing here places orders or reads the market.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import mean, median, quantiles
from typing import Any, Callable, Iterable

from . import history
from .config import EngineInputError
from .projection import call_put, implied_sigma

EXITS = ("b1", "b2")
WIDTHS = ("1", "2")
POINTS = ("entry",) + EXITS
REGIME_MULT = 1.25        # regime guard, RULES_CHANGELOG v1.1
INTRADAY_BAND_TOP = 0.07  # 5-7% is allowed only with a sector move and no stock news (v1.1)
ENTRY_MISMATCH = 0.01     # raw entry price versus the daily close: flag above this
PLACEHOLDER = 0.011       # a print at or below this is "no trade in the bar", not a price
PARITY_TOL = 0.20         # |(call - put) - (spot - strike)| above this share of the straddle: prints out of sync
EDGE_BUCKETS = ((0.70, "<=0.70"), (0.85, "0.70-0.85"), (1.00, "0.85-1.00"), (1.25, "1.00-1.25"))
ROI_BUCKETS = ((0.35, "<=0.35"), (0.70, "0.35-0.70"), (1.00, "0.70-1.00"), (1.50, "1.00-1.50"))
INTRADAY_BUCKETS = ((0.02, "<2%"), (0.05, "2-5%"), (0.07, "5-7%"))
PRICE_BUCKETS = ((25.0, "$10-25"), (50.0, "$25-50"), (100.0, "$50-100"))
DEFAULT_WING_MULT = {n: {"entry": 1.0, "exit": 1.0} for n in WIDTHS}


def _f(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _r(v: float | None, nd: int = 4) -> float | None:
    return round(v, nd) if v is not None else None


def option_sigma(spot: float, strike: float, price: float | None, kind: str) -> float | None:
    """Total remaining stdev that reproduces ONE option's price (zero rates).

    None when the price is at or below intrinsic value or above the no-arbitrage bound.
    """
    if kind not in ("call", "put"):
        raise EngineInputError("kind must be call or put")
    if price is None or spot <= 0 or strike <= 0:
        return None
    intrinsic = max(spot - strike, 0.0) if kind == "call" else max(strike - spot, 0.0)
    upper = spot if kind == "call" else strike
    if price <= intrinsic + 1e-9 or price >= upper:
        return None
    lo, hi = 1e-6, 5.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        c, p = call_put(spot, strike, mid)
        if (c if kind == "call" else p) < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _leg(raw: dict[str, Any], name: str, field: str) -> float | None:
    """A leg's printed price, or None when there is no usable print."""
    leg = (raw.get("legs") or {}).get(name)
    if not isinstance(leg, dict):
        return None
    v = _f(leg.get(field))
    if v is None or v <= PLACEHOLDER or field in (leg.get("interp") or []):
        return None
    return v


def week_of(day: str) -> str:
    d = date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def hist_stats(event: dict[str, Any], bars: list[dict[str, Any]] | None, reports: Iterable[Any] | None,
               lookback: int = 12) -> dict[str, Any]:
    """Point-in-time history for one event: only reports BEFORE this report date count."""
    out: dict[str, Any] = {"n_hist": 0, "avg_hist_move": None, "moves": [], "dates": [],
                           "prior_close": None, "close_E": None, "regime20": None}
    if not bars:
        return out
    prior = []
    for rep in reports or []:
        if isinstance(rep, dict):
            d, t, a = rep.get("date"), rep.get("timing"), rep.get("actual", 1)
        else:
            d, t, a = (list(rep) + [1, 1, 1])[:3]
        if d and str(d) < str(event["report_date"]) and a:
            prior.append({"date": str(d), "timing": t})
    res = history.compute_moves(bars, prior, event.get("symbol", ""))
    moves, dates = res["moves"][-lookback:], res["dates"][-lookback:]
    out.update(n_hist=len(moves), moves=moves, dates=dates,
               avg_hist_move=_r(mean(abs(m) for m in moves), 6) if moves else None)
    days, closes = history.build_calendar(bars, event.get("symbol", ""))
    known = [(d.isoformat(), closes[d]) for d in days if closes[d] is not None]
    by_day = dict(known)
    e_prev, e_day = event.get("E_prev"), event.get("E")
    if e_prev:
        out["prior_close"] = by_day.get(e_prev)
        upto = [c for d, c in known if d <= e_prev]   # what a scan on day E can see
        if len(upto) >= 21:
            last = upto[-21:]
            out["regime20"] = _r(mean(abs(last[i] / last[i - 1] - 1.0) for i in range(1, 21)), 6)
    if e_day:
        out["close_E"] = by_day.get(e_day)
    return out


def _body(raw: dict[str, Any], k: float, spots: dict[str, float | None]) -> dict[str, dict[str, Any]]:
    """Body prices at entry, b1, b2: floored at intrinsic, with a put-call parity check."""
    out: dict[str, dict[str, Any]] = {}
    for x in POINTS:
        spot = spots.get(x)
        c_raw = _f(((raw.get("legs") or {}).get("kc") or {}).get(x))
        p_raw = _f(((raw.get("legs") or {}).get("kp") or {}).get(x))
        d: dict[str, Any] = {"straddle": None, "parity_ok": None, "floored": False}
        if spot and c_raw is not None and p_raw is not None:
            ci, pi = max(spot - k, 0.0), max(k - spot, 0.0)
            c, p = max(c_raw, ci), max(p_raw, pi)
            st = c + p
            gap = (c - p) - (spot - k)
            d.update(straddle=st, call=c, put=p, floored=bool(c > c_raw + 1e-9 or p > p_raw + 1e-9),
                     parity_gap=_r(gap), parity_ok=bool(st > 0 and abs(gap) <= PARITY_TOL * st))
        out[x] = d
    return out


def _fly(raw: dict[str, Any], n: str, k: float, spots: dict[str, float | None],
         body: dict[str, dict[str, Any]], sigma: dict[str, float | None],
         mult: dict[str, float]) -> dict[str, Any] | None:
    cs, ps = _f(raw.get(f"w{n}c_strike")), _f(raw.get(f"w{n}p_strike"))
    if cs is None or ps is None or cs <= k or ps >= k or ps <= 0:
        return None
    wc, wp = cs - k, k - ps
    width = max(wc, wp)
    se, s_entry = body["entry"]["straddle"], spots["entry"]
    out: dict[str, Any] = {"call_strike": cs, "put_strike": ps, "width_call": _r(wc), "width_put": _r(wp),
                           "width_over_straddle": _r((wc + wp) / 2.0 / se) if se else None}
    if se is None or not s_entry:
        return out
    # 1. model wings: real body, wings from the body's implied stdev (headline)
    if sigma["entry"] is not None:
        g0 = sigma["entry"] * mult["entry"]
        credit = se - call_put(s_entry, cs, g0)[0] - call_put(s_entry, ps, g0)[1]
        model: dict[str, Any] = {"credit": _r(credit), "max_loss_usd": _r((width - credit) * 100.0, 2),
                                 "credit_over_straddle": _r(credit / se)}
        for x in EXITS:
            sx, spot_x = body[x]["straddle"], spots[x]
            if sx is None or not spot_x:
                continue
            gx = (sigma[x] or 0.0) * mult["exit"]
            close = sx - call_put(spot_x, cs, gx)[0] - call_put(spot_x, ps, gx)[1]
            close = min(max(close, 0.0), width)     # a fly is worth between 0 and its width
            model[f"close_{x}"] = _r(close)
            model[f"pnl_{x}_usd"] = _r((credit - close) * 100.0, 2)
        out["model"] = model
    # 2. printed wings: only when every wing print exists (cross-check, not the headline)
    ce, pe = _leg(raw, f"w{n}c", "entry"), _leg(raw, f"w{n}p", "entry")
    if ce is not None and pe is not None:
        credit = se - ce - pe
        traded: dict[str, Any] = {"credit": _r(credit), "max_loss_usd": _r((width - credit) * 100.0, 2),
                                  "coherent": bool(0.0 < credit < width)}
        for x in EXITS:
            sx, spot_x = body[x]["straddle"], spots[x]
            if sx is None or not spot_x:
                continue
            cx_raw = _f(((raw.get("legs") or {}).get(f"w{n}c") or {}).get(x))
            px_raw = _f(((raw.get("legs") or {}).get(f"w{n}p") or {}).get(x))
            if cx_raw is None or px_raw is None:
                continue
            # at the exit a 0.01 print is plausible for a wing left far out of the money
            cx, px = max(cx_raw, spot_x - cs, 0.0), max(px_raw, ps - spot_x, 0.0)
            close = sx - cx - px
            traded[f"close_{x}"] = _r(close)
            traded[f"pnl_{x}_usd"] = _r((credit - close) * 100.0, 2)
            traded[f"coherent_{x}"] = bool(traded["coherent"] and -0.05 * width <= close <= 1.05 * width)
        out["traded"] = traded
    return out


def derive(event: dict[str, Any], raw: dict[str, Any], bars: list[dict[str, Any]] | None = None,
           reports: Iterable[Any] | None = None, cfg: dict[str, Any] | None = None,
           macro_entry_dates: Iterable[str] = (),
           wing_mult: dict[str, dict[str, float]] | None = None) -> dict[str, Any]:
    """One derived record from an event row, its raw prices and its history."""
    cfg = cfg or {}
    wing_mult = wing_mult or DEFAULT_WING_MULT
    for key in ("symbol", "report_date", "timing", "E", "X"):
        if not event.get(key):
            raise EngineInputError(f"event is missing {key}")
    if raw.get("symbol") != event["symbol"]:
        raise EngineInputError(f"raw record is for {raw.get('symbol')!r}, event is {event['symbol']!r}")
    rec: dict[str, Any] = {k: event.get(k) for k in ("symbol", "report_date", "timing", "E", "X", "expiry")}
    rec.update(week=week_of(event["E"]), status=raw.get("status") or "no_data", quality=raw.get("quality"))
    stock = raw.get("stock") if isinstance(raw.get("stock"), dict) else {}
    s_entry = _f(stock.get("entry"))
    hs = hist_stats(event, bars, reports, int(cfg.get("history_lookback", 12)))
    if not bars:
        # daily scoring: the scan already knows the history, so the event row may carry it
        for key in ("avg_hist_move", "prior_close", "regime20"):
            if _f(event.get(key)) is not None:
                hs[key] = _f(event[key])
        if hs["avg_hist_move"] is not None:
            hs["n_hist"] = int(event.get("n_hist") or 0)
    rec.update(S_prev_close=hs["prior_close"], S_entry=s_entry, S_open=_f(stock.get("x_open")),
               S_b1=_f(stock.get("b1")), S_b2=_f(stock.get("b2")))
    flags: list[str] = []
    if s_entry and hs["close_E"] and abs(s_entry / hs["close_E"] - 1.0) > ENTRY_MISMATCH:
        flags.append("entry_price_differs_from_daily_close")
    if s_entry:
        rec["intraday_pct"] = _r(s_entry / hs["prior_close"] - 1.0) if hs["prior_close"] else None
        rec["open_move"] = _r(rec["S_open"] / s_entry - 1.0) if rec["S_open"] else None
        for x in EXITS:
            sx = rec[f"S_{x}"]
            rec[f"move_{x}"] = _r(sx / s_entry - 1.0) if sx else None
    rec["history"] = {k: hs[k] for k in ("n_hist", "avg_hist_move", "moves", "dates")}
    rec["regime20"] = hs["regime20"]

    k = _f(raw.get("K"))
    if rec["status"] != "ok" or k is None or not s_entry:
        rec.update(flags=flags, label="not_priced", clean=False)
        return rec
    rec["K"] = k
    spots: dict[str, float | None] = {"entry": s_entry, "b1": rec["S_b1"], "b2": rec["S_b2"]}
    body = _body(raw, k, spots)
    se = body["entry"]["straddle"]
    if se is None or se <= 0:
        rec.update(status="no_data", label="not_priced", clean=False, flags=flags + ["no_body_entry_price"])
        return rec
    sigma: dict[str, float | None] = {
        x: implied_sigma(spots[x], k, body[x]["straddle"]) if spots[x] and body[x]["straddle"] is not None else None
        for x in POINTS}
    # implied move = an AT-THE-MONEY straddle at the body's implied stdev, as a share of spot.
    # With a coarse strike grid the body can sit well off the money, and its raw straddle
    # then holds intrinsic value that is not an implied move (TFC, 2026-10-15: 4.5% raw, 4.2% at the money).
    atm_straddle = call_put(s_entry, s_entry, sigma["entry"]) if sigma["entry"] is not None else None
    implied_pct = sum(atm_straddle) / s_entry if atm_straddle else se / s_entry
    rec.update(straddle_entry=_r(se), straddle_b1=_r(body["b1"]["straddle"]), straddle_b2=_r(body["b2"]["straddle"]),
               straddle_over_spot=_r(se / s_entry), body_offset_pct=_r(k / s_entry - 1.0),
               implied_pct=_r(implied_pct), sigma_pre=_r(sigma["entry"]),
               parity={x: {"gap": body[x].get("parity_gap"), "ok": body[x]["parity_ok"],
                           "floored": body[x]["floored"]} for x in POINTS})
    if body["entry"]["parity_ok"] is False:
        flags.append("entry_parity")
    for x in EXITS:
        mv, sx = rec.get(f"move_{x}"), body[x]["straddle"]
        rec[f"r_over_i_{x}"] = _r(abs(mv) / implied_pct) if mv is not None else None
        rec[f"sigma_post_{x}"] = _r(sigma[x])
        rec[f"crush_{x}"] = _r(sigma[x] / sigma["entry"]) if sigma[x] is not None and sigma["entry"] else None
        rec[f"short_straddle_pnl_{x}_usd"] = _r((se - sx) * 100.0, 2) if sx is not None else None
        if body[x]["parity_ok"] is False:
            flags.append(f"exit_parity_{x}")
        if body[x]["floored"]:
            flags.append(f"body_floored_{x}")
    rec["clean"] = bool(body["entry"]["parity_ok"] and body["b2"]["parity_ok"])

    # how the market priced the wings relative to the body (skew), from usable prints only
    ratios: dict[str, dict[str, float]] = {"entry": {}, "b2": {}}
    for n in WIDTHS:
        for side, kind in (("c", "call"), ("p", "put")):
            strike = _f(raw.get(f"w{n}{side}_strike"))
            if strike is None:
                continue
            for x in ("entry", "b2"):
                price = _leg(raw, f"w{n}{side}", x)
                if price is not None and spots[x] and sigma[x] and body[x]["parity_ok"]:
                    g = option_sigma(spots[x], strike, price, kind)
                    if g is not None:
                        ratios[x][f"w{n}{side}"] = _r(g / sigma[x])
    rec["wing_sigma_ratio"] = ratios
    for n in WIDTHS:
        rec[f"fly{n}"] = _fly(raw, n, k, spots, body, sigma, wing_mult.get(n, DEFAULT_WING_MULT[n]))

    # gates that can be replayed
    factor = float(cfg.get("straddle_factor", 0.85))
    avg = hs["avg_hist_move"]
    implied_move = factor * implied_pct
    edge = avg / implied_move if avg is not None and implied_move > 0 else None
    rec.update(implied_move=_r(implied_move), edge_ratio=_r(edge))
    sell_max, buy_min = float(cfg.get("sell_max_ratio", 0.85)), float(cfg.get("buy_min_ratio", 1.25))
    intraday = rec.get("intraday_pct")
    max_intraday = float(cfg.get("max_intraday_move", 0.05))
    gates: dict[str, Any] = {
        "history_ok": hs["n_hist"] >= int(cfg.get("min_history", 4)),
        "price_ok": s_entry >= float(cfg.get("min_price", 10.0)),
        "edge": None if edge is None else "sell" if edge <= sell_max else "buy" if edge >= buy_min else "none",
        "regime_ok": None if hs["regime20"] is None or avg is None else bool(hs["regime20"] < REGIME_MULT * avg),
        "regime_ratio": _r(hs["regime20"] / avg) if hs["regime20"] is not None and avg else None,
        "intraday": None if intraday is None else "pass" if abs(intraday) <= max_intraday
        else "band" if abs(intraday) <= INTRADAY_BAND_TOP else "block",
        "macro_ok": event["E"] not in set(macro_entry_dates),
    }
    rec["gates"] = gates
    if not gates["history_ok"] or gates["edge"] is None:
        label = "no_history"
    elif gates["edge"] == "none":
        label = "no_edge"
    elif gates["edge"] == "buy":
        label = "buy_zone"
    else:
        blockers = []
        if not gates["price_ok"]:
            blockers.append("price")
        if gates["regime_ok"] is False:
            blockers.append("regime")
        if gates["intraday"] == "block":
            blockers.append("intraday")
        elif gates["intraday"] == "band":
            blockers.append("intraday_band")
        if not gates["macro_ok"]:
            blockers.append("macro")
        label = "sell_pass" if not blockers else "sell_blocked:" + "+".join(blockers)
    rec["label"] = label
    rec["flags"] = flags
    return rec


def calibrate_wings(records: list[dict[str, Any]], min_prints: int = 8) -> dict[str, Any]:
    """Median wing/body implied-stdev ratio per width, at entry and at the exit.

    Falls back to 1.0 where fewer than ``min_prints`` usable prints exist.
    """
    out: dict[str, Any] = {"mult": {}, "prints": {}}
    for n in WIDTHS:
        out["mult"][n], out["prints"][n] = {}, {}
        for point, key in (("entry", "entry"), ("b2", "exit")):
            vals = [v for r in records if r.get("clean")
                    for name, v in ((r.get("wing_sigma_ratio") or {}).get(point) or {}).items()
                    if name.startswith(f"w{n}")]
            out["prints"][n][key] = len(vals)
            out["mult"][n][key] = round(median(vals), 4) if len(vals) >= min_prints else 1.0
    return out


# ---------------------------------------------------------------- summary

def _stats(rows: list[tuple[float, float | None]]) -> dict[str, Any]:
    """rows = (pnl_usd, max_loss_usd)."""
    if not rows:
        return {"n": 0}
    pnls = [p for p, _ in rows]
    rom = [p / m for p, m in rows if m and m > 0]
    wins = sum(1 for p in pnls if p > 0)
    return {"n": len(rows), "wins": wins, "win_rate": round(wins / len(rows), 4),
            "total_usd": round(sum(pnls), 2), "avg_usd": round(mean(pnls), 2),
            "median_usd": round(median(pnls), 2), "worst_usd": round(min(pnls), 2),
            "best_usd": round(max(pnls), 2),
            "avg_pnl_over_max_loss": round(mean(rom), 4) if rom else None}


def _quart(xs: Iterable[float | None]) -> dict[str, Any]:
    vals = sorted(x for x in xs if x is not None)
    if len(vals) < 2:
        return {"n": len(vals), "median": vals[0] if vals else None}
    q1, q2, q3 = quantiles(vals, n=4, method="inclusive")
    return {"n": len(vals), "q1": round(q1, 4), "median": round(q2, 4), "q3": round(q3, 4),
            "min": round(vals[0], 4), "max": round(vals[-1], 4), "mean": round(mean(vals), 4)}


def _bucket(value: float | None, edges: tuple[tuple[float, str], ...], top: str) -> str:
    if value is None:
        return "unknown"
    for limit, name in edges:
        if value <= limit:
            return name
    return top


def _ranks(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        for t in range(i, j + 1):
            ranks[order[t]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = mean(rx), mean(ry)
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if sx == 0 or sy == 0:
        return None
    return round(sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy), 4)


def fly_row(rec: dict[str, Any], n: str = "1", x: str = "b2", source: str = "model",
            cost_frac: float = 0.0) -> tuple[float, float | None] | None:
    """(pnl, max_loss) for one variant, or None when it cannot be scored.

    ``cost_frac`` takes that share of the entry credit off the result as a round-trip
    trading cost (the replay prices have no bid-ask in them).
    """
    fly = rec.get(f"fly{n}")
    if not isinstance(fly, dict):
        return None
    part = fly.get(source)
    if not isinstance(part, dict):
        return None
    p = part.get(f"pnl_{x}_usd")
    if p is None or (source == "traded" and not part.get(f"coherent_{x}")):
        return None
    if cost_frac:
        p = round(p - cost_frac * float(part.get("credit") or 0.0) * 100.0, 2)
    return p, part.get("max_loss_usd")


def fisher_one_sided(a_wins: int, a_n: int, b_wins: int, b_n: int) -> float | None:
    """Chance of group A winning at least this often if A and B were the same (Fisher exact)."""
    n, wins = a_n + b_n, a_wins + b_wins
    if a_n == 0 or b_n == 0:
        return None
    total = math.comb(n, a_n)
    return round(sum(math.comb(wins, x) * math.comb(n - wins, a_n - x)
                     for x in range(a_wins, min(a_n, wins) + 1)) / total, 4)


def summarize(records: list[dict[str, Any]], max_loss_cap: float = 350.0, clean_only: bool = True,
              cost_frac: float = 0.0, tight_edge: float = 0.70) -> dict[str, Any]:
    priced_all = [r for r in records if r.get("status") == "ok" and r.get("straddle_entry")]
    priced = [r for r in priced_all if r.get("clean")] if clean_only else priced_all

    def variant(rs: list[dict[str, Any]], n: str, x: str = "b2", source: str = "model") -> dict[str, Any]:
        return _stats([row for row in (fly_row(r, n, x, source, cost_frac) for r in rs) if row is not None])

    def split(pred: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        scored = [(r, fly_row(r, "1", "b2", "model", cost_frac)) for r in priced]
        a = [row for r, row in scored if row is not None and pred(r)]
        b = [row for r, row in scored if row is not None and not pred(r)]
        aw, bw = sum(1 for p, _ in a if p > 0), sum(1 for p, _ in b if p > 0)
        return {"in": _stats(a), "out": _stats(b), "fisher_one_sided_p": fisher_one_sided(aw, len(a), bw, len(b))}

    def abs_move(key: str) -> float | None:
        vals = [abs(r[key]) for r in priced if r.get(key) is not None]
        return round(mean(vals), 4) if vals else None

    def by(key_fn: Callable[[dict[str, Any]], str], n: str = "1") -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in priced:
            groups.setdefault(key_fn(r), []).append(r)
        return {k: variant(v, n) for k, v in sorted(groups.items())}

    status: dict[str, int] = {}
    for r in records:
        status[r.get("status") or "?"] = status.get(r.get("status") or "?", 0) + 1
    flag_counts: dict[str, int] = {}
    for r in priced_all:
        for fl in r.get("flags") or []:
            flag_counts[fl] = flag_counts.get(fl, 0) + 1

    def label_group(r: dict[str, Any]) -> str:
        lab = r.get("label") or "?"
        return "sell_blocked" if lab.startswith("sell_blocked") else lab

    def cap_ok(r: dict[str, Any]) -> bool:
        row = fly_row(r, "1")
        return row is not None and row[1] is not None and row[1] <= max_loss_cap

    edge_roi = [(r["edge_ratio"], r["r_over_i_b2"]) for r in priced
                if r.get("edge_ratio") is not None and r.get("r_over_i_b2") is not None]
    edge_groups: dict[str, list[float]] = {}
    for e, roi in edge_roi:
        edge_groups.setdefault(_bucket(e, EDGE_BUCKETS, ">=1.25"), []).append(roi)
    buy = [r for r in priced if r.get("label") == "buy_zone" and r.get("short_straddle_pnl_b2_usd") is not None]
    straddle_rows = [(r["short_straddle_pnl_b2_usd"], None) for r in priced
                     if r.get("short_straddle_pnl_b2_usd") is not None]
    both_exits = [r for r in priced if fly_row(r, "1", "b1") and fly_row(r, "1", "b2")]
    both_src = [r for r in priced if fly_row(r, "1", "b2", "model") and fly_row(r, "1", "b2", "traded")]

    return {
        "counts": {"events": len(records), "by_status": status, "priced": len(priced_all),
                   "clean": sum(1 for r in priced_all if r.get("clean")), "used": len(priced),
                   "clean_only": clean_only, "cost_frac": cost_frac, "flags": dict(sorted(flag_counts.items()))},
        "edge_split": {
            "tight": {"cut": tight_edge,
                      **split(lambda r: r.get("edge_ratio") is not None and r["edge_ratio"] <= tight_edge)},
            "tight_and_passing": {"cut": tight_edge, **split(
                lambda r: r.get("label") == "sell_pass" and r.get("edge_ratio") is not None
                and r["edge_ratio"] <= tight_edge)},
            "passing": split(lambda r: r.get("label") == "sell_pass"),
        },
        "stock_move_abs_mean": {"open": abs_move("open_move"), "b1": abs_move("move_b1"), "b2": abs_move("move_b2"),
                                "grew_open_to_b2": sum(1 for r in priced if r.get("open_move") is not None
                                                       and r.get("move_b2") is not None
                                                       and abs(r["move_b2"]) > abs(r["open_move"]))},
        "overall": {f"fly{n}_{x}_{src}": variant(priced, n, x, src)
                    for n in WIDTHS for x in EXITS for src in ("model", "traded")},
        "short_straddle_b2": _stats(straddle_rows),
        "by_label": {n: by(label_group, n) for n in WIDTHS},
        "by_label_detail": by(lambda r: r.get("label") or "?"),
        "by_edge_bucket": {n: by(lambda r: _bucket(r.get("edge_ratio"), EDGE_BUCKETS, ">=1.25"), n) for n in WIDTHS},
        "by_r_over_i": {n: by(lambda r: _bucket(r.get("r_over_i_b2"), ROI_BUCKETS, ">1.50"), n) for n in WIDTHS},
        "by_week": {n: by(lambda r: r.get("week") or "?", n) for n in WIDTHS},
        "by_intraday": by(lambda r: _bucket(abs(r["intraday_pct"]) if r.get("intraday_pct") is not None else None,
                                            INTRADAY_BUCKETS, ">7%")),
        "by_regime": by(lambda r: {True: "ok", False: "tripped", None: "unknown"}[(r.get("gates") or {}).get("regime_ok")]),
        "by_macro": by(lambda r: "ok" if (r.get("gates") or {}).get("macro_ok", True) else "veto_day"),
        "by_timing": by(lambda r: r.get("timing") or "?"),
        "by_price": by(lambda r: _bucket(r.get("S_entry"), PRICE_BUCKETS, "$100+")),
        "exit_time_paired": {"n": len(both_exits), "b1": variant(both_exits, "1", "b1"),
                             "b2": variant(both_exits, "1", "b2")},
        "model_vs_traded_paired": {"n": len(both_src), "model": variant(both_src, "1", "b2", "model"),
                                   "traded": variant(both_src, "1", "b2", "traded")},
        "max_loss_within_cap": {"cap_usd": max_loss_cap, "fly1": variant([r for r in priced if cap_ok(r)], "1")},
        "edge_vs_realized": {
            "n": len(edge_roi),
            "spearman_edge_vs_r_over_i": spearman([e for e, _ in edge_roi], [y for _, y in edge_roi]),
            "r_over_i_by_edge_bucket": {k: _quart(v) for k, v in sorted(edge_groups.items())},
        },
        "r_over_i": _quart(r.get("r_over_i_b2") for r in priced),
        "crush_post_over_pre": {x: _quart(r.get(f"crush_{x}") for r in priced) for x in EXITS},
        "width_over_straddle": {n: _quart((r.get(f"fly{n}") or {}).get("width_over_straddle") for r in priced)
                                for n in WIDTHS},
        "wing_calibration": calibrate_wings(priced_all),
        "long_straddle_in_buy_zone": _stats([(-r["short_straddle_pnl_b2_usd"], r["straddle_entry"] * 100.0) for r in buy]),
        "limits": [
            "prices are last trades in 30-minute bars, not quotes: no bid-ask cost, prints can be stale",
            "wings are priced by a model from the at-the-money straddle (multiplier calibrated on real wing prints)",
            "the spread gate and the news gate cannot be replayed",
            "one contract per event, filled at the printed prices",
        ],
    }
