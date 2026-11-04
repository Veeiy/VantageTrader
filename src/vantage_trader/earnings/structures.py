"""Defined-risk structure builders: iron fly (credit) and long straddle (debit).

Only these two structures are produced; there is no code path that emits a naked
short. Every short leg of an iron fly has a long wing of equal quantity.

Iron fly (per unit, prices per share):
    shorts: call K, put K (K = listed strike nearest spot, ties -> lower strike; if K
            lacks valid quotes the candidate is skipped, never shifted to another strike)
    wings:  call K+W, put K-W, symmetric. For each pct in ``wing_widths_pct`` the
            target width spot*pct is snapped to the nearest distance W for which BOTH
            K+W (call) and K-W (put) are listed with quotes.
    mid credit     = Kc.mid + Kp.mid - (K+W)c.mid - (K-W)p.mid
    natural credit = Kc.bid + Kp.bid - (K+W)c.ask - (K-W)p.ask
    max_loss  = (W - credit) * 100 * qty ;  max_profit = credit * 100 * qty
    breakevens = K -/+ credit
    hist EV: for each historical |m| evaluate the expiry payoff at spot*(1+m) and
    spot*(1-m) with the mid credit; EV = mean payoff * 100.
    W is chosen to maximise EV / max_loss subject to max_loss <= cap and a fillable
    limit range (see pricing.credit_limits).

Long straddle: buy call K + put K. debit = mid sum, natural = ask sum,
    max_loss = debit * 100 * qty, max_profit = None (unbounded),
    hist EV = mean(|S-K| at both signs) - debit, hist_win_rate = share of those
    scenarios where intrinsic > debit.

Reported ``max_loss`` / ``max_profit`` / ``breakevens`` use ``limit_start`` (matches
the CONTRACT example: start 14.60, W 20 -> max_loss 540, max_profit 1460).
``max_loss_worst`` is the loss if filled at ``limit_floor``; it is always <= cap.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from . import pricing, sizing


@dataclass(frozen=True)
class Quote:
    option_id: str
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


def _quote(raw: Any) -> Quote | None:
    if not isinstance(raw, dict):
        return None
    try:
        bid, ask = float(raw["bid"]), float(raw["ask"])
        oid = raw["id"]
    except (KeyError, TypeError, ValueError):
        return None
    if not oid or bid < 0 or ask <= 0 or ask < bid:
        return None
    return Quote(str(oid), bid, ask)


class Chain:
    def __init__(self, rows: list[dict[str, Any]]):
        self.calls: dict[float, Quote] = {}
        self.puts: dict[float, Quote] = {}
        self.listed: set[float] = set()
        for r in rows:
            k = round(float(r["strike"]), 4)
            self.listed.add(k)
            c, p = _quote(r.get("call")), _quote(r.get("put"))
            if c:
                self.calls[k] = c
            if p:
                self.puts[k] = p
        self.strikes = sorted(set(self.calls) | set(self.puts))

    def atm_strike(self, spot: float) -> float | None:
        """Listed strike nearest spot (ties -> lower). None if that strike lacks a valid
        call AND put quote: we never fall back to a further strike for the ATM legs."""
        if not self.listed:
            return None
        k = min(self.listed, key=lambda x: (abs(x - spot), x))
        return k if (k in self.calls and k in self.puts) else None

    def wing_distances(self, k: float) -> list[float]:
        return sorted({round(c - k, 4) for c in self.calls if c > k and round(k - (c - k), 4) in self.puts})


def _leg(q: Quote, side: str, strike: float, typ: str) -> dict[str, Any]:
    return {"option_id": q.option_id, "side": side, "position_effect": "open",
            "strike": strike, "type": typ}


def scenarios(spot: float, moves: list[float]) -> list[float]:
    out = []
    for m in moves:
        a = abs(m)
        out.append(spot * (1 + a))
        out.append(spot * (1 - a))
    return out


def iron_fly_payoff(s: float, k: float, w: float, credit: float) -> float:
    """Per-share P&L at expiry for a short iron fly opened for ``credit``."""
    return credit - min(abs(s - k), w)


def evaluate_iron_fly(chain: Chain, spot: float, k: float, w: float, moves: list[float]) -> dict[str, Any] | None:
    kc, kp = chain.calls.get(k), chain.puts.get(k)
    lc, lp = chain.calls.get(round(k + w, 4)), chain.puts.get(round(k - w, 4))
    if not (kc and kp and lc and lp):
        return None
    mid = kc.mid + kp.mid - lc.mid - lp.mid
    natural = kc.bid + kp.bid - lc.ask - lp.ask
    if mid <= 0 or mid >= w:
        return None
    payoffs = [iron_fly_payoff(s, k, w, mid) for s in scenarios(spot, moves)]
    ev = mean(payoffs) * 100.0
    ml = (w - mid) * 100.0
    return {
        "width": w, "mid": mid, "natural": natural, "ev": ev, "max_loss_unit_mid": ml,
        "ev_per_dollar_risk": ev / ml, "hist_win_rate": sum(p > 0 for p in payoffs) / len(payoffs),
        "legs": [_leg(kc, "sell", k, "call"), _leg(kp, "sell", k, "put"),
                 _leg(lc, "buy", round(k + w, 4), "call"), _leg(lp, "buy", round(k - w, 4), "put")],
    }


def build_iron_fly(chain: Chain, spot: float, moves: list[float], cap: float,
                   cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Return (order-like dict, None) or (None, reason)."""
    k = chain.atm_strike(spot)
    if k is None:
        return None, "missing_atm_quotes"
    dists = chain.wing_distances(k)
    if not dists:
        return None, "no_valid_wings"
    widths: list[float] = []
    for pct in cfg["wing_widths_pct"]:
        target = spot * pct
        w = min(dists, key=lambda d: (abs(d - target), d))
        if w not in widths:
            widths.append(w)
    best: dict[str, Any] | None = None
    reason = "no_valid_wings"
    for w in widths:
        ev = evaluate_iron_fly(chain, spot, k, w, moves)
        if ev is None:
            continue
        if ev["max_loss_unit_mid"] > cap + 1e-9:
            reason = "max_loss_exceeds_cap"
            continue
        qty, qreason = sizing.quantity_for(ev["max_loss_unit_mid"], cap, cfg)
        if qty == 0:
            reason = qreason or "max_loss_exceeds_cap"
            continue
        lim = pricing.credit_limits(ev["mid"], ev["natural"], w, cap, qty, cfg)
        if lim is None:
            reason = "no_fillable_limit_range"
            continue
        start, floor, step = lim
        cand = {
            "structure": "iron_fly", "direction": "credit", "quantity": qty, "legs": ev["legs"],
            "limit_start": start, "limit_floor": floor, "limit_step": step,
            "max_loss": round((w - start) * 100 * qty, 2),
            "max_loss_worst": round((w - floor) * 100 * qty, 2),
            "max_profit": round(start * 100 * qty, 2),
            "breakevens": [round(k - start, 2), round(k + start, 2)],
            "hist_win_rate": round(ev["hist_win_rate"], 4),
            "ev_per_dollar_risk": round(ev["ev_per_dollar_risk"], 4),
            "hist_ev": round(ev["ev"] * qty, 2),
            "mid": round(ev["mid"], 4), "natural": round(ev["natural"], 4),
            "wing_width": w, "atm_strike": k,
        }
        if best is None or cand["ev_per_dollar_risk"] > best["ev_per_dollar_risk"]:
            best = cand
    if best is None:
        return None, reason
    return best, None


