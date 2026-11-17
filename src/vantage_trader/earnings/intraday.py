"""The same-day pilot gate (proposal P017, rules v1.15).

The owner, 2026-11-16: "Push the day trading pilot" and "Dont need a decision on me. Remember,
self healing and strengthening the model with your own decision making".

The trade: an iron fly on an index fund in options that expire today. Short the call and the
put at the strike nearest the price, long one wing each side at the listed strikes nearest one
body straddle away. One contract, one fly a day, entered in the morning window, flat by the
time stop. Defined risk, limit orders, single-leg execution (wings first on entry, shorts
first on exit), never TSLA.

Two tiers:
    signal   the premium ratio sits inside the configured band (``intraday_signal_*``); the fly
             may carry up to ``intraday_max_loss``. Off until a band has passed its test.
    probe    no signal needed; the smallest fly (``intraday_probe_names``, max loss up to
             ``intraday_probe_max_loss``). It buys execution data and a live record at a
             known, small price.

Premium ratio: (body straddle mid / spot) / mean |move from the entry time to the close| over
the last ``intraday_lookback`` sessions. Recorded on every candidate, whichever tier it is.

Candidate::

    {"symbol", "spot", "prev_close", "K", "expiry": "YYYY-MM-DD",
     "call": {"bid", "ask"}, "put": {"bid", "ask"},                 # body strike K
     "wings": {"call_strike", "put_strike", "call": {"bid", "ask"}, "put": {"bid", "ask"}},
     "same_hours_moves": [signed fractions, oldest first],          # entry time -> close, per session
     "event_ahead"?: bool|str,       # a tier-1 release or a Fed decision still to come before the time stop
     "exits_pending"?: bool|str,     # a position due to close this morning is still open (also one
                                     # waiting on the owner's own closing order)
     "macro_veto"?: bool|str, "circuit_breaker"?: bool|str,
     "account_value", "open_risk_usd", "buying_power",
     "open_intraday"?: int, "entries_today"?: int,
     "today"?: "YYYY-MM-DD", "now_pt"?: "HH:MM"}                    # filled from the clock when absent

Gates (all evaluated; ``reason`` is the first failure, ``blocked_by`` lists all):
     1 enabled            intraday_live_enabled ("day trades paper" switches the line off)
     2 universe           never TSLA or a blocklisted name; only intraday_live_names
     3 same_day_expiry    the options expire today
     4 window             now inside the entry window
     5 history            at least intraday_lookback same-hours moves
     6 atm_spread         body straddle (ask-bid)/mid <= intraday_max_spread_pct
     7 pre_move           |spot / prev_close - 1| <= intraday_max_pre_move
     8 event_ahead        blocks when set
     9 macro_veto         blocks when set, hard or soft
    10 circuit_breaker    the account breaker (account floor, loss streaks of the main line)
    11 pilot_breaker      the pilot's own: cumulative loss limit or losses in a row
    12 structure          wings listed both sides, 0 < credit < width, wings between
                          intraday_min/max_wing_over_straddle x the body straddle, body centered
    13 tier               signal (ratio in band, max loss <= intraday_max_loss) or probe
                          (probe name, max loss <= intraday_probe_max_loss)
    14 one_a_day          nothing open in the pilot, fewer than intraday_max_entries_per_day today
    15 risk_budget        max loss at the credit floor + the exit reserve fits the total risk cap
    16 exit_feasible      exit_buyback_mult x width x 100 fits the buying power left after entry
    17 morning_exits      no position due to close this morning is still open: exits come first

Exit plan in the record: take profit when the fly can be bought back for
credit x (1 - intraday_take_profit_frac); no stop unless intraday_cut_frac is set (the wings are
the stop); flat at intraday_time_stop.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from . import journal as jr
from . import rules, sizing
from .config import EngineInputError, cancel_by_la_minutes, norm_symbol

EPS = 1e-9
LA = ZoneInfo("America/Los_Angeles")
PILOT_KIND = jr.PILOT_KIND


# ---------------------------------------------------------------- the pilot's own record

def pilot_trades(events: list[dict[str, Any]], since_ts: str | None = None) -> list[dict[str, Any]]:
    """Closed same-day pilot trades from the journal, oldest first."""
    out = [t for t in jr.closed_trades(events) if jr.is_pilot(t)]
    if since_ts:
        out = [t for t in out if str(t.get("exit_ts") or "") >= since_ts]
    return sorted(out, key=lambda t: str(t.get("exit_ts") or ""))


def pilot_state(events: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    """The pilot's breaker. A trade with no known result counts as a loss of its max loss."""
    trades = pilot_trades(events, cfg.get("intraday_pilot_reset_ts"))
    total = 0.0
    for t in trades:
        if t["pnl"] is None:
            total -= float(t.get("max_loss") or 0.0)
        else:
            total += float(t["pnl"])
    streak = 0
    for t in reversed(trades):
        if jr.is_loss(t):
            streak += 1
        else:
            break
    reasons = []
    if total <= -cfg["intraday_pilot_loss_limit"] + EPS:
        reasons.append(f"pilot result {total:.2f} at or under -{cfg['intraday_pilot_loss_limit']:.0f}")
    if streak >= cfg["intraday_max_consecutive_losses"]:
        reasons.append(f"{streak} pilot losses in a row")
    wins = sum(1 for t in trades if not jr.is_loss(t))
    return {"trades": len(trades), "wins": wins, "pnl_usd": round(total, 2), "consecutive_losses": streak,
            "paused": bool(reasons), "reasons": reasons,
            "review_due": len(trades) >= cfg["intraday_review_after_trades"],
            "since": cfg.get("intraday_pilot_reset_ts")}


