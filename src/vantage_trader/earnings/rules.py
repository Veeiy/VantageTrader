"""Circuit breaker, trading calendar and exit rules.

Circuit breaker (BLUEPRINT): halt NEW entries when any of
  * account.total_value < min_account_value ($400)
  * last ``max_consecutive_max_loss`` (2) closed trades were max-loss trades
  * last ``max_consecutive_losses`` (3) closed trades were losses
Streaks only count trades whose exit_ts >= ``circuit_reset_ts`` (config; null = all).
Resuming after a streak halt is a human action: set ``circuit_reset_ts`` in config.
Exits are never blocked by the breaker: ``exit`` reports the breaker state (from
``--journal`` and the optional snapshot ``account``) as context only, always exit code 0.
If the exit snapshot has no ``account.total_value`` the account-value rule is not evaluated.

Exit snapshot position shape (CONTRACT plus the fields below):
  {"symbol","structure","direction","entry_price","opened"?,
   "expiry"                    REQUIRED (missing -> input error, exit code 2),
   "report_date"?,"timing"?    optional; enable the AMC/BMO rule,
   "provenance"?               optional; "reconstructed" for positions adopted by reconcile,
   "legs":[{"option_id","side_held":"short|long","quantity","bid","ask",
            "strike" REQUIRED, "type":"call|put" REQUIRED}]}

Exit rules, evaluated per position with ``today`` = as_of in ``market_timezone``:
  0. Broken structure (unequal leg quantities, or a short leg without a same-type long
     wing): ``leg_qty_mismatch: true``; no normal close. Flatten immediately (any
     minutes_since_open >= 0; before the open it is a hold carrying the flag), with
     reason "partial_fill_flatten", actions in this order:
       a. per short leg with a same-type long: close the vertical for the matched
          quantity, closing debit capped at that vertical's width (rule 2 logic);
       b. per short leg, any unmatched (naked) quantity: buy back alone, worst = ask
          (NOT capped: a naked short has no width bound and must not be left open);
       c. remaining long quantity: sell.
     Each action carries ``sequence`` (1..n) and must be worked in that order.
  1. long straddle (direction debit) whose mid value >= (1+straddle_take_profit)*entry
     -> exit immediately (no minutes_since_open wait).
  2. today >= expiry -> exit now, regardless of minutes ("expiry_day"). Exit runs at
     ~9:45 ET, before the 12:00 PT expiry-day cutoff, so a short leg is never held into
     the expiry-day close.
  3. Otherwise once minutes_since_open >= exit_min_minutes_since_open:
       - with ``report_date`` + ``timing``: pm (AMC) -> today > report_date;
         am (BMO) -> today >= report_date.
       - without them: exit when provenance == "reconstructed", or ``opened`` is
         missing, or opened < today. An unknown-provenance position is never held past
         the first session after it was opened.
  Otherwise hold (reported in ``holds``).

Closing price. Each leg flips (short->buy, long->sell, position_effect close).
Net closing value per unit at mid = sum(long mids) - sum(short mids).
  >= 0 -> direction credit, limit_start = mid value, limit_worst = sum(long bids) - sum(short asks)
  <  0 -> direction debit,  limit_start = |mid value|, limit_worst = sum(short asks) - sum(long bids)
limit_start is rounded to nearest tick, limit_worst rounded away from us (credit
down, debit up); limit_start is clamped so it is never worse than limit_worst.
Width cap: when every short leg has a same-type long wing (iron fly / condor /
vertical), W = max vertical width computed from leg strikes, and both limit_start and
limit_worst of a closing debit are clamped to <= W (W rounded down to tick); the
structure can never be worth more than W. If the natural closing debit exceeds W the
close is split into one action per vertical (put vertical first, then call), each
clamped to its own width, reason "split_verticals_natural_exceeds_width" (the exit rule
that fired is in ``trigger``, present on every normal/split action).
limit_step = 0.05 if price < 3 else 0.10.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import journal as jr
from . import pricing
from .config import EngineInputError, norm_symbol


def parse_ts(s: Any, what: str = "as_of") -> datetime:
    if not isinstance(s, str):
        raise EngineInputError(f"{what} must be an ISO timestamp string")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise EngineInputError(f"{what}: bad timestamp {s!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def local_date(as_of: str, tz: str) -> date:
    return parse_ts(as_of).astimezone(ZoneInfo(tz)).date()


def parse_date(s: Any, what: str) -> date:
    try:
        return date.fromisoformat(str(s))
    except ValueError:
        raise EngineInputError(f"{what}: bad date {s!r}")


# ---------------------------------------------------------------- circuit breaker

def circuit_breaker(account: dict[str, Any], events: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    trades = jr.closed_trades(events)
    st = jr.streaks(trades, cfg["max_loss_tolerance"], cfg.get("circuit_reset_ts"))
    reasons = []
    tv = (account or {}).get("total_value")
    if isinstance(tv, (int, float)) and not isinstance(tv, bool) and tv < cfg["min_account_value"]:
        reasons.append(f"account_value {tv:.2f} < {cfg['min_account_value']:.2f}")
    if st["consecutive_max_losses"] >= cfg["max_consecutive_max_loss"]:
        reasons.append(f"{st['consecutive_max_losses']} consecutive max-loss trades")
    if st["consecutive_losses"] >= cfg["max_consecutive_losses"]:
        reasons.append(f"{st['consecutive_losses']} losing trades in a row")
    return {"halted": bool(reasons), "reasons": reasons, **st}


# ---------------------------------------------------------------- trading calendar

def is_trading_day(d: date, cfg: dict[str, Any]) -> bool:
    return d.weekday() < 5 and d.isoformat() not in set(cfg["market_holidays"])


def next_trading_day(d: date, cfg: dict[str, Any]) -> date:
    n = d + timedelta(days=1)
    while not is_trading_day(n, cfg):
        n += timedelta(days=1)
    return n


# ---------------------------------------------------------------- exits

def _num(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EngineInputError(f"{what} must be a number")
    return float(v)


def _parse_legs(pos: dict[str, Any]) -> list[dict[str, Any]]:
    legs = pos.get("legs")
    if not isinstance(legs, list) or not legs:
        raise EngineInputError(f"position {pos.get('symbol')}: legs required")
    out = []
    for i, leg in enumerate(legs):
        what = f"position {pos.get('symbol')} leg {i}"
        if not isinstance(leg, dict):
            raise EngineInputError(f"{what} must be an object")
        if leg.get("side_held") not in ("short", "long"):
            raise EngineInputError(f"{what}: side_held must be short|long")
        if leg.get("type") not in ("call", "put"):
            raise EngineInputError(f"{what}: type must be call|put")
        if not leg.get("option_id"):
            raise EngineInputError(f"{what}: option_id required")
        bid, ask = _num(leg.get("bid"), f"{what} bid"), _num(leg.get("ask"), f"{what} ask")
        if bid < 0 or ask < bid:
            raise EngineInputError(f"{what}: invalid bid/ask")
        strike = _num(leg.get("strike"), f"{what} strike")
        if strike <= 0:
            raise EngineInputError(f"{what}: strike must be > 0")
        q = _num(leg.get("quantity", 1), f"{what} quantity")
        if q <= 0 or not float(q).is_integer():
            raise EngineInputError(f"{what}: quantity must be a positive integer")
        out.append({"option_id": str(leg["option_id"]), "side_held": leg["side_held"], "type": leg["type"],
                    "bid": bid, "ask": ask, "strike": strike, "quantity": int(q)})
    return out


def _price(legs: list[dict[str, Any]], cfg: dict[str, Any], cap: float | None = None) -> dict[str, Any]:
    """Closing order for ``legs`` (each traded once per unit). ``cap`` clamps a debit."""
    tick = cfg["tick"]
    mid_val = nat_val = 0.0
    close_legs = []
    for leg in legs:
        mid = (leg["bid"] + leg["ask"]) / 2
        if leg["side_held"] == "long":
            mid_val += mid
            nat_val += leg["bid"]
            side = "sell"
        else:
            mid_val -= mid
            nat_val -= leg["ask"]
            side = "buy"
        close_legs.append({"option_id": leg["option_id"], "side": side, "position_effect": "close",
                           "strike": leg["strike"], "type": leg["type"]})
    if mid_val >= 0:
        direction = "credit"
        worst = max(pricing.round_down(nat_val, tick), 0.0)
        start = max(pricing.round_nearest(mid_val, tick), worst)
    else:
        direction = "debit"
        worst = pricing.round_up(-nat_val, tick)
        start = min(pricing.round_nearest(-mid_val, tick), worst)
        if cap is not None:
            capr = pricing.round_down(cap, tick)
            worst, start = min(worst, capr), min(start, capr)
    return {"close_legs": close_legs, "direction": direction, "limit_start": start,
            "limit_worst": worst, "limit_step": pricing.limit_step(start, cfg),
            "mid_value": round(mid_val, 4), "natural_value": round(nat_val, 4)}


def _verticals(legs: list[dict[str, Any]]) -> dict[str, tuple[dict[str, Any], dict[str, Any] | None]]:
    """type -> (short leg, same-type long leg or None) for each short leg type."""
    out = {}
    for t in ("put", "call"):
        shorts = [l for l in legs if l["type"] == t and l["side_held"] == "short"]
        longs = [l for l in legs if l["type"] == t and l["side_held"] == "long"]
        for s in shorts:
            out[f"{t}:{s['option_id']}"] = (s, longs[0] if len(longs) == 1 and len(shorts) == 1 else None)
    return out


def _is_broken(legs: list[dict[str, Any]]) -> bool:
    if len({l["quantity"] for l in legs}) > 1:
        return True
    return any(lng is None for _, lng in _verticals(legs).values())


def _flatten(pos: dict[str, Any], legs: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    remaining = {l["option_id"]: l["quantity"] for l in legs}
    acts: list[dict[str, Any]] = []
    for s, lng in _verticals(legs).values():           # a. matched verticals, capped
        if lng is None:
            continue
        q = min(remaining[s["option_id"]], remaining[lng["option_id"]])
        if q > 0:
            o = _price([s, lng], cfg, cap=abs(s["strike"] - lng["strike"]))
            o.update(quantity=q, width_cap=abs(s["strike"] - lng["strike"]))
            acts.append(o)
            remaining[s["option_id"]] -= q
            remaining[lng["option_id"]] -= q
    for s in (l for l in legs if l["side_held"] == "short"):  # b. naked remainder, uncapped
        if remaining[s["option_id"]] > 0:
            o = _price([s], cfg)
            o.update(quantity=remaining[s["option_id"]], width_cap=None, naked_short=True)
            acts.append(o)
            remaining[s["option_id"]] = 0
    for lg in (l for l in legs if l["side_held"] == "long"):  # c. leftover longs
        if remaining[lg["option_id"]] > 0:
            o = _price([lg], cfg)
            o.update(quantity=remaining[lg["option_id"]], width_cap=None)
            acts.append(o)
    for i, o in enumerate(acts, 1):
        o.update(symbol=pos["symbol"], structure=pos.get("structure"), sequence=i,
                 leg_qty_mismatch=True, reason="partial_fill_flatten")
    return acts


def closing_actions(pos: dict[str, Any], legs: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Normal (balanced) close; split into verticals when natural debit exceeds W."""
    verts = _verticals(legs)
    widths = {k: abs(s["strike"] - lng["strike"]) for k, (s, lng) in verts.items() if lng is not None}
    cap = max(widths.values()) if verts and len(widths) == len(verts) else None
    qty = legs[0]["quantity"]
    base = _price(legs, cfg, cap=cap)
    acts = []
    if cap is not None and base["direction"] == "debit" and -base["natural_value"] > cap + 1e-9:
        for i, (k, (s, lng)) in enumerate(verts.items(), 1):
            o = _price([s, lng], cfg, cap=widths[k])
            o.update(width_cap=widths[k], sequence=i, reason="split_verticals_natural_exceeds_width")
            acts.append(o)
    else:
        base.update(width_cap=cap, sequence=1)
        acts.append(base)
    for o in acts:
        o.update(symbol=pos["symbol"], structure=pos.get("structure"), quantity=qty, leg_qty_mismatch=False)
    return acts