def build_long_straddle(chain: Chain, spot: float, moves: list[float], cap: float,
                        cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    k = chain.atm_strike(spot)
    if k is None:
        return None, "missing_atm_quotes"
    c, p = chain.calls[k], chain.puts[k]
    mid = c.mid + p.mid
    natural = c.ask + p.ask
    if mid <= 0:
        return None, "missing_atm_quotes"
    intrinsics = [abs(s - k) for s in scenarios(spot, moves)]
    ev_share = mean(intrinsics) - mid
    win = sum(i > mid for i in intrinsics) / len(intrinsics)
    qty, qreason = sizing.quantity_for(mid * 100.0, cap, cfg)
    if qty == 0:
        return None, qreason
    lim = pricing.debit_limits(mid, natural, cap, qty, cfg)
    if lim is None:
        return None, "no_fillable_limit_range"
    start, worst, step = lim
    return {
        "structure": "long_straddle", "direction": "debit", "quantity": qty,
        "legs": [_leg(c, "buy", k, "call"), _leg(p, "buy", k, "put")],
        "limit_start": start, "limit_floor": worst, "limit_step": step,
        "max_loss": round(start * 100 * qty, 2),
        "max_loss_worst": round(worst * 100 * qty, 2),
        "max_profit": None,
        "breakevens": [round(k - start, 2), round(k + start, 2)],
        "hist_win_rate": round(win, 4),
        "ev_per_dollar_risk": round(ev_share / mid, 4),
        "hist_ev": round(ev_share * 100 * qty, 2),
        "mid": round(mid, 4), "natural": round(natural, 4), "atm_strike": k,
    }, None
