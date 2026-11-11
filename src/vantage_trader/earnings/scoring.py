"""Candidate scoring and the ``score`` decision (rules v1.1-v1.5, proposals P004/P011).

implied_move  = straddle_factor * ATM-equivalent straddle / spot (P011): the body straddle
                (ATM = listed strike nearest spot, ties -> lower; skipped if it lacks quotes)
                is converted to its at-the-money equivalent through its implied total stdev,
                see ``gate.atm_implied_move``.
avg_hist_move = mean(|m|) over the last ``history_lookback`` entries of
                ``historical_moves`` (assumed chronological, oldest first, as emitted by
                the ``history`` command); requires >= ``min_history`` moves.
edge_ratio    = avg_hist_move / implied_move
band          = tight (<= 0.70) | final_sweep (<= 0.85) | no_edge | long_straddle_off (>= 1.25)
action        = sell if edge_ratio <= sell_max_ratio; else skip. Long straddles are OFF
                (P010, 2026-11-11): edge_ratio >= buy_min_ratio -> skip "long_straddle_off".

Gates are checked in this order; the first failure becomes ``skip_reason``
(metrics are still reported when computable):
  blocklisted, symbol_mismatch, unverified_report_date, flagged:<flags>,
  price_below_min, report_not_imminent, bad_expiry, insufficient_history, missing_atm_quotes,
  spread_too_wide, intraday_move_too_large, regime_guard, long_straddle_off, no_edge,
  already_open, then structure/sizing reasons: missing_atm_quotes, no_valid_wings,
  max_loss_exceeds_cap, no_buying_power, no_fillable_limit_range, negative_ev.
There is no limit on the number of open positions (v1.4); the total risk cap is the limit.

Symbols: ``symbol`` (and optional ``chain_symbol``) are strip().upper()'d before any
check. A ``chain_symbol`` that is blocklisted -> blocklisted; one that differs from
``symbol`` -> symbol_mismatch.
Entry timing (today = as_of date in market_timezone, America/New_York):
  report_not_imminent unless (pm and report_date == today) or
  (am and report_date == next trading day after today; weekends and config
  ``market_holidays`` are skipped).
Expiry rule (bad_expiry unless all hold): expiry > today, expiry <= report_date +
  max_expiry_days_after_report (7) calendar days, and pm -> expiry > report_date,
  am -> expiry >= report_date, and expiry is not a ``market_early_closes`` day
  (13:00 ET close).
Orders add ``order_legs`` (legs stripped to option_id/side/position_effect for the broker
tool), ``exit_slippage_reserve`` and ``risk_cap_effective`` (= risk_cap - reserve*qty, the
bound on max_loss_worst).
Spread rule: (ask-bid)/mid above max_spread_pct (25%) on the call, the put or the straddle
  -> skip. Above wide_spread_pct (12%) the candidate's max loss is capped at
  wide_spread_max_loss ($350).
Intraday: |intraday_move| <= 5%; 5-7% only with candidate ``sector_same_direction: true``
  (and no flag, which skips anyway); above 7% skip.
Regime guard: applied when the candidate carries ``regime_20d`` (the ``gate`` command
  requires it): regime_20d must be < regime_mult (1.25) x avg_hist_move.
Flags: any flag skips, except ``big_intraday_move`` (a price fact the intraday gate covers).
Risk cap: min(max_loss_abs $1,000, 0.93 x account.total_value) minus
  ``account.open_risk_usd`` (max loss + exit reserves of positions already open; required
  when ``open_positions`` is not empty). Quantity: this older chain-based path stays at
  1 contract per name; sizing above 1 (v1.7) is decided by the ``gate`` command only.

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

from . import gate as gt
from . import journal as jr
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
    if acct.get("open_risk_usd") is not None:
        if _num(acct["open_risk_usd"], "account.open_risk_usd") < 0:
            raise EngineInputError("account.open_risk_usd must be >= 0")
    elif snap.get("open_positions"):
        raise EngineInputError("account.open_risk_usd (max loss + exit reserves of the open positions) "
                               "is required when open_positions is not empty")
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
        if c.get("regime_20d") is not None:
            _num(c["regime_20d"], f"{w}.regime_20d")
        if not isinstance(c.get("sector_same_direction", False), bool):
            raise EngineInputError(f"{w}.sector_same_direction must be true/false")
        chain = c.get("chain")
        if not isinstance(chain, list):
            raise EngineInputError(f"{w}.chain must be a list")
        for r in chain:
            if not isinstance(r, dict):
                raise EngineInputError(f"{w}.chain rows must be objects")
            _num(r.get("strike"), f"{w}.chain[].strike", positive=True)


def score_candidate(c: dict[str, Any], ctx: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    sym = norm_symbol(c["symbol"])
    chain_sym = norm_symbol(c["chain_symbol"]) if c.get("chain_symbol") is not None else None
    spot = float(c["spot"])
    chain = structures.Chain(c["chain"])
    row: dict[str, Any] = {"symbol": sym, "edge_ratio": None, "implied_move": None,
                           "implied_move_raw": None, "avg_hist_move": None, "band": None,
                           "action": "skip", "skip_reason": None, "ev_per_dollar_risk": None}
    # metrics
    k = chain.atm_strike(spot)
    atm = (chain.calls[k], chain.puts[k]) if k is not None else None
    spread = None
    if atm:
        straddle = atm[0].mid + atm[1].mid
        if straddle > 0:
            im = gt.atm_implied_move(spot, k, straddle, cfg["straddle_factor"])
            row["implied_move"], row["implied_move_raw"] = im["implied_move"], im["implied_move_raw"]
        spread = gt.spread_pcts((atm[0].bid, atm[0].ask), (atm[1].bid, atm[1].ask))
        row["spread_pct"] = round(spread["worst"], 4) if spread["worst"] != float("inf") else None
    moves = [float(m) for m in c["historical_moves"]][-cfg["history_lookback"]:]
    if len(moves) >= cfg["min_history"]:
        row["avg_hist_move"] = round(mean(abs(m) for m in moves), 6)
    edge = None
    if row["implied_move"] and row["avg_hist_move"] is not None:
        edge = row["avg_hist_move"] / row["implied_move"]
        row["edge_ratio"] = round(edge, 4)
    row["band"] = gt.edge_band(None if edge is None else round(edge, 6), cfg)

    def skip(reason: str) -> dict[str, Any]:
        row["action"] = "skip"
        row["skip_reason"] = reason
        return row

    rd = rules.parse_date(c["report_date"], "report_date")
    exp = rules.parse_date(c["expiry"], "expiry")
    flags = gt.news_flags([str(f) for f in c.get("flags", [])])
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
            and ((c["timing"] == "pm" and exp > rd) or (c["timing"] == "am" and exp >= rd))
            and exp.isoformat() not in set(cfg["market_early_closes"])):
        return skip("bad_expiry")
    if row["avg_hist_move"] is None:
        return skip("insufficient_history")
    if atm is None or row["implied_move"] is None or row["implied_move"] <= 0:
        return skip("missing_atm_quotes")
    if spread["worst"] > cfg["max_spread_pct"] + 1e-12:
        return skip("spread_too_wide")
    ok, _ = gt.intraday_verdict(float(c["intraday_move"]), c.get("sector_same_direction") is True, flags, cfg)
    if not ok:
        return skip("intraday_move_too_large")
    if c.get("regime_20d") is not None and not (
            float(c["regime_20d"]) < cfg["regime_mult"] * row["avg_hist_move"] - 1e-9):
        return skip("regime_guard")
    if row["band"] == "long_straddle_off":
        return skip("long_straddle_off")
    if row["band"] not in ("tight", "final_sweep"):
        return skip("no_edge")
    band = "sell"
    if sym in ctx["open_symbols"]:
        return skip("already_open")

    cap = ctx["cap"]
    if spread["worst"] > cfg["wide_spread_pct"] + 1e-12:
        row["spread_band_cap"] = cfg["wide_spread_max_loss"]
        cap = min(cap, cfg["wide_spread_max_loss"] + cfg["exit_slippage_reserve"] * ctx["qty_limit"])
    order, reason = structures.build_iron_fly(chain, spot, moves, cap, dict(cfg, max_quantity=ctx["qty_limit"]))
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


ORDER_KEYS = ["symbol", "structure", "quantity", "direction", "expiry", "legs", "order_legs", "limit_start",
              "limit_floor", "limit_step", "max_loss", "max_profit", "breakevens", "hist_win_rate",
              "cancel_by", "max_loss_worst", "risk_cap", "risk_cap_effective", "exit_slippage_reserve",
              "ev_per_dollar_risk", "hist_ev",
              "mid", "natural", "atm_strike", "wing_width", "implied_move", "edge_ratio",
              "report_date", "timing"]


def score(snapshot: dict[str, Any], cfg: dict[str, Any], journal_events: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    validate_snapshot(snapshot)
    acct = snapshot["account"]
    open_positions = snapshot.get("open_positions", [])
    total_cap = sizing.risk_cap(float(acct["total_value"]), cfg)
    open_risk = float(acct.get("open_risk_usd") or 0.0)
    cap = sizing.risk_budget(float(acct["total_value"]), open_risk, cfg)
    closed = len(jr.closed_trades(journal_events))
    ctx = {"cap": cap, "open_positions": open_positions, "qty_limit": 1,
           "today": rules.local_date(snapshot["as_of"], cfg["market_timezone"]),
           "open_symbols": {norm_symbol(p.get("symbol")) for p in open_positions if isinstance(p, dict)}}
    rows = [score_candidate(c, ctx, cfg) for c in snapshot["candidates"]]
    tradeable = sorted((r for r in rows if r["action"] == "sell"),
                       key=lambda r: -r["ev_per_dollar_risk"])
    skipped = [r for r in rows if r["action"] == "skip"]
    ranked = tradeable + skipped

    cb = rules.circuit_breaker(acct, journal_events, cfg)
    decision: dict[str, Any] = {
        "as_of": snapshot["as_of"], "status": "no_trade", "reason": "", "order": None,
        "risk_cap": cap, "risk_cap_total": total_cap, "open_risk_usd": open_risk,
        "contracts_limit": ctx["qty_limit"], "closed_live_trades": closed,
        "human_must_approve_trades": bool(acct.get("human_must_approve_trades", False)),
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
