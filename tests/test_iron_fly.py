import pytest

from vantage_trader.strategy.iron_fly import build_iron_fly_close, build_iron_fly_open, iron_fly_max_loss


def test_open_is_one_credit_order_with_four_legs_wings_first():
    p = build_iron_fly_open("SPY", "2026-11-17", body=744, put_wing=740, call_wing=748, credit=2.75).to_payload()
    assert p["order-type"] == "Limit" and p["time-in-force"] == "Day"
    assert p["price"] == "2.75" and p["price-effect"] == "Credit"
    assert [(leg["symbol"], leg["action"], leg["quantity"]) for leg in p["legs"]] == [
        ("SPY   261117P00740000", "Buy to Open", 1),
        ("SPY   261117C00748000", "Buy to Open", 1),
        ("SPY   261117P00744000", "Sell to Open", 1),
        ("SPY   261117C00744000", "Sell to Open", 1),
    ]
    assert all(leg["instrument-type"] == "Equity Option" for leg in p["legs"])


def test_close_is_one_debit_order_shorts_first():
    p = build_iron_fly_close("hd", "2026-11-20", body=347.5, put_wing=330, call_wing=365, debit=11.4,
                             quantity=2).to_payload()
    assert p["price"] == "11.40" and p["price-effect"] == "Debit"
    assert [(leg["symbol"], leg["action"], leg["quantity"]) for leg in p["legs"]] == [
        ("HD    261120P00347500", "Buy to Close", 2),
        ("HD    261120C00347500", "Buy to Close", 2),
        ("HD    261120P00330000", "Sell to Close", 2),
        ("HD    261120C00365000", "Sell to Close", 2),
    ]


def test_max_loss_uses_the_wider_wing():
    assert iron_fly_max_loss(744, 740, 748, 2.75) == 125.0
    assert iron_fly_max_loss(347.5, 330, 365, 11.925, quantity=2) == 1115.0
    assert iron_fly_max_loss(100, 95, 107, 3.0) == 400.0


@pytest.mark.parametrize("kwargs", [
    dict(underlying="TSLA", body=380, put_wing=370, call_wing=390, credit=6.0),
    dict(underlying="SPY", body=744, put_wing=744, call_wing=748, credit=2.0),
    dict(underlying="SPY", body=744, put_wing=748, call_wing=740, credit=2.0),
    dict(underlying="SPY", body=744, put_wing=740, call_wing=748, credit=0.0),
    dict(underlying="SPY", body=744, put_wing=740, call_wing=748, credit=4.0),
    dict(underlying="SPY", body=744, put_wing=740, call_wing=748, credit=2.0, quantity=0),
    dict(underlying="SPY", body=744, put_wing=740, call_wing=748, credit=2.0, quantity=1.5),
])
def test_bad_flies_are_refused(kwargs):
    with pytest.raises(ValueError):
        build_iron_fly_open(expiration="2026-11-17", **kwargs)