def _finish(o: dict[str, Any]) -> dict[str, Any]:
    o.pop("mid_value", None)
    o.pop("natural_value", None)
    return o


def exit_decision(snapshot: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise EngineInputError("snapshot must be a JSON object")
    as_of = snapshot.get("as_of")
    today = local_date(as_of, cfg["market_timezone"])
    positions = snapshot.get("positions", [])
    if not isinstance(positions, list):
        raise EngineInputError("positions must be a list")
    mso = snapshot.get("minutes_since_open")
    if mso is None:
        raise EngineInputError("minutes_since_open is required")
    mso = _num(mso, "minutes_since_open")
    session_ready = mso >= cfg["exit_min_minutes_since_open"]
    actions: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    for pos in positions:
        if not isinstance(pos, dict) or not norm_symbol(pos.get("symbol")):
            raise EngineInputError("each position needs a symbol")
        pos = dict(pos, symbol=norm_symbol(pos["symbol"]))
        sym = pos["symbol"]
        if not pos.get("expiry"):
            raise EngineInputError(f"position {sym}: expiry is required")
        exp = parse_date(pos["expiry"], f"{sym} expiry")
        legs = _parse_legs(pos)

        if _is_broken(legs):
            if mso < 0:
                holds.append({"symbol": sym, "leg_qty_mismatch": True,
                              "reason": "wait_market_open: broken structure will be flattened at the open"})
            else:
                actions.extend(_finish(o) for o in _flatten(pos, legs, cfg))
            continue

        acts = closing_actions(pos, legs, cfg)
        direction = pos.get("direction") or jr.direction_of(pos)
        reason = None
        # 1. long straddle take-profit
        if direction == "debit" and pos.get("entry_price") is not None:
            entry = _num(pos["entry_price"], f"{sym} entry_price")
            value = sum(((l["bid"] + l["ask"]) / 2) * (1 if l["side_held"] == "long" else -1) for l in legs)
            if entry > 0 and value >= (1 + cfg["straddle_take_profit"]) * entry:
                reason = f"take_profit: value {value:.2f} >= {1 + cfg['straddle_take_profit']:.2f}x entry {entry:.2f}"
        # 2. expiry day
        if reason is None and today >= exp:
            reason = "expiry_day: exit before 12:00 PT"
        # 3. session after report
        if reason is None:
            if pos.get("report_date") and pos.get("timing") in ("am", "pm"):
                rd = parse_date(pos["report_date"], f"{sym} report_date")
                after = today > rd if pos["timing"] == "pm" else today >= rd
                basis = f"{'AMC' if pos['timing'] == 'pm' else 'BMO'} report {rd.isoformat()}"
            elif pos.get("provenance") == "reconstructed":
                after, basis = True, "reconstructed position"
            elif not pos.get("opened"):
                after, basis = True, "unknown opened date"
            else:
                op = parse_date(pos["opened"], f"{sym} opened")
                after = op < today
                basis = f"opened {op.isoformat()}"
            if after and session_ready:
                reason = f"post_report_session: {basis}, minutes_since_open={mso:g}"
            elif after:
                holds.append({"symbol": sym, "leg_qty_mismatch": False,
                              "reason": f"wait: minutes_since_open {mso:g} < {cfg['exit_min_minutes_since_open']}"})
                continue
            else:
                holds.append({"symbol": sym, "leg_qty_mismatch": False,
                              "reason": f"hold: report session not passed ({basis})"})
                continue
        for o in acts:
            o["trigger"] = reason
            if o.get("reason") != "split_verticals_natural_exceeds_width":
                o["reason"] = reason
            actions.append(_finish(o))
    return {"as_of": as_of, "actions": actions, "holds": holds}
