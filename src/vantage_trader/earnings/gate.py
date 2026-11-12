"""The entry gate in code (proposals P004 and P011).

One candidate in, one decision record out. Every rule from RULES_CHANGELOG v1.1 to v1.7 and
the 2026-11-11 decisions is checked separately and reported with its number, its limit and
pass/fail, so the decision can be compared line by line with the manual gate. A
disagreement between this record and the manual gate blocks the entry until explained.

Candidate (the compact shape the analysts already produce)::

    {"symbol", "timing"?, "spot", "prev_close", "K",
     "call": {"bid", "ask"}, "put": {"bid", "ask"},              # body strike K
     "wings"?: {"call_strike", "put_strike", "call": {"bid", "ask"}, "put": {"bid", "ask"}},
     "hist_moves": [signed fractions, oldest first], "regime_20d",
     "flags"?: [risk-sentinel flags] or {"name": true|false},
     "sector_same_direction"?: bool, "macro_veto"?: bool|str, "circuit_breaker"?: bool|str,
     "sector"?: str, "sectors_entered_today"?: [str], "tick"?: float,
     "account_value", "open_risk_usd",
     "buying_power",                               # get_portfolio buying power now (gate 16)
     "held"?: {"quantity", "max_loss_usd", "K"},   # contracts already open on this name (an add)
     "phase"?: "early" | "final"}                  # the CLI fills it from the clock when absent

``open_risk_usd`` is max loss PLUS exit reserves of every position already open (earnings
and non-earnings), as positions.json records them. It includes the tranche in ``held``.

Implied move (P011). On a coarse strike grid the body strike K sits off the money and its
straddle holds intrinsic value, which overstates the implied move. The body straddle is
converted to its at-the-money equivalent first, as replay.py does:
    sigma = implied_sigma(spot, K, body_straddle_mid)
    atm   = straddle(spot, spot, sigma)
    implied_move = straddle_factor (0.85) x atm / spot
    edge_ratio   = mean(|hist_moves|) / implied_move

Gates (all evaluated; ``reason`` is the first failure, ``blocked_by`` lists all):
     1 blocklist          never TSLA (config blocklist)
     2 price              spot >= $10
     3 history            >= 4 past earnings moves
     4 edge_ratio         <= 0.85; >= 1.25 -> "long_straddle_off" (never a buy)
     5 atm_spread         worse of the call, put and straddle (ask-bid)/mid <= 25%
     6 regime             regime_20d < 1.25 x average past earnings move
     7 intraday           |spot/prev_close - 1| <= 5%; 5-7% only with sector_same_direction
                          true and no stock-news flag; above 7% blocks
     8 news               no stock-specific flag ("big_intraday_move" is a price fact covered
                          by gate 7, not news)
     9 macro_veto         blocks when set
    10 circuit_breaker    blocks when set, when account value < $400, or on the journal's
                          loss streaks (2 max losses or 3 losses in a row)
    11 sector             blocks when ``sector`` is in ``sectors_entered_today`` (only
                          checked when both are given)
    12 structure          wings present, K-put_strike > 0, call_strike-K > 0, 0 < mid credit
                          < width, a fillable limit range (floor <= start)
    13 add_centered       an add only: same body strike as the held tranche, and spot
                          within 0.25 x body straddle of it. A first entry passes.
    14 name_risk          max loss on the name (held + the contracts entered now, at the
                          credit floor) <= $350, and at least one contract may be entered now
    15 risk_budget        open_risk_usd + max loss at the floor + exit reserve <= the cap
                          min($1,000, 0.93 x account value)
    16 exit_feasible      v1.9: the position must be closable with single-leg orders. One
                          in-the-money short leg with the stock at its wing costs about
                          wing width x 100 (x exit_buyback_mult 1.1 for time value); that
                          must fit the buying power left after the entry
                          (buying_power - contracts x max loss at the floor). Contracts are
                          cut to what fits; no buying_power given = blocked.

Max loss is checked at the credit FLOOR max(natural, 0.92 x mid) of the fly, the worst
price the execution rules accept; ``max_loss_mid`` is reported next to it. The exit reserve
is $50 per earnings contract (the narrower $10 reserve applies to non-earnings flies).

Contracts (v1.7 and v1.8, sizing.plan): sized by risk. The name's target is 20% of account value
(never above $350). ``contracts`` is what may be entered at this check-in,
``contracts_planned`` what the name may still add in total, ``contracts_later`` the part
that waits for the final window (from 11:30 PT). Before the final window a name carries at
most half its target; one contract is always allowed on a name with nothing held.
Band: a label only since v1.5 ("tight" edge <= 0.70, "final_sweep" 0.70 to 0.85, "no_edge").

Exit code (CLI): 0 when the candidate may be entered, 3 when blocked, 2 on bad input.
Nothing here places orders or reads the market.
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any

from . import journal as jr
from . import pricing, rules, sizing
from .config import EngineInputError, cancel_by_la_minutes, norm_symbol
from .projection import implied_sigma, straddle

NEWS_EXEMPT_FLAGS = {"big_intraday_move"}
EPS = 1e-9


# ---------------------------------------------------------------- shared helpers

def atm_implied_move(spot: float, strike: float, straddle_mid: float, factor: float) -> dict[str, Any]:
    """P011: implied move from the at-the-money-equivalent straddle of the body strike.

    Returns raw and at-the-money straddle as a share of spot, sigma (total stdev) and
    ``implied_move`` (factor x atm / spot). ``implied_move`` is None when the body straddle
    is at or below intrinsic value (the quotes cannot be right).
    """
    out: dict[str, Any] = {"straddle_mid": round(straddle_mid, 6),
                           "straddle_pct_raw": round(straddle_mid / spot, 6),
                           "body_offset_pct": round(strike / spot - 1.0, 6),
                           "sigma": None, "atm_straddle_pct": None, "implied_move": None,
                           "implied_move_raw": round(factor * straddle_mid / spot, 6)}
    sigma = implied_sigma(spot, strike, straddle_mid)
    if sigma is None:
        return out
    atm = straddle(spot, spot, sigma)
    out.update(sigma=round(sigma, 6), atm_straddle_pct=round(atm / spot, 6),
               implied_move=round(factor * atm / spot, 6))
    return out


def edge_band(ratio: float | None, cfg: dict[str, Any]) -> str | None:
    if ratio is None:
        return None
    if ratio >= cfg["buy_min_ratio"] - EPS:
        return "long_straddle_off"
    if ratio <= cfg["tight_max_ratio"] + EPS:
        return "tight"
    if ratio <= cfg["sell_max_ratio"] + EPS:
        return "final_sweep"
    return "no_edge"


def spread_pcts(call: tuple[float, float], put: tuple[float, float]) -> dict[str, float]:
    """(ask-bid)/mid for the call, the put and the straddle; ``worst`` is the max of the three."""
    def pct(bid: float, ask: float) -> float:
        mid = (bid + ask) / 2.0
        return float("inf") if mid <= 0 else (ask - bid) / mid

    c, p = pct(*call), pct(*put)
    s = pct(call[0] + put[0], call[1] + put[1])
    return {"call": c, "put": p, "straddle": s, "worst": max(c, p, s)}


def intraday_verdict(move: float, sector_same_direction: bool, news_flags: list[str],
                     cfg: dict[str, Any]) -> tuple[bool, str]:
    a = abs(move)
    if a <= cfg["max_intraday_move"] + EPS:
        return True, "within_base_limit"
    if a <= cfg["max_intraday_move_sector"] + EPS:
        if sector_same_direction is True and not news_flags:
            return True, "sector_band_ok"
        return False, "sector_band_needs_sector_move_and_no_news"
    return False, "above_sector_band"


def news_flags(flags: list[str]) -> list[str]:
    return [f for f in flags if f not in NEWS_EXEMPT_FLAGS]


# ---------------------------------------------------------------- input parsing

def _num(v: Any, what: str, positive: bool = False, nonneg: bool = False) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EngineInputError(f"{what} must be a number, got {v!r}")
    if positive and v <= 0:
        raise EngineInputError(f"{what} must be > 0")
    if nonneg and v < 0:
        raise EngineInputError(f"{what} must be >= 0")
    return float(v)


def _quote(raw: Any, what: str) -> tuple[float, float]:
    if not isinstance(raw, dict):
        raise EngineInputError(f"{what} must be an object with bid and ask")
    bid, ask = _num(raw.get("bid"), f"{what}.bid", nonneg=True), _num(raw.get("ask"), f"{what}.ask", nonneg=True)
    if ask < bid:
        raise EngineInputError(f"{what}: ask below bid")
    return bid, ask


def _flag_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        if not all(isinstance(f, str) for f in raw):
            raise EngineInputError("flags must be a list of strings")
        return [f for f in raw if f.strip()]
    if isinstance(raw, dict):
        return [str(k) for k, v in raw.items() if v]
    raise EngineInputError("flags must be a list of strings or an object of booleans")


def _set_flag(v: Any, what: str) -> tuple[bool, str | None]:
    """A veto input: null/false -> not set; true or a non-empty string -> set (string = reason)."""
    if v is None or v is False:
        return False, None
    if v is True:
        return True, None
    if isinstance(v, str):
        return (bool(v.strip()), v.strip() or None)
    raise EngineInputError(f"{what} must be true/false or a reason string")


def parse_candidate(c: Any) -> dict[str, Any]:
    if not isinstance(c, dict):
        raise EngineInputError("candidate must be a JSON object")
    sym = norm_symbol(c.get("symbol"))
    if not isinstance(c.get("symbol"), str) or not sym:
        raise EngineInputError("symbol required")
    hm = c.get("hist_moves")
    if not isinstance(hm, list):
        raise EngineInputError("hist_moves must be a list")
    out: dict[str, Any] = {
        "symbol": sym, "timing": c.get("timing"),
        "spot": _num(c.get("spot"), "spot", positive=True),
        "prev_close": _num(c.get("prev_close"), "prev_close", positive=True),
        "K": _num(c.get("K"), "K", positive=True),
        "call": _quote(c.get("call"), "call"), "put": _quote(c.get("put"), "put"),
        "hist_moves": [_num(m, "hist_moves[]") for m in hm],
        "regime_20d": _num(c.get("regime_20d"), "regime_20d", nonneg=True),
        "flags": _flag_list(c.get("flags")),
        "account_value": _num(c.get("account_value"), "account_value"),
        "open_risk_usd": _num(c.get("open_risk_usd"), "open_risk_usd", nonneg=True),
    }
    ssd = c.get("sector_same_direction", False)
    if ssd is not None and not isinstance(ssd, bool):
        raise EngineInputError("sector_same_direction must be true/false")
    out["sector_same_direction"] = bool(ssd)
    for key in ("macro_veto", "circuit_breaker"):
        out[key] = _set_flag(c.get(key), key)
    if c.get("tick") is not None:
        out["tick"] = _num(c["tick"], "tick", positive=True)
    sector, entered = c.get("sector"), c.get("sectors_entered_today")
    if sector is not None and not isinstance(sector, str):
        raise EngineInputError("sector must be a string")
    if entered is not None and not (isinstance(entered, list) and all(isinstance(s, str) for s in entered)):
        raise EngineInputError("sectors_entered_today must be a list of strings")
    out["sector"], out["sectors_entered_today"] = sector, entered
    held = c.get("held")
    if held is not None:
        if not isinstance(held, dict):
            raise EngineInputError("held must be an object with quantity, max_loss_usd and K")
        hq = _num(held.get("quantity"), "held.quantity", positive=True)
        if not float(hq).is_integer():
            raise EngineInputError("held.quantity must be a whole number")
        out["held"] = {"quantity": int(hq),
                       "max_loss_usd": _num(held.get("max_loss_usd"), "held.max_loss_usd", nonneg=True),
                       "K": _num(held.get("K"), "held.K", positive=True)}
    else:
        out["held"] = None
    phase = c.get("phase")
    if phase is not None and phase not in ("early", "final"):
        raise EngineInputError("phase must be 'early' or 'final'")
    out["phase"] = phase
    out["buying_power"] = (None if c.get("buying_power") is None
                           else _num(c.get("buying_power"), "buying_power", nonneg=True))
    w = c.get("wings")
    if w is not None:
        if not isinstance(w, dict):
            raise EngineInputError("wings must be an object")
        out["wings"] = {"call_strike": _num(w.get("call_strike"), "wings.call_strike", positive=True),
                        "put_strike": _num(w.get("put_strike"), "wings.put_strike", positive=True),
                        "call": _quote(w.get("call"), "wings.call"), "put": _quote(w.get("put"), "wings.put")}
    else:
        out["wings"] = None
    return out


# ---------------------------------------------------------------- the fly

def _mid(q: tuple[float, float]) -> float:
    return (q[0] + q[1]) / 2.0


def fly(c: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Credit, max loss and breakevens of the iron fly, per contract. None without wings."""
    w = c["wings"]
    if w is None:
        return None
    k = c["K"]
    width_call, width_put = w["call_strike"] - k, k - w["put_strike"]
    width = max(width_call, width_put)
    mid = _mid(c["call"]) + _mid(c["put"]) - _mid(w["call"]) - _mid(w["put"])
    natural = c["call"][0] + c["put"][0] - w["call"][1] - w["put"][1]
    floor_credit = max(natural, cfg["credit_floor_mid_frac"] * mid)
    tick = c.get("tick", cfg["tick"])
    start = pricing.round_nearest(mid, tick) if mid > 0 else None
    floor_rounded = pricing.round_up(floor_credit, tick) if floor_credit > 0 else None
    return {
        "body": k, "call_wing": w["call_strike"], "put_wing": w["put_strike"],
        "width_call": round(width_call, 4), "width_put": round(width_put, 4), "width": round(width, 4),
        # v1.6 (P018): the wings should sit about 1.5x the body straddle from the body
        "width_over_straddle": (round(width / (_mid(c["call"]) + _mid(c["put"])), 4)
                                if _mid(c["call"]) + _mid(c["put"]) > 0 else None),
        "credit_mid": round(mid, 4), "credit_natural": round(natural, 4),
        "credit_floor": round(floor_credit, 4),
        "limit_start": start, "limit_floor": floor_rounded, "tick": tick,
        "limit_step": pricing.limit_step(start, cfg) if start else None,
        "max_loss_mid": round((width - mid) * 100.0, 2),
        "max_loss_natural": round((width - natural) * 100.0, 2),
        "max_loss_floor": round((width - floor_credit) * 100.0, 2),
        "max_profit_mid": round(mid * 100.0, 2),
        "breakevens_mid": [round(k - mid, 4), round(k + mid, 4)],
        "valid": bool(width_call > 0 and width_put > 0 and 0 < mid < width and natural < width),
        "fillable": bool(start is not None and floor_rounded is not None and floor_rounded <= start + EPS
                         and start < width),
    }


