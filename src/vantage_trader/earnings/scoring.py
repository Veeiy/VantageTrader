"""Candidate scoring and the ``score`` decision.

implied_move  = straddle_factor * (ATM call mid + ATM put mid) / spot
                (ATM = listed strike nearest spot, ties -> lower; skipped if it lacks quotes)
avg_hist_move = mean(|m|) over the last ``history_lookback`` entries of
                ``historical_moves`` (assumed chronological, oldest first, as emitted by
                the ``history`` command); requires >= ``min_history`` moves.
edge_ratio    = avg_hist_move / implied_move
action        = sell if edge_ratio <= sell_max_ratio; buy if >= buy_min_ratio; else skip.

Gates are checked in this order; the first failure becomes ``skip_reason``
(metrics are still reported when computable):
  blocklisted, symbol_mismatch, unverified_report_date, flagged:<flags>,
  price_below_min, report_not_imminent, bad_expiry, insufficient_history, missing_atm_quotes,
  spread_too_wide, intraday_move_too_large, no_edge, open_position_limit,
  already_open, then structure/sizing reasons: missing_atm_quotes, no_valid_wings,
  max_loss_exceeds_cap, no_buying_power, no_fillable_limit_range, negative_ev.

Symbols: ``symbol`` (and optional ``chain_symbol``) are strip().upper()'d before any
check. A ``chain_symbol`` that is blocklisted -> blocklisted; one that differs from
``symbol`` -> symbol_mismatch.
Entry timing (today = as_of date in market_timezone, America/New_York):
  report_not_imminent unless (pm and report_date == today) or
  (am and report_date == next trading day after today; weekends and config
  ``market_holidays`` are skipped).
Expiry rule (bad_expiry unless all hold): expiry > today, expiry <= report_date +
  max_expiry_days_after_report (7) calendar days, and pm -> expiry > report_date,
  am -> expiry >= report_date.
Spread rule: (ask-bid)/mid > max_spread_pct on EITHER ATM leg -> skip.

Ranking: tradeable candidates by ev_per_dollar_risk desc, then skipped ones. The top
tradeable candidate becomes ``order``. ``status`` is "halted" (exit 3) if the circuit
breaker trips; ranking is still reported but ``order`` is null.

Snapshot validation is strict (missing/mistyped required fields -> EngineInputError ->
exit code 2). ``flags`` and ``open_positions`` default to []. ``intraday_move`` is required
(null is invalid) because the intraday gate cannot be evaluated without it.
"""
from __future__ import annotations

from statistics import mean
from typing import Any

from . import rules, sizing, structures
from datetime import timedelta

from .config import EngineInputError, norm_symbol


def _num(v: Any, what: str, positive: bool = False) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EngineInputError(f"{what} must be a number, got {v!r}")
    if positive and v <= 0:
        raise EngineInputError(f"{what} must be > 0")
    return float(v)


