from vantage_trader.tastytrade.models import (
    InstrumentType,
    OptionContract,
    OrderLeg,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)


def test_occ_symbol_integer_strike():
    c = OptionContract(
        underlying="SPY", expiration="2024-06-14", strike=500.0, option_type="P"
    )
    assert c.occ_symbol == "SPY   240614P00500000"


def test_occ_symbol_fractional_strike():
    c = OptionContract(
        underlying="SPY", expiration="2024-06-14", strike=500.5, option_type="C"
    )
    assert c.occ_symbol == "SPY   240614C00500500"


def test_occ_symbol_short_root_padded():
    c = OptionContract(
        underlying="F", expiration="2025-01-17", strike=12.0, option_type="C"
    )
    assert c.occ_symbol == "F     250117C00012000"


def test_streamer_symbol_integer_strike():
    c = OptionContract(
        underlying="QQQ", expiration="2025-03-21", strike=450.0, option_type="C"
    )
    assert c.streamer_symbol == ".QQQ250321C450"


def test_streamer_symbol_decimal_strike():
    c = OptionContract(
        underlying="SPY", expiration="2025-03-21", strike=500.5, option_type="P"
    )
    assert c.streamer_symbol == ".SPY250321P500.5"


def test_limit_order_payload_includes_price():
    order = OrderRequest(
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        legs=[
            OrderLeg(
                symbol="SPY   240614P00500000",
                quantity=1,
                action=OrderSide.BUY_TO_OPEN,
                instrument_type=InstrumentType.EQUITY_OPTION,
            )
        ],
        price=1.23,
        price_effect="Debit",
    )
    payload = order.to_payload()
    assert payload["order-type"] == "Limit"
    assert payload["price"] == "1.23"
    assert payload["price-effect"] == "Debit"
    assert payload["legs"][0]["action"] == "Buy to Open"
    assert payload["legs"][0]["instrument-type"] == "Equity Option"


def test_limit_order_requires_price():
    order = OrderRequest(
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        legs=[
            OrderLeg(
                symbol="SPY", quantity=1, action=OrderSide.BUY_TO_OPEN
            )
        ],
    )
    try:
        order.to_payload()
    except ValueError:
        return
    raise AssertionError("expected ValueError for missing price")
