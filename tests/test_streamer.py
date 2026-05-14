from vantage_trader.tastytrade.streamer import GREEKS_FIELDS, Greeks, DXLinkStreamer


def test_greeks_from_row_parses_all_fields():
    row = [".SPY240614C500", "5.25", "0.18", "0.51", "0.03", "-0.08", "0.12", "0.01"]
    g = Greeks.from_row(GREEKS_FIELDS, row)
    assert g.symbol == ".SPY240614C500"
    assert g.price == 5.25
    assert g.volatility == 0.18
    assert g.delta == 0.51
    assert g.gamma == 0.03
    assert g.theta == -0.08
    assert g.vega == 0.12
    assert g.rho == 0.01


def test_greeks_from_row_handles_nan_and_blank():
    row = [".SPY240614C500", "NaN", "", None, "0.03", "-0.08", "0.12", "0.01"]
    g = Greeks.from_row(GREEKS_FIELDS, row)
    assert g.symbol == ".SPY240614C500"
    assert g.price is None
    assert g.volatility is None
    assert g.delta is None
    assert g.theta == -0.08


def test_feed_data_handler_decodes_multiple_rows():
    """Server may pack multiple Greeks records into one FEED_DATA frame."""
    s = DXLinkStreamer.__new__(DXLinkStreamer)
    s._greeks = {}
    # Two rows concatenated into one flat list.
    flat = (
        [".SPY240614C500", "5.0", "0.2", "0.5", "0.03", "-0.08", "0.10", "0.01"]
        + [".SPY240614P500", "5.1", "0.2", "-0.5", "0.03", "-0.07", "0.10", "0.01"]
    )
    msg = {"type": "FEED_DATA", "data": ["Greeks", flat]}
    s._handle_feed_data(msg)
    assert ".SPY240614C500" in s._greeks
    assert ".SPY240614P500" in s._greeks
    assert s._greeks[".SPY240614C500"].delta == 0.5
    assert s._greeks[".SPY240614P500"].delta == -0.5


def test_feed_data_handler_ignores_malformed():
    s = DXLinkStreamer.__new__(DXLinkStreamer)
    s._greeks = {}
    # Not a multiple of len(GREEKS_FIELDS) -> ignored.
    msg = {"type": "FEED_DATA", "data": ["Greeks", [".SPY240614C500", "5.0"]]}
    s._handle_feed_data(msg)
    assert s._greeks == {}


def test_feed_data_handler_ignores_non_greeks_event():
    s = DXLinkStreamer.__new__(DXLinkStreamer)
    s._greeks = {}
    msg = {"type": "FEED_DATA", "data": ["Quote", ["SPY", "500.0", "500.1"]]}
    s._handle_feed_data(msg)
    assert s._greeks == {}