# ---------------------------------------------------------------- numbers

def premium_ratio(straddle_mid: float, spot: float, moves: list[float], lookback: int) -> float | None:
    """(straddle / spot) over the mean absolute same-hours move of the last ``lookback`` sessions."""
    use = [abs(m) for m in moves[-lookback:]]
    if len(use) < lookback or spot <= 0:
        return None
    avg = mean(use)
    return None if avg <= 0 else round((straddle_mid / spot) / avg, 4)


def _num(v: Any, what: str, positive: bool = False, nonneg: bool = False) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        raise EngineInputError(f"{what} must be a number")
    v = float(v)
    if positive and v <= 0:
        raise EngineInputError(f"{what} must be > 0")
    if nonneg and v < 0:
        raise EngineInputError(f"{what} must be >= 0")
    return v


def _quote(raw: Any, what: str) -> tuple[float, float]:
    if not isinstance(raw, dict):
        raise EngineInputError(f"{what} must be an object with bid and ask")
    bid, ask = _num(raw.get("bid"), f"{what}.bid", nonneg=True), _num(raw.get("ask"), f"{what}.ask", positive=True)
    if ask < bid:
        raise EngineInputError(f"{what}: ask below bid")
    return bid, ask


def _set_flag(v: Any, what: str) -> tuple[bool, str | None]:
    if v is None or v is False:
        return False, None
    if v is True:
        return True, None
    if isinstance(v, str):
        return (bool(v.strip()), v.strip() or None)
    raise EngineInputError(f"{what} must be true, false or a reason string")


def _count(v: Any, what: str) -> int:
    if v is None:
        return 0
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise EngineInputError(f"{what} must be a whole number >= 0")
    return v


def _mid(q: tuple[float, float]) -> float:
    return (q[0] + q[1]) / 2.0


def _hhmm(text: Any, what: str) -> int:
    try:
        hh, mm = str(text).strip().split(":")
        h, m = int(hh), int(mm)
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError
    except ValueError:
        raise EngineInputError(f"{what} must look like HH:MM")
    return h * 60 + m