# ---------------------------------------------------------------- the gate

def phase_now(cfg: dict[str, Any], now: datetime | None = None) -> str:
    """"final" from final_window_start (11:30 PT) on, "early" before it. Used when the candidate gives no phase."""
    from zoneinfo import ZoneInfo
    la = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/Los_Angeles"))
    return "final" if la.hour * 60 + la.minute >= cancel_by_la_minutes(cfg["final_window_start"]) else "early"


def evaluate(raw: Any, cfg: dict[str, Any], journal_events: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], int]:
    c = parse_candidate(raw)
    events = journal_events or []
    spot, k = c["spot"], c["K"]
    gates: list[dict[str, Any]] = []

    def add(name: str, passed: bool | None, value: Any = None, limit: Any = None, note: str | None = None,
            reason: str | None = None) -> None:
        gates.append({"n": len(gates) + 1, "gate": name, "pass": passed, "value": value, "limit": limit,
                      "note": note, "reason": None if passed else (reason or name)})

    # metrics
    moves = c["hist_moves"][-cfg["history_lookback"]:]
    avg = round(mean(abs(m) for m in moves), 6) if moves else None
    body_straddle = _mid(c["call"]) + _mid(c["put"])
    im = atm_implied_move(spot, k, body_straddle, cfg["straddle_factor"]) if body_straddle > 0 else None
    implied = im["implied_move"] if im else None
    edge = round(avg / implied, 6) if avg is not None and implied else None
    band = edge_band(edge, cfg)
    sp = spread_pcts(c["call"], c["put"])
    intraday = c["spot"] / c["prev_close"] - 1.0
    nflags = news_flags(c["flags"])
    f = fly(c, cfg)

    # 1-3
    add("blocklist", c["symbol"] not in cfg["blocklist"], c["symbol"], cfg["blocklist"], reason="blocklisted")
    add("price", spot >= cfg["min_price"] - EPS, spot, cfg["min_price"], reason="price_below_min")
    add("history", len(moves) >= cfg["min_history"], len(moves), cfg["min_history"], reason="insufficient_history")
    # 4 edge
    if edge is None:
        add("edge_ratio", False, None, cfg["sell_max_ratio"],
            note="no implied move: body straddle at or below intrinsic, or no history",
            reason="bad_quotes" if implied is None else "insufficient_history")
    else:
        add("edge_ratio", band in ("tight", "final_sweep"), round(edge, 4), cfg["sell_max_ratio"],
            note=f"band {band}", reason="long_straddle_off" if band == "long_straddle_off" else "no_edge")
    # 5 spread
    add("atm_spread", sp["worst"] <= cfg["max_spread_pct"] + EPS, round(sp["worst"], 4), cfg["max_spread_pct"],
        note=(f"straddle {sp['straddle']:.4f}, call {sp['call']:.4f}, put {sp['put']:.4f}; "
              f"above {cfg['wide_spread_pct']} the ${cfg['wide_spread_max_loss']:.0f} max-loss cap applies"),
        reason="spread_too_wide")
    # 6 regime
    if avg:
        regime_limit = round(cfg["regime_mult"] * avg, 6)
        add("regime", c["regime_20d"] < regime_limit - EPS, c["regime_20d"], regime_limit,
            note=f"ratio {c['regime_20d'] / avg:.4f} (must be < {cfg['regime_mult']})", reason="regime_guard")
    else:
        add("regime", False, c["regime_20d"], None, note="no history", reason="regime_guard")
    # 7 intraday
    ok, why = intraday_verdict(intraday, c["sector_same_direction"], nflags, cfg)
    add("intraday", ok, round(intraday, 6), [cfg["max_intraday_move"], cfg["max_intraday_move_sector"]],
        note=f"{why}; sector_same_direction={c['sector_same_direction']}", reason="intraday_move_too_large")
    # 8 news
    add("news", not nflags, nflags, [], note=("ignored: " + ",".join(sorted(set(c["flags"]) - set(nflags))))
        if set(c["flags"]) - set(nflags) else None, reason="flagged:" + ",".join(nflags))
    # 9 macro
    mv, mreason = c["macro_veto"]
    add("macro_veto", not mv, mv, False, note=mreason, reason="macro_veto")
    # 10 circuit breaker
    cb = rules.circuit_breaker({"total_value": c["account_value"]}, events, cfg)
    cbi, cbreason = c["circuit_breaker"]
    cb_reasons = list(cb["reasons"]) + (["input: " + (cbreason or "set")] if cbi else [])
    add("circuit_breaker", not cb_reasons, cb_reasons, [], reason="circuit_breaker")
    # 11 sector
    if c["held"] is not None:
        add("sector", True, c["sector"], c["sectors_entered_today"],
            note="an add to a name already open: the one-name-per-sector rule does not apply")
    elif c["sector"] is not None and c["sectors_entered_today"] is not None:
        clash = c["sector"].strip().lower() in {s.strip().lower() for s in c["sectors_entered_today"]}
        add("sector", not clash, c["sector"], c["sectors_entered_today"], reason="same_sector_today")
    else:
        add("sector", True, c["sector"], c["sectors_entered_today"],
            note="not checked: give sector and sectors_entered_today")
    # 12 structure
    if f is None:
        add("structure", False, None, None, note="no wings given", reason="no_wings")
    else:
        add("structure", f["valid"] and f["fillable"], {"credit_mid": f["credit_mid"], "width": f["width"]},
            None, note=None if f["valid"] else "wings or credit out of range",
            reason="no_valid_wings" if not f["valid"] else "no_fillable_limit_range")

    # sizing and caps (v1.7: by risk, in tranches)
    closed = len(jr.closed_trades(events))
    cap = sizing.risk_cap(c["account_value"], cfg)
    budget = sizing.risk_budget(c["account_value"], c["open_risk_usd"], cfg)
    reserve = cfg["exit_slippage_reserve"]
    wide = sp["worst"] > cfg["wide_spread_pct"] + EPS
    held = c["held"]
    held_qty = held["quantity"] if held else 0
    held_ml = held["max_loss_usd"] if held else 0.0
    phase = c["phase"] or "early"      # no phase given: the smaller, early size
    ml_unit = f["max_loss_floor"] if f is not None and f["valid"] and f["max_loss_floor"] > 0 else None
    # above the 12% spread band the name cap is the tighter of the two limits (both $350 today)
    name_cap = min(cfg["name_risk_cap"], cfg["wide_spread_max_loss"]) if wide else cfg["name_risk_cap"]
    plan = sizing.plan(ml_unit, reserve, c["account_value"], c["open_risk_usd"],
                       dict(cfg, name_risk_cap=name_cap),
                       held_qty=held_qty, held_max_loss=held_ml, phase=phase)
    qty = plan["now"]
    # 16 exit feasibility (v1.9), worked out here because it can cut the contract count.
    # Multi-leg orders are refused for the agent, so an exit buys back each short leg alone.
    # With the stock between the body and a wing the in-the-money short costs up to the wing
    # width; that buyback must fit the buying power that is left once this entry is on.
    bp = c["buying_power"]
    exit_need = exit_room = n_exit = None
    if ml_unit is not None and bp is not None:
        exit_need = round(max(cfg["exit_buyback_mult"], 1.0) * f["width"] * 100.0, 2)
        n_exit = int((bp - exit_need) // ml_unit) if bp >= exit_need else 0
        if qty > n_exit:
            plan = dict(plan, now=max(n_exit, 0), later=max(plan["planned"] - max(n_exit, 0), 0),
                        limits=dict(plan["limits"], exit_feasible=n_exit),
                        binding="exit_not_feasible" if n_exit < 1 else plan["binding"])
            qty = plan["now"]
        exit_room = round(bp - max(qty, 1) * ml_unit, 2)
    q_eval = max(qty, 1)
    ml_floor = round(ml_unit * q_eval, 2) if ml_unit is not None else None
    # 13 add centered
    if held is None:
        add("add_centered", True, None, None, note="first entry on this name")
    else:
        off = abs(spot - k)
        room = round(cfg["add_center_frac"] * body_straddle, 4)
        same_body = abs(k - held["K"]) <= EPS
        add("add_centered", same_body and off <= room + EPS, round(off, 4), room,
            note=(f"held body {held['K']}, this body {k}; spot must sit within "
                  f"{cfg['add_center_frac']} x the body straddle of it"),
            reason="add_off_center" if same_body else "add_different_body")
    # 14 name risk
    name_ml = None if ml_floor is None else round(held_ml + ml_floor, 2)
    add("name_risk", name_ml is not None and name_ml <= name_cap + EPS and qty >= 1,
        name_ml, name_cap,
        note=(f"target {plan['target']} (phase {phase}): planned {plan['planned']} more, {plan['now']} now, "
              f"{plan['later']} later; held {held_qty} with max loss {held_ml}"
              + (f"; spread above {cfg['wide_spread_pct']}" if wide else "")),
        reason=("name_risk_cap" if name_ml is not None and name_ml > name_cap + EPS
                else (plan["binding"] or "name_risk_cap")))
    # 15 risk budget
    need = None if ml_floor is None else round(ml_floor + reserve * q_eval, 2)
    add("risk_budget", need is not None and need <= budget + EPS, need, budget,
        note=f"cap {cap} - open risk {c['open_risk_usd']} = {budget}; needs max loss at floor + "
             f"${reserve:.0f} reserve per contract", reason="max_loss_exceeds_cap")

    # 16 exit feasible
    add("exit_feasible",
        exit_need is not None and n_exit is not None and n_exit >= 1 and exit_need <= exit_room + EPS,
        exit_need, exit_room,
        note=("buying_power not given: take it from get_portfolio" if bp is None else
              (f"one in-the-money short leg at the wing costs about {exit_need} "
               f"({cfg['exit_buyback_mult']} x width x 100); buying power {bp} less the entry leaves "
               f"{exit_room}; at most {n_exit} contract(s) fit" if exit_need is not None else
               "no valid fly to check")),
        reason="buying_power_missing" if bp is None else "exit_not_feasible")

    failures = [g for g in gates if not g["pass"]]
    action = "no_trade" if failures else "sell"
    record: dict[str, Any] = {
        "symbol": c["symbol"], "timing": c["timing"], "action": action,
        "reason": failures[0]["reason"] if failures else "passes: may be entered at any check-in on its entry day (v1.5)",
        "blocked_by": list(dict.fromkeys(g["reason"] for g in failures)),
        "band": band,
        "metrics": {
            "spot": spot, "prev_close": c["prev_close"], "K": k, "intraday_move": round(intraday, 6),
            "avg_hist_move": avg, "n_hist": len(moves), "implied": im,
            "implied_move": implied, "edge_ratio": None if edge is None else round(edge, 4),
            "spread_pct": {k2: round(v, 4) for k2, v in sp.items()},
            "regime_20d": c["regime_20d"],
            "regime_ratio": round(c["regime_20d"] / avg, 4) if avg else None,
        },
        "gates": gates,
        "fly": f,
        "contracts": qty if action == "sell" else 0,
        "contracts_planned": plan["planned"] if action == "sell" else 0,
        "contracts_later": plan["later"] if action == "sell" else 0,
        "sizing": plan,
        "closed_live_trades": closed,
        "max_loss": {"mid": round(f["max_loss_mid"] * q_eval, 2),
                     "natural": round(f["max_loss_natural"] * q_eval, 2),
                     "floor": ml_floor, "per_contract_floor": ml_unit,
                     "name_total_floor": name_ml} if f else None,
        "breakevens": f["breakevens_mid"] if f else None,
        "risk": {
            "risk_cap": cap, "open_risk_usd": c["open_risk_usd"], "budget_before": budget,
            "exit_reserve_per_contract": reserve,
            "spread_band_cap": cfg["wide_spread_max_loss"] if wide else None,
            "name_risk_cap": name_cap, "name_target": plan["target"],
            "this_trade_usd": need if action == "sell" else 0.0,
            "budget_left": round(budget - (need if action == "sell" else 0.0), 2),
        },
    }
    return record, 0 if action == "sell" else 3
