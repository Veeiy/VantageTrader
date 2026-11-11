import pytest

from vantage_trader.earnings import pricing, sizing

from .factories import cfg


def test_cap_with_750_account_value():
    assert sizing.risk_cap(750.0, cfg()) == 697.5          # 0.93*750 < 1000
    assert sizing.risk_cap(5000.0, cfg()) == 1000.0        # abs cap (2026-11-11: $1,000)
    assert sizing.risk_cap(1075.0, cfg()) == 999.75        # under about $1,075 the 0.93 factor binds
    assert sizing.risk_cap(0.0, cfg()) == 0.0
    assert sizing.risk_cap(-5.0, cfg()) == 0.0


def test_risk_budget_counts_open_risk():
    assert sizing.risk_budget(1339.0, 172.0, cfg()) == 828.0
    assert sizing.risk_budget(1339.0, 1200.0, cfg()) == 0.0


def test_no_data_phase_since_v17():
    c = cfg(max_quantity=5)
    assert sizing.max_quantity(0, c) == 5 and sizing.max_quantity(10, c) == 5


def test_name_target():
    assert sizing.name_target(1327.0, cfg()) == 159.24          # 12% of the account
    assert sizing.name_target(5000.0, cfg()) == 350.0           # never above the $350 name cap
    assert sizing.name_target(0.0, cfg()) == 0.0


def test_plan_by_risk():
    c = cfg()
    p = sizing.plan(50.0, 50.0, 1327.0, 0.0, c)                 # 159.24 / 50 -> 3
    assert (p["planned"], p["now"], p["later"], p["binding"]) == (3, 3, 0, "name_target_reached")
    p = sizing.plan(50.0, 50.0, 1327.0, 0.0, c, phase="early")  # half the target: 79.62 / 50 -> 1
    assert (p["planned"], p["now"], p["later"]) == (3, 1, 2)
    p = sizing.plan(300.0, 50.0, 1327.0, 0.0, c)                # above the target, under the cap: 1
    assert (p["planned"], p["now"]) == (1, 1)
    p = sizing.plan(300.0, 50.0, 1327.0, 0.0, c, phase="early")
    assert p["now"] == 1                                        # one contract may always go early
    p = sizing.plan(400.0, 50.0, 1327.0, 0.0, c)                # one contract above $350: none
    assert p["planned"] == 0 and p["binding"] == "name_risk_cap"
    p = sizing.plan(50.0, 50.0, 1327.0, 950.0, c)               # $50 of budget left
    assert p["planned"] == 0 and p["binding"] == "max_loss_exceeds_cap"
    p = sizing.plan(50.0, 50.0, 1327.0, 1000.0, c)
    assert p["planned"] == 0 and p["binding"] == "no_buying_power"
    p = sizing.plan(100.0, 50.0, 1327.0, 0.0, c)                # 1.59 -> nearest is 2 ($200, above the target)
    assert (p["planned"], p["binding"]) == (2, "name_target_reached")
    p = sizing.plan(100.0, 50.0, 1327.0, 0.0, c, phase="early")  # early part rounds DOWN: 0 -> the one allowed
    assert (p["now"], p["later"]) == (1, 1)
    p = sizing.plan(10.0, 10.0, 5000.0, 0.0, c)                 # 350 / 10 = 35 -> max_quantity 10
    assert p["planned"] == 10 and p["binding"] == "max_quantity"
    assert sizing.plan(None, 50.0, 1327.0, 0.0, c)["binding"] == "invalid_max_loss"
    with pytest.raises(ValueError):
        sizing.plan(50.0, 50.0, 1327.0, 0.0, c, phase="late")


def test_plan_adds_count_what_is_held():
    c = cfg()
    p = sizing.plan(50.0, 50.0, 1327.0, 94.0, c, held_qty=1, held_max_loss=44.0)       # (159.24-44)/50 -> 2
    assert (p["planned"], p["now"]) == (2, 2)
    p = sizing.plan(50.0, 50.0, 1327.0, 94.0, c, held_qty=1, held_max_loss=44.0, phase="early")
    assert (p["planned"], p["now"], p["binding"]) == (2, 0, "early_tranche_full")      # 79.62-44 < 50
    p = sizing.plan(130.0, 50.0, 1327.0, 94.0, c, held_qty=1, held_max_loss=44.0)      # 0.89 -> 1 (name at $174)
    assert (p["planned"], p["now"]) == (1, 1)
    p = sizing.plan(250.0, 50.0, 1327.0, 94.0, c, held_qty=1, held_max_loss=44.0)      # 0.46 -> 0
    assert p["planned"] == 0 and p["binding"] == "name_target_reached"
    p = sizing.plan(50.0, 50.0, 1327.0, 300.0, c, held_qty=3, held_max_loss=150.0)
    assert p["planned"] == 0 and p["binding"] == "name_target_reached"                 # no "one is allowed" on an add
    p = sizing.plan(50.0, 50.0, 1327.0, 94.0, c, held_qty=10, held_max_loss=44.0)
    assert p["planned"] == 0 and p["binding"] == "max_quantity"


def test_quantity():
    c = cfg()
    assert sizing.quantity_for(420.0, 697.5, c) == (1, None)
    assert sizing.quantity_for(105.0, 697.5, cfg(max_quantity=1)) == (1, None)
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