def parse_candidate(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise EngineInputError("candidate must be a JSON object")
    sym = norm_symbol(raw.get("symbol"))
    if not sym:
        raise EngineInputError("candidate.symbol is required")
    wings = raw.get("wings")
    w = None
    if wings is not None:
        if not isinstance(wings, dict):
            raise EngineInputError("candidate.wings must be an object")
        w = {"call_strike": _num(wings.get("call_strike"), "wings.call_strike", positive=True),
             "put_strike": _num(wings.get("put_strike"), "wings.put_strike", positive=True),
             "call": _quote(wings.get("call"), "wings.call"), "put": _quote(wings.get("put"), "wings.put")}
    moves = raw.get("same_hours_moves", [])
    if not isinstance(moves, list):
        raise EngineInputError("candidate.same_hours_moves must be a list of fractions")
    moves = [_num(m, "same_hours_moves entry") for m in moves]
    if any(abs(m) > 0.5 for m in moves):
        raise EngineInputError("same_hours_moves must be fractions (0.004 = 0.4%)")
    bp = raw.get("buying_power")
    return {
        "symbol": sym,
        "spot": _num(raw.get("spot"), "candidate.spot", positive=True),
        "prev_close": _num(raw.get("prev_close"), "candidate.prev_close", positive=True),
        "K": _num(raw.get("K"), "candidate.K", positive=True),
        "expiry": str(raw.get("expiry") or ""),
        "today": None if raw.get("today") is None else str(raw.get("today")),
        "now_pt": None if raw.get("now_pt") is None else _hhmm(raw.get("now_pt"), "candidate.now_pt"),
        "call": _quote(raw.get("call"), "candidate.call"),
        "put": _quote(raw.get("put"), "candidate.put"),
        "wings": w,
        "moves": moves,
        "event_ahead": _set_flag(raw.get("event_ahead"), "candidate.event_ahead"),
        "exits_pending": _set_flag(raw.get("exits_pending"), "candidate.exits_pending"),
        "macro_veto": _set_flag(raw.get("macro_veto"), "candidate.macro_veto"),
        "circuit_breaker": _set_flag(raw.get("circuit_breaker"), "candidate.circuit_breaker"),
        "account_value": _num(raw.get("account_value"), "candidate.account_value", positive=True),
        "open_risk_usd": _num(raw.get("open_risk_usd"), "candidate.open_risk_usd", nonneg=True),
        "buying_power": None if bp is None else _num(bp, "candidate.buying_power", nonneg=True),
        "open_intraday": _count(raw.get("open_intraday"), "candidate.open_intraday"),
        "entries_today": _count(raw.get("entries_today"), "candidate.entries_today"),
    }


def fly(c: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any] | None:
    """The fly's numbers. The credit floor is the worse of the natural credit and
    credit_floor_mid_frac x mid, never below the natural: on penny-wide contracts it is the natural."""
    w = c["wings"]
    if w is None:
        return None
    k = c["K"]
    body_mid = _mid(c["call"]) + _mid(c["put"])
    wing_mid = _mid(w["call"]) + _mid(w["put"])
    mid = body_mid - wing_mid
    natural = c["call"][0] + c["put"][0] - w["call"][1] - w["put"][1]
    width_call, width_put = w["call_strike"] - k, k - w["put_strike"]
    width = max(width_call, width_put)
    floor = max(natural, math.floor(cfg["credit_floor_mid_frac"] * mid * 100.0 + EPS) / 100.0)
    valid = bool(width_call > 0 and width_put > 0 and 0 < mid < width and 0 < floor < width)
    narrow = min(width_call, width_put)
    return {
        "strikes": [w["put_strike"], k, w["call_strike"]],
        "width": round(width, 4), "width_call": round(width_call, 4), "width_put": round(width_put, 4),
        "body_straddle_mid": round(body_mid, 4),
        "credit_mid": round(mid, 4), "credit_natural": round(natural, 4), "credit_floor": round(floor, 4),
        "max_loss_mid": round((width - mid) * 100.0, 2), "max_loss_floor": round((width - floor) * 100.0, 2),
        "max_profit_mid": round(mid * 100.0, 2),
        "breakevens_mid": [round(k - mid, 4), round(k + mid, 4)],
        "wing_over_straddle": [round(narrow / body_mid, 4), round(width / body_mid, 4)] if body_mid > 0 else None,
        "valid": valid,
    }


def clock(cfg: dict[str, Any], now: datetime | None = None) -> tuple[str, int]:
    la = (now or datetime.now(timezone.utc)).astimezone(LA)
    return la.strftime("%Y-%m-%d"), la.hour * 60 + la.minute


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ---------------------------------------------------------------- the gate

def evaluate(raw: Any, cfg: dict[str, Any], journal_events: list[dict[str, Any]] | None = None,
             now: datetime | None = None) -> tuple[dict[str, Any], int]:
    c = parse_candidate(raw)
    events = journal_events or []
    gates: list[dict[str, Any]] = []

    def add(name: str, passed: bool, value: Any = None, limit: Any = None, note: str | None = None,
            reason: str | None = None) -> None:
        gates.append({"n": len(gates) + 1, "gate": name, "pass": bool(passed), "value": value, "limit": limit,
                      "note": note, "reason": None if passed else (reason or name)})

    today_clock, minutes_clock = clock(cfg, now)
    today = c["today"] or today_clock
    minutes = c["now_pt"] if c["now_pt"] is not None else minutes_clock
    start, end = cancel_by_la_minutes(cfg["intraday_entry_start"]), cancel_by_la_minutes(cfg["intraday_entry_end"])
    stop = cancel_by_la_minutes(cfg["intraday_time_stop"])

    spot, k = c["spot"], c["K"]
    f = fly(c, cfg)
    straddle = _mid(c["call"]) + _mid(c["put"])
    spread = ((c["call"][1] - c["call"][0]) + (c["put"][1] - c["put"][0])) / straddle if straddle > 0 else None
    lookback = cfg["intraday_lookback"]
    ratio = premium_ratio(straddle, spot, c["moves"], lookback)
    avg_move = round(mean(abs(m) for m in c["moves"][-lookback:]), 6) if len(c["moves"]) >= lookback else None
    pre_move = spot / c["prev_close"] - 1.0
    off_center = abs(spot - k) / straddle if straddle > 0 else None
    state = pilot_state(events, cfg)

    # 1-5
    add("enabled", cfg["intraday_live_enabled"], cfg["intraday_live_enabled"], True,
        note=None if cfg["intraday_live_enabled"] else "the same-day line is on paper (intraday_live_enabled false)",
        reason="intraday_off")
    listed = c["symbol"] in cfg["intraday_live_names"]
    blocked = c["symbol"] in cfg["blocklist"]
    add("universe", listed and not blocked, c["symbol"], cfg["intraday_live_names"],
        reason="blocklisted" if blocked else "not_a_pilot_name")
    add("same_day_expiry", c["expiry"] == today, c["expiry"], today, reason="not_same_day_expiry")
    add("window", start <= minutes <= end, _fmt(minutes), [_fmt(start), _fmt(end)],
        note="Pacific time", reason="outside_entry_window")
    add("history", len(c["moves"]) >= lookback, len(c["moves"]), lookback, reason="insufficient_history")
    # 6 spread
    add("atm_spread", spread is not None and spread <= cfg["intraday_max_spread_pct"] + EPS,
        None if spread is None else round(spread, 4), cfg["intraday_max_spread_pct"], reason="spread_too_wide")
    # 7 pre-entry move
    add("pre_move", abs(pre_move) <= cfg["intraday_max_pre_move"] + EPS, round(pre_move, 6),
        cfg["intraday_max_pre_move"], reason="pre_entry_move_too_large")
    # 8-9
    ev, evreason = c["event_ahead"]
    add("event_ahead", not ev, evreason if ev else False, False, reason="event_ahead")
    mv, mreason = c["macro_veto"]
    add("macro_veto", not mv, mreason if mv else False, False,
        note="a soft macro band blocks the same-day line too" if mv else None, reason="macro_veto")
    # 10 account breaker (main-line streaks and the account floor; pilot trades are not in them)
    cb = rules.circuit_breaker({"total_value": c["account_value"]}, events, cfg)
    cbi, cbreason = c["circuit_breaker"]
    cb_reasons = list(cb["reasons"]) + (["input: " + (cbreason or "set")] if cbi else [])
    add("circuit_breaker", not cb_reasons, cb_reasons, [], reason="circuit_breaker")
    # 11 the pilot's own breaker
    add("pilot_breaker", not state["paused"], state["reasons"],
        {"loss_limit": cfg["intraday_pilot_loss_limit"], "losses_in_a_row": cfg["intraday_max_consecutive_losses"]},
        note=f"{state['trades']} closed pilot trade(s), {state['pnl_usd']:.2f} in total", reason="pilot_paused")
    # 12 structure
    if f is None:
        add("structure", False, None, None, note="no wings given", reason="no_wings")
    else:
        wos = f["wing_over_straddle"]
        in_range = (wos is not None and wos[0] + EPS >= cfg["intraday_min_wing_over_straddle"]
                    and wos[1] <= cfg["intraday_max_wing_over_straddle"] + EPS)
        centered = off_center is not None and off_center <= cfg["intraday_max_off_center"] + EPS
        add("structure", f["valid"] and in_range and centered,
            {"credit_mid": f["credit_mid"], "width": f["width"], "wing_over_straddle": wos,
             "off_center": None if off_center is None else round(off_center, 4)},
            {"wing_over_straddle": [cfg["intraday_min_wing_over_straddle"], cfg["intraday_max_wing_over_straddle"]],
             "off_center": cfg["intraday_max_off_center"]},
            reason=("no_valid_wings" if not f["valid"] else
                    "wings_out_of_range" if not in_range else "body_off_center"))
    # 13 tier
    ml = f["max_loss_floor"] if f is not None and f["valid"] else None
    lo, hi = cfg["intraday_signal_min_ratio"], cfg["intraday_signal_max_ratio"]
    in_band = (cfg["intraday_signal_enabled"] and ratio is not None
               and (lo is None or ratio + EPS >= lo) and (hi is None or ratio <= hi + EPS))
    tier, tier_note, tier_reason = None, None, "no_tier"
    if ml is None:
        tier_note = "no valid fly"
    elif in_band and ml <= cfg["intraday_max_loss"] + EPS:
        tier = "signal"
    elif cfg["intraday_probe_enabled"] and c["symbol"] in cfg["intraday_probe_names"] \
            and ml <= cfg["intraday_probe_max_loss"] + EPS:
        tier = "probe"
    elif in_band:
        tier_note, tier_reason = f"signal tier: max loss {ml} above {cfg['intraday_max_loss']}", "max_loss_above_cap"
    elif not cfg["intraday_probe_enabled"]:
        tier_note, tier_reason = "no signal and the probe tier is off", "no_signal"
    elif c["symbol"] not in cfg["intraday_probe_names"]:
        tier_note, tier_reason = (f"no signal; probes only on {cfg['intraday_probe_names']}", "no_signal")
    else:
        tier_note, tier_reason = (f"probe: max loss {ml} above {cfg['intraday_probe_max_loss']}",
                                  "max_loss_above_cap")
    add("tier", tier is not None, {"tier": tier, "premium_ratio": ratio, "max_loss_floor": ml},
        {"signal_band": [lo, hi] if cfg["intraday_signal_enabled"] else None,
         "signal_max_loss": cfg["intraday_max_loss"], "probe_max_loss": cfg["intraday_probe_max_loss"],
         "probe_names": cfg["intraday_probe_names"] if cfg["intraday_probe_enabled"] else []},
        note=tier_note, reason=tier_reason)
    # 14 one a day
    add("one_a_day", c["open_intraday"] == 0 and c["entries_today"] < cfg["intraday_max_entries_per_day"],
        {"open_intraday": c["open_intraday"], "entries_today": c["entries_today"]},
        {"open_intraday": 0, "entries_today_below": cfg["intraday_max_entries_per_day"]},
        reason="pilot_fly_already_open" if c["open_intraday"] else "pilot_entry_already_made_today")
    # 15 risk budget (the total cap covers both lines)
    cap = sizing.risk_cap(c["account_value"], cfg)
    budget = sizing.risk_budget(c["account_value"], c["open_risk_usd"], cfg)
    reserve = cfg["exit_slippage_reserve"]
    need = None if ml is None else round(ml + reserve, 2)
    add("risk_budget", need is not None and need <= budget + EPS, need, budget,
        note=f"cap {cap} - open risk {c['open_risk_usd']} = {budget}; needs max loss at the floor + ${reserve:.0f} reserve",
        reason="max_loss_exceeds_cap")
    # 16 exit feasible (single-leg exits: one in-the-money short at the wing must fit what is left)
    bp = c["buying_power"]
    exit_need = exit_room = None
    if ml is not None and bp is not None:
        exit_need = round(max(cfg["exit_buyback_mult"], 1.0) * f["width"] * 100.0, 2)
        exit_room = round(bp - ml, 2)
    add("exit_feasible", exit_need is not None and exit_need <= exit_room + EPS, exit_need, exit_room,
        note=("buying_power not given: take it from get_portfolio" if bp is None else
              None if exit_need is None else
              f"one in-the-money short at the wing costs about {exit_need}; buying power {bp} less the entry leaves {exit_room}"),
        reason="buying_power_missing" if bp is None else "exit_not_feasible")

    # 17 morning exits come first: their buying power is not lent to the pilot
    xp, xreason = c["exits_pending"]
    add("morning_exits", not xp, xreason if xp else False, False,
        note="a position due this morning is still open; no pilot entry until it is flat" if xp else None,
        reason="morning_exit_pending")

    failures = [g for g in gates if not g["pass"]]
    action = "sell" if not failures else "no_trade"
    plan = None
    if f is not None and f["valid"]:
        tp, cut = cfg["intraday_take_profit_frac"], cfg["intraday_cut_frac"]
        plan = {
            "take_profit_close_cost": None if tp is None else round(f["credit_mid"] * (1.0 - tp), 2),
            "cut_close_cost": None if cut is None else round(
                f["credit_mid"] + cut * (f["width"] - f["credit_mid"]), 2),
            "time_stop_pt": _fmt(stop), "entry_window_pt": [_fmt(start), _fmt(end)],
            "limit_start": f["credit_mid"], "limit_floor": f["credit_floor"],
            "note": "take profit and cut are measured on the fly's mid; the wings are the only stop when cut is null",
        }
    record: dict[str, Any] = {
        "symbol": c["symbol"], "kind": PILOT_KIND, "action": action, "tier": tier if action == "sell" else None,
        "reason": failures[0]["reason"] if failures else f"passes: {tier} tier, one contract, flat by {_fmt(stop)} PT",
        "blocked_by": list(dict.fromkeys(g["reason"] for g in failures)),
        "metrics": {
            "spot": spot, "prev_close": c["prev_close"], "K": k, "pre_move": round(pre_move, 6),
            "straddle_mid": round(straddle, 4), "straddle_pct": round(straddle / spot, 6),
            "atm_spread_pct": None if spread is None else round(spread, 4),
            "avg_abs_same_hours_move": avg_move, "n_moves": len(c["moves"]), "premium_ratio": ratio,
            "off_center": None if off_center is None else round(off_center, 4),
            "tier_if_passing": tier,
        },
        "gates": gates,
        "fly": f,
        "contracts": 1 if action == "sell" else 0,
        "plan": plan,
        "pilot": state,
        "risk": {"risk_cap": cap, "open_risk_usd": c["open_risk_usd"], "budget_before": budget,
                 "exit_reserve": reserve, "this_trade_usd": need if action == "sell" else 0.0,
                 "budget_left": round(budget - (need if action == "sell" else 0.0), 2)},
        "clock": {"today": today, "now_pt": _fmt(minutes), "source": "candidate" if c["now_pt"] is not None else "clock"},
    }
    return record, 0 if action == "sell" else 3