def validate_snapshot(snap: Any) -> None:
    if not isinstance(snap, dict):
        raise EngineInputError("snapshot must be a JSON object")
    rules.parse_ts(snap.get("as_of"))
    acct = snap.get("account")
    if not isinstance(acct, dict):
        raise EngineInputError("account object required")
    _num(acct.get("buying_power"), "account.buying_power")
    _num(acct.get("total_value"), "account.total_value")
    if not isinstance(snap.get("open_positions", []), list):
        raise EngineInputError("open_positions must be a list")
    cands = snap.get("candidates")
    if not isinstance(cands, list):
        raise EngineInputError("candidates must be a list")
    for i, c in enumerate(cands):
        w = f"candidates[{i}]"
        if not isinstance(c, dict):
            raise EngineInputError(f"{w} must be an object")
        if not isinstance(c.get("symbol"), str) or not norm_symbol(c["symbol"]):
            raise EngineInputError(f"{w}.symbol required")
        if "chain_symbol" in c and c["chain_symbol"] is not None and not isinstance(c["chain_symbol"], str):
            raise EngineInputError(f"{w}.chain_symbol must be a string")
        w = f"candidate {c['symbol']}"
        rules.parse_date(c.get("report_date"), f"{w}.report_date")
        rules.parse_date(c.get("expiry"), f"{w}.expiry")
        if c.get("timing") not in ("am", "pm"):
            raise EngineInputError(f"{w}.timing must be 'am' or 'pm'")
        if not isinstance(c.get("verified"), bool):
            raise EngineInputError(f"{w}.verified must be true/false")
        _num(c.get("spot"), f"{w}.spot", positive=True)
        _num(c.get("intraday_move"), f"{w}.intraday_move")
        hm = c.get("historical_moves")
        if not isinstance(hm, list):
            raise EngineInputError(f"{w}.historical_moves must be a list")
        for m in hm:
            _num(m, f"{w}.historical_moves[]")
        if not isinstance(c.get("flags", []), list):
            raise EngineInputError(f"{w}.flags must be a list")
        chain = c.get("chain")
        if not isinstance(chain, list):
            raise EngineInputError(f"{w}.chain must be a list")
        for r in chain:
            if not isinstance(r, dict):
                raise EngineInputError(f"{w}.chain rows must be objects")
            _num(r.get("strike"), f"{w}.chain[].strike", positive=True)


def _spread_pct(q: structures.Quote) -> float:
    return float("inf") if q.mid <= 0 else (q.ask - q.bid) / q.mid


