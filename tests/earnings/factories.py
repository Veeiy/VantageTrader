"""Shared test data for the earnings engine."""
from __future__ import annotations

import copy

from vantage_trader.earnings.config import validate

# ARM example: spot 202.49, 202.5 call 11.45/11.55, put 11.15/11.35. Wing quotes made up.
ARM_QUOTES = {
    # strike: (call bid, call ask, put bid, put ask)
    177.5: (26.40, 27.40, 2.40, 2.50),
    182.5: (21.60, 22.40, 3.35, 3.55),
    187.5: (16.80, 17.60, 4.80, 5.00),
    192.5: (12.40, 13.10, 6.70, 6.90),
    202.5: (11.45, 11.55, 11.15, 11.35),
    212.5: (6.90, 7.10, 15.80, 16.60),
    217.5: (4.90, 5.10, 20.10, 21.00),
    222.5: (3.40, 3.60, 24.60, 25.50),
    227.5: (2.40, 2.50, 29.30, 30.20),
}
ARM_MOVES = [-0.062, -0.134, -0.012, 0.057, -0.101, 0.074]


def chain_rows(quotes=ARM_QUOTES):
    rows = []
    for k, (cb, ca, pb, pa) in sorted(quotes.items()):
        rows.append({"strike": k,
                     "call": {"id": f"C{k}", "bid": cb, "ask": ca, "oi": 100},
                     "put": {"id": f"P{k}", "bid": pb, "ask": pa, "oi": 100}})
    return rows


def arm_candidate(**over):
    c = {
        "symbol": "ARM", "report_date": "2026-11-04", "timing": "pm", "verified": True,
        "spot": 202.49, "expiry": "2026-11-06", "historical_moves": list(ARM_MOVES),
        "intraday_move": 0.012, "chain": chain_rows(), "flags": [],
    }
    c.update(over)
    return c


def snapshot(candidates=None, bp=750.0, tv=750.0, open_positions=None):
    return {
        "as_of": "2026-11-04T19:55:00Z",
        "account": {"account_number": "XXXX3413", "buying_power": bp, "total_value": tv,
                    "human_must_approve_trades": False},
        "open_positions": open_positions or [],
        "candidates": [arm_candidate()] if candidates is None else candidates,
    }


def cfg(**over):
    return validate(dict(over))


# The total risk cap before rules v1.11 (2026-11-13): min($1,000, 0.93 x account value).
# Numeric cases written before that date keep it, so they still test the ceiling mechanism.
LEGACY_CAP = {"max_loss_abs": 1000.0, "max_loss_bp_frac": 0.93}


def cfg_legacy_cap(**over):
    return validate({**LEGACY_CAP, **over})


def straddle_chain(spot=100.0, call=(2.0, 2.1), put=(1.9, 2.0)):
    """Single-strike chain at 100 for long straddle tests."""
    return [{"strike": 100.0, "call": {"id": "C100", "bid": call[0], "ask": call[1]},
             "put": {"id": "P100", "bid": put[0], "ask": put[1]}},
            {"strike": 95.0, "call": {"id": "C95", "bid": 5.5, "ask": 5.7}, "put": {"id": "P95", "bid": 0.3, "ask": 0.4}},
            {"strike": 105.0, "call": {"id": "C105", "bid": 0.3, "ask": 0.4}, "put": {"id": "P105", "bid": 5.5, "ask": 5.7}}]


def deep(x):
    return copy.deepcopy(x)


def straddle_candidate(moves, **over):
    c = {"symbol": "XYZ", "report_date": "2026-11-04", "timing": "pm", "verified": True,
         "spot": 100.0, "expiry": "2026-11-06", "historical_moves": list(moves),
         "intraday_move": 0.0, "chain": straddle_chain(), "flags": []}
    c.update(over)
    return c


def trade(symbol, structure, entry, exit_, day, *, implied=0.09, edge=0.8, realized=0.05,
          max_loss=500.0, qty=1, pnl=None):
    """entry_filled + exit_filled pair; day is an int used to order timestamps."""
    e = {"ts": f"2026-10-{day:02d}T19:55:00Z", "event": "entry_filled", "symbol": symbol,
         "structure": structure, "order_id": f"E{symbol}{day}", "price": entry, "quantity": qty,
         "implied_move": implied, "edge_ratio": edge, "max_loss": max_loss}
    x = {"ts": f"2026-10-{day:02d}T23:00:00Z", "event": "exit_filled", "symbol": symbol,
         "structure": structure, "order_id": f"X{symbol}{day}", "price": exit_, "quantity": qty,
         "realized_move": realized}
    if max_loss is None:
        e.pop("max_loss")
    if pnl is not None:
        x["pnl"] = pnl
    return [e, x]
