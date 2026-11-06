from vantage_trader.earnings import pricing, sizing

from .factories import cfg


def test_cap_with_750_bp():
    assert sizing.risk_cap(750.0, cfg()) == 697.5          # 0.93*750 < 700
    assert sizing.risk_cap(5000.0, cfg()) == 700.0         # abs cap
    assert sizing.risk_cap(0.0, cfg()) == 0.0
    assert sizing.risk_cap(-5.0, cfg()) == 0.0


def test_quantity():
    c = cfg()
    assert sizing.quantity_for(420.0, 697.5, c) == (1, None)
    assert sizing.quantity_for(105.0, 697.5, c) == (1, None)           # max_quantity 1
    assert sizing.quantity_for(105.0, 697.5, cfg(max_quantity=5)) == (5, None)
    assert sizing.quantity_for(105.0, 400.0, cfg(max_quantity=5)) == (3, None)
    assert sizing.quantity_for(715.0, 697.5, c) == (0, "max_loss_exceeds_cap")
    assert sizing.quantity_for(100.0, 0.0, c) == (0, "no_buying_power")


def test_rounding():
    assert pricing.round_up(13.432) == 13.45
    assert pricing.round_up(13.35) == 13.35
    assert pricing.round_up(0.92 * 14.51) == 13.35           # 13.3492 -> 13.35
    assert pricing.round_down(4.24) == 4.20
    assert pricing.round_down(4.10) == 4.10
    assert pricing.round_nearest(14.574) == 14.55
    assert pricing.round_nearest(14.575) == 14.60


def test_steps():
    c = cfg()
    assert pricing.limit_step(2.95, c) == 0.05
    assert pricing.limit_step(3.0, c) == 0.10


def test_credit_floor_components():
    c = cfg()
    # 0.92*mid dominates: max(20-6.975, 10, 14.536) -> 14.55
    assert pricing.credit_limits(15.80, 10.0, 20.0, 697.5, 1, c) == (15.80, 14.55, 0.10)
    # cap term dominates: 20 - 5.00 = 15.00
    assert pricing.credit_limits(15.80, 10.0, 20.0, 500.0, 1, c) == (15.80, 15.00, 0.10)
    # natural dominates
    assert pricing.credit_limits(15.80, 15.42, 20.0, 697.5, 1, c) == (15.80, 15.45, 0.10)
    # small premium -> 0.05 step
    assert pricing.credit_limits(2.10, 1.90, 5.0, 697.5, 1, c) == (2.10, 1.95, 0.05)


def test_credit_floor_above_start_means_no_trade():
    assert pricing.credit_limits(15.80, 15.0, 20.0, 300.0, 1, cfg()) is None   # floor 17 > 15.80


def test_debit_worst():
    c = cfg()
    assert pricing.debit_limits(4.0, 4.1, 697.5, 1, c) == (4.0, 4.10, 0.10)
    assert pricing.debit_limits(4.0, 4.6, 697.5, 1, c) == (4.0, 4.20, 0.10)   # 1.06*mid=4.24 -> 4.20
    assert pricing.debit_limits(2.03, 2.2, 697.5, 1, c) == (2.05, 2.15, 0.05)
    assert pricing.debit_limits(4.0, 4.6, 410.0, 1, c) == (4.0, 4.10, 0.10)   # cap/100
    assert pricing.debit_limits(4.0, 4.6, 350.0, 1, c) is None                # worst < start