def score_candidate(c: dict[str, Any], ctx: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    sym = norm_symbol(c["symbol"])
    chain_sym = norm_symbol(c["chain_symbol"]) if c.get("chain_symbol") is not None else None
    spot = float(c["spot"])
    chain = structures.Chain(c["chain"])
    row: dict[str, Any] = {"symbol": sym, "edge_ratio": None, "implied_move": None,
                           "avg_hist_move": None, "action": "skip", "skip_reason": None,
                           "ev_per_dollar_risk": None}
    # metrics
    k = chain.atm_strike(spot)
    atm = (chain.calls[k], chain.puts[k]) if k is not None else None
    if atm:
        straddle = atm[0].mid + atm[1].mid
        row["implied_move"] = round(cfg["straddle_factor"] * straddle / spot, 6)
    moves = [float(m) for m in c["historical_moves"]][-cfg["history_lookback"]:]
    if len(moves) >= cfg["min_history"]:
        row["avg_hist_move"] = round(mean(abs(m) for m in moves), 6)
    if row["implied_move"] and row["avg_hist_move"] is not None:
        row["edge_ratio"] = round(row["avg_hist_move"] / row["implied_move"], 4)
    band = None
    if row["edge_ratio"] is not None:
        if row["edge_ratio"] <= cfg["sell_max_ratio"]:
            band = "sell"
        elif row["edge_ratio"] >= cfg["buy_min_ratio"]:
            band = "buy"

    def skip(reason: str) -> dict[str, Any]:
        row["action"] = "skip"
        row["skip_reason"] = reason
        return row

    rd = rules.parse_date(c["report_date"], "report_date")
    exp = rules.parse_date(c["expiry"], "expiry")
    flags = [str(f) for f in c.get("flags", [])]
    if sym in cfg["blocklist"] or (chain_sym is not None and chain_sym in cfg["blocklist"]):
        return skip("blocklisted")
    if chain_sym is not None and chain_sym != sym:
        return skip("symbol_mismatch")
    if not c["verified"]:
        return skip("unverified_report_date")
    if flags:
        return skip("flagged:" + ",".join(flags))
    if spot < cfg["min_price"]:
        return skip("price_below_min")
    today = ctx["today"]
    if not ((c["timing"] == "pm" and rd == today)
            or (c["timing"] == "am" and rd == rules.next_trading_day(today, cfg))):
        return skip("report_not_imminent")
    if not (exp > today and exp <= rd + timedelta(days=cfg["max_expiry_days_after_report"])
            and ((c["timing"] == "pm" and exp > rd) or (c["timing"] == "am" and exp >= rd))):
        return skip("bad_expiry")
    if row["avg_hist_move"] is None:
        return skip("insufficient_history")
    if atm is None or row["implied_move"] is None or row["implied_move"] <= 0:
        return skip("missing_atm_quotes")
    if max(_spread_pct(atm[0]), _spread_pct(atm[1])) > cfg["max_spread_pct"] + 1e-12:
        return skip("spread_too_wide")
    if abs(float(c["intraday_move"])) > cfg["max_intraday_move"] + 1e-12:
        return skip("intraday_move_too_large")
    if band is None:
        return skip("no_edge")
    if len(ctx["open_positions"]) >= cfg["max_open_positions"]:
        row["action_if_allowed"] = band
        return skip("open_position_limit")
    if sym in ctx["open_symbols"]:
        return skip("already_open")

    builder = structures.build_iron_fly if band == "sell" else structures.build_long_straddle
    order, reason = builder(chain, spot, moves, ctx["cap"], cfg)
    if order is None:
        row["action_if_allowed"] = band
        return skip(reason or "no_structure")
    row["ev_per_dollar_risk"] = order["ev_per_dollar_risk"]
    if order["ev_per_dollar_risk"] <= cfg["min_ev_per_dollar_risk"]:
        row["action_if_allowed"] = band
        return skip("negative_ev")
    row["action"] = band
    order.update({"symbol": sym, "expiry": c["expiry"], "cancel_by": cfg["cancel_by"],
                  "implied_move": row["implied_move"], "edge_ratio": row["edge_ratio"],
                  "report_date": c["report_date"], "timing": c["timing"]})
    row["_order"] = order
    return row


ORDER_KEYS = ["symbol", "structure", "quantity", "direction", "expiry", "legs", "limit_start",
              "limit_floor", "limit_step", "max_loss", "max_profit", "breakevens", "hist_win_rate",
              "cancel_by", "max_loss_worst", "risk_cap", "ev_per_dollar_risk", "hist_ev",
              "mid", "natural", "atm_strike", "wing_width", "implied_move", "edge_ratio",
              "report_date", "timing"]


def score(snapshot: dict[str, Any], cfg: dict[str, Any], journal_events: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    validate_snapshot(snapshot)
    acct = snapshot["account"]
    open_positions = snapshot.get("open_positions", [])
    cap = sizing.risk_cap(float(acct["buying_power"]), cfg)
    ctx = {"cap": cap, "open_positions": open_positions,
           "today": rules.local_date(snapshot["as_of"], cfg["market_timezone"]),
           "open_symbols": {norm_symbol(p.get("symbol")) for p in open_positions if isinstance(p, dict)}}
    rows = [score_candidate(c, ctx, cfg) for c in snapshot["candidates"]]
    tradeable = sorted((r for r in rows if r["action"] in ("sell", "buy")),
                       key=lambda r: -r["ev_per_dollar_risk"])
    skipped = [r for r in rows if r["action"] == "skip"]
    ranked = tradeable + skipped

    cb = rules.circuit_breaker(acct, journal_events, cfg)
    decision: dict[str, Any] = {
        "as_of": snapshot["as_of"], "status": "no_trade", "reason": "", "order": None,
        "risk_cap": cap, "human_must_approve_trades": bool(acct.get("human_must_approve_trades", False)),
        "circuit_breaker": cb,
    }
    code = 0
    if cb["halted"]:
        decision["status"] = "halted"
        decision["reason"] = "circuit breaker: " + "; ".join(cb["reasons"])
        code = 3
    elif tradeable:
        top = tradeable[0]["_order"]
        top["risk_cap"] = cap
        decision["status"] = "trade"
        decision["order"] = {k: top.get(k) for k in ORDER_KEYS if k in top}
        decision["reason"] = (f"{top['symbol']} {top['structure']}: edge_ratio {top['edge_ratio']}, "
                              f"ev/risk {top['ev_per_dollar_risk']}")
    elif not rows:
        decision["reason"] = "no candidates"
    else:
        decision["reason"] = "no candidate passed all gates"
    decision["ranked"] = [{k: v for k, v in r.items() if k != "_order"} for r in ranked]
    return decision, code
