from statistics import mean

import pytest

from vantage_trader.earnings import structures
from vantage_trader.earnings.structures import Chain, build_iron_fly, build_long_straddle, evaluate_iron_fly

from .factories import ARM_MOVES, ARM_QUOTES, cfg, chain_rows, straddle_chain

SPOT = 202.49


def _ev_per_risk(w, credit):
    pay = [credit - min(abs(s - 202.5), w) for s in structures.scenarios(SPOT, ARM_MOVES)]
    return mean(pay) * 100 / ((w - credit) * 100)


def test_atm_strike_nearest_spot():
    ch = Chain(chain_rows())
    assert ch.atm_strike(SPOT) == 202.5
    assert ch.wing_distances(202.5) == [10.0, 15.0, 20.0, 25.0]


def test_iron_fly_math_arm_w20():
    ch = Chain(chain_rows())
    ev = evaluate_iron_fly(ch, SPOT, 202.5, 20.0, ARM_MOVES)
    # mid credit = 11.50 + 11.25 - 3.50 - 3.45
    assert ev["mid"] == pytest.approx(15.80)
    # natural = sell at bid, buy at ask = 11.45 + 11.15 - 3.60 - 3.55
    assert ev["natural"] == pytest.approx(15.45)
    assert ev["max_loss_unit_mid"] == pytest.approx(420.0)
    assert ev["ev_per_dollar_risk"] == pytest.approx(_ev_per_risk(20.0, 15.80))


def test_wing_selection_maximises_ev_per_risk_within_cap():
    c = cfg()
    order, reason = build_iron_fly(Chain(chain_rows()), SPOT, ARM_MOVES, 697.5, c)
    assert reason is None
    credits = {10.0: 8.95, 15.0: 12.85, 20.0: 15.80}  # W=25 credit 17.85 -> max loss 715 > cap
    best = max(credits, key=lambda w: _ev_per_risk(w, credits[w]))
    assert order["wing_width"] == best == 20.0
    assert order["limit_start"] == 15.80
    # floor = max(20 - 6.975, 15.45, 0.92*15.80=14.536) -> 15.45
    assert order["limit_floor"] == 15.45
    assert order["limit_step"] == 0.10
    assert order["max_loss"] == 420.0 and order["max_profit"] == 1580.0
    assert order["max_loss_worst"] == 455.0 <= 697.5
    assert order["breakevens"] == [186.7, 218.3]
    assert order["quantity"] == 1
    strikes = {(l["side"], l["type"]): l["strike"] for l in order["legs"]}
    assert strikes == {("sell", "call"): 202.5, ("sell", "put"): 202.5,
                       ("buy", "call"): 222.5, ("buy", "put"): 182.5}
    assert all(l["position_effect"] == "open" for l in order["legs"])


def test_wing_selection_respects_smaller_cap():
    order, _ = build_iron_fly(Chain(chain_rows()), SPOT, ARM_MOVES, 279.0, cfg())  # cap for $300 BP
    assert order["wing_width"] == 15.0
    assert order["max_loss_worst"] <= 279.0


def test_iron_fly_no_wing_fits_cap():
    order, reason = build_iron_fly(Chain(chain_rows()), SPOT, ARM_MOVES, 90.0, cfg())
    assert order is None and reason == "max_loss_exceeds_cap"


def test_iron_fly_needs_both_wings():
    rows = [r for r in chain_rows() if r["strike"] == 202.5]
    order, reason = build_iron_fly(Chain(rows), SPOT, ARM_MOVES, 697.5, cfg())
    assert order is None and reason == "no_valid_wings"


def test_never_undefined_risk():
    order, _ = build_iron_fly(Chain(chain_rows()), SPOT, ARM_MOVES, 697.5, cfg())
    sells = [l for l in order["legs"] if l["side"] == "sell"]
    buys = [l for l in order["legs"] if l["side"] == "buy"]
    for s in sells:
        assert any(b["type"] == s["type"] for b in buys)
    st, _ = build_long_straddle(Chain(straddle_chain()), 100.0, [0.05], 697.5, cfg())
    assert all(l["side"] == "buy" for l in st["legs"])


def test_long_straddle_math():
    moves = [0.05, -0.06, 0.045, -0.055]
    st, reason = build_long_straddle(Chain(straddle_chain()), 100.0, moves, 697.5, cfg())
    assert reason is None
    assert st["mid"] == pytest.approx(4.0) and st["natural"] == pytest.approx(4.1)
    assert st["limit_start"] == 4.0
    assert st["limit_floor"] == 4.10      # min(4.10, 4.24, 6.975)
    assert st["limit_step"] == 0.10
    assert st["max_loss"] == 400.0 and st["max_profit"] is None
    assert st["breakevens"] == [96.0, 104.0]
    assert st["hist_win_rate"] == 1.0
    assert st["ev_per_dollar_risk"] == pytest.approx((5.25 - 4.0) / 4.0)


def test_long_straddle_win_rate_partial():
    st, _ = build_long_straddle(Chain(straddle_chain()), 100.0, [0.05, 0.02], 697.5, cfg())
    assert st["hist_win_rate"] == 0.5
    assert st["ev_per_dollar_risk"] == pytest.approx((3.5 - 4.0) / 4.0)


def test_long_straddle_cap_too_small():
    st, reason = build_long_straddle(Chain(straddle_chain()), 100.0, [0.05], 300.0, cfg())
    assert st is None and reason == "max_loss_exceeds_cap"


def test_quote_parsing_rejects_crossed_markets():
    rows = chain_rows({202.5: (11.6, 11.5, 11.15, 11.35)})
    assert Chain(rows).atm_strike(SPOT) is None
    assert ARM_QUOTES[202.5][0] == 11.45


def test_atm_never_falls_back_to_further_strike():
    rows = chain_rows()
    for r in rows:
        if r["strike"] == 202.5:
            r["put"] = {"id": "P202.5", "bid": None, "ask": None}
    assert Chain(rows).atm_strike(SPOT) is None
