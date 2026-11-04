"""Circuit breaker and exit rules.

Circuit breaker (BLUEPRINT): halt NEW entries when any of
  * account.total_value < min_account_value ($400)
  * last ``max_consecutive_max_loss`` (2) closed trades were max-loss trades
  * last ``max_consecutive_losses`` (3) closed trades were losses
Streaks only count trades whose exit_ts >= ``circuit_reset_ts`` (config; null = all).
Resuming after a streak halt is a human action: set ``circuit_reset_ts`` in config.
Exits are never blocked by the breaker.

Exit rules (CONTRACT), evaluated per position with ``today`` = as_of in
``market_timezone`` (America/New_York):
  1. long straddle (direction debit) whose mid value >= (1+straddle_take_profit)*entry
     -> exit immediately (no minutes_since_open wait).
  2. today >= expiry (optional position ``expiry``) -> exit now, regardless of minutes.
     Exit runs at ~9:45 ET, before the 12:00 PT expiry-day cutoff.
  3. Session after the report, once minutes_since_open >= exit_min_minutes_since_open:
       - position has ``report_date`` + ``timing``: pm (AMC) -> today > report_date;
         am (BMO) -> today >= report_date.
       - otherwise (contract shape only has ``opened``): entries are made near the
         close before the report, so the "session after the report" is any session
         after ``opened``: today > opened. This is the conservative reading (it can
         only exit earlier, never hold longer).
  Otherwise hold (reported in ``holds``).

Closing orders flip each leg (short->buy, long->sell, position_effect close).
Net closing value per unit at mid = sum(long mids) - sum(short mids).
  >= 0 -> direction credit, limit_start = mid value, limit_worst = sum(long bids) - sum(short asks)
  <  0 -> direction debit,  limit_start = |mid value|, limit_worst = sum(short asks) - sum(long bids)
limit_start is rounded to nearest tick, limit_worst rounded away from us (credit
down, debit up); limit_start is clamped so it is never worse than limit_worst.
limit_step = 0.05 if price < 3 else 0.10.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import journal as jr
from . import pricing
from .config import EngineInputError


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
    tv = account.get("total_value")
    if tv < cfg["min_account_value"]:
        reasons.append(f"account_value {tv:.2f} < {cfg['min_account_value']:.2f}")
    if st["consecutive_max_losses"] >= cfg["max_consecutive_max_loss"]:
        reasons.append(f"{st['consecutive_max_losses']} consecutive max-loss trades")
    if st["consecutive_losses"] >= cfg["max_consecutive_losses"]:
        reasons.append(f"{st['consecutive_losses']} losing trades in a row")
    return {"halted": bool(reasons), "reasons": reasons, **st}


# ---------------------------------------------------------------- exits

def _num(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EngineInputError(f"{what} must be a number")
    return float(v)


def closing_order(pos: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    tick = cfg["tick"]
    legs = pos.get("legs")
    if not isinstance(legs, list) or not legs:
        raise EngineInputError(f"position {pos.get('symbol')}: legs required")
    mid_val = nat_val = 0.0
    close_legs = []
    qtys = []
    for i, leg in enumerate(legs):
        what = f"position {pos.get('symbol')} leg {i}"
        side_held = leg.get("side_held")
        if side_held not in ("short", "long"):
            raise EngineInputError(f"{what}: side_held must be short|long")
        if not leg.get("option_id"):
            raise EngineInputError(f"{what}: option_id required")
        bid, ask = _num(leg.get("bid"), f"{what} bid"), _num(leg.get("ask"), f"{what} ask")
        if bid < 0 or ask < bid:
            raise EngineInputError(f"{what}: invalid bid/ask")
        q = _num(leg.get("quantity", 1), f"{what} quantity")
        qtys.append(int(q))
        mid = (bid + ask) / 2
        if side_held == "long":
            mid_val += mid
            nat_val += bid
            side = "sell"
        else:
            mid_val -= mid
            nat_val -= ask
            side = "buy"
        close_legs.append({"option_id": leg["option_id"], "side": side, "position_effect": "close"})
    if mid_val >= 0:
        direction = "credit"
        worst = max(pricing.round_down(nat_val, tick), 0.0)
        start = max(pricing.round_nearest(mid_val, tick), worst)
    else:
        direction = "debit"
        worst = pricing.round_up(-nat_val, tick)
        start = min(pricing.round_nearest(-mid_val, tick), worst)
    return {
        "symbol": pos.get("symbol"), "structure": pos.get("structure"),
        "close_legs": close_legs, "direction": direction, "quantity": min(qtys),
        "limit_start": start, "limit_worst": worst, "limit_step": pricing.limit_step(start, cfg),
        "mid_value": round(mid_val, 4),
    }


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
    actions, holds = [], []
    for pos in positions:
        if not isinstance(pos, dict) or not pos.get("symbol"):
            raise EngineInputError("each position needs a symbol")
        order = closing_order(pos, cfg)
        sym = pos["symbol"]
        direction = pos.get("direction") or jr.direction_of(pos)
        reason = None
        # 1. long straddle take-profit
        if direction == "debit" and pos.get("entry_price") is not None:
            entry = _num(pos["entry_price"], f"{sym} entry_price")
            if entry > 0 and order["mid_value"] >= (1 + cfg["straddle_take_profit"]) * entry:
                reason = f"take_profit: value {order['mid_value']:.2f} >= {1 + cfg['straddle_take_profit']:.2f}x entry {entry:.2f}"
        # 2. expiry day
        if reason is None and pos.get("expiry"):
            exp = parse_date(pos["expiry"], f"{sym} expiry")
            if today >= exp:
                reason = "expiry_day: exit before 12:00 PT"
        # 3. session after report
        if reason is None:
            if pos.get("report_date") and pos.get("timing") in ("am", "pm"):
                rd = parse_date(pos["report_date"], f"{sym} report_date")
                after = today > rd if pos["timing"] == "pm" else today >= rd
                basis = f"{'AMC' if pos['timing'] == 'pm' else 'BMO'} report {rd.isoformat()}"
            else:
                if not pos.get("opened"):
                    raise EngineInputError(f"position {sym}: opened (or report_date+timing) required")
                op = parse_date(pos["opened"], f"{sym} opened")
                after = today > op
                basis = f"opened {op.isoformat()}"
            if after and session_ready:
                reason = f"post_report_session: {basis}, minutes_since_open={mso:g}"
            elif after:
                holds.append({"symbol": sym, "reason": f"wait: minutes_since_open {mso:g} < {cfg['exit_min_minutes_since_open']}"})
                continue
            else:
                holds.append({"symbol": sym, "reason": f"hold: report session not passed ({basis})"})
                continue
        order.pop("mid_value", None)
        order["reason"] = reason
        actions.append(order)
    return {"as_of": as_of, "actions": actions, "holds": holds}
