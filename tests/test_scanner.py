from datetime import date, timedelta

from vantage_trader.strategy.calendar import CalendarScanner
from vantage_trader.tastytrade.streamer import Greeks


def _entry_config(**overrides):
    base = {
        "short_dte_min": 0, "short_dte_max": 0,
        "long_dte_min": 30, "long_dte_max": 60,
        "short_delta_min": 0.40, "short_delta_max": 0.55,
        "max_debit_per_spread": 250,
        "min_open_interest_short": 100,
        "min_open_interest_long": 50,
        "max_bid_ask_spread_pct": 0.20,
        "min_theta_per_dollar": 0.0,
        "direction": "auto",
    }
    base.update(overrides)
    return base


def _chain(spot_strike=500.0):
    today = date.today()
    short_exp = today.isoformat()
    long_exp = (today + timedelta(days=45)).isoformat()

    def _strike(k):
        return {
            "strike-price": f"{k:.1f}",
            "call": f"SPY   {today.strftime('%y%m%d')}C{int(k*1000):08d}",
            "put": f"SPY   {today.strftime('%y%m%d')}P{int(k*1000):08d}",
            "call-streamer-symbol": f".SPY{today.strftime('%y%m%d')}C{int(k)}",
            "put-streamer-symbol": f".SPY{today.strftime('%y%m%d')}P{int(k)}",
        }

    def _strike_long(k):
        return {
            "strike-price": f"{k:.1f}",
            "call": f"SPY   LONG_C_{int(k)}",
            "put": f"SPY   LONG_P_{int(k)}",
            "call-streamer-symbol": f".SPY_LONG_C{int(k)}",
            "put-streamer-symbol": f".SPY_LONG_P{int(k)}",
        }

    strikes_short = [_strike(k) for k in (495, 500, 505)]
    strikes_long = [_strike_long(k) for k in (495, 500, 505)]

    return {
        "items": [{
            "expirations": [
                {"date": short_exp, "strikes": strikes_short},
                {"date": long_exp, "strikes": strikes_long},
            ]
        }]
    }


def test_build_candidate_picks_atm_within_delta_band():
    chain = _chain()
    scanner = CalendarScanner(client=None, entry_config=_entry_config())
    pairs = scanner.expiration_pairs(chain)
    assert len(pairs) == 1
    short_exp, long_exp = pairs[0]

    # Spot at 500: short call deltas should be: 495 (~0.65), 500 (~0.50), 505 (~0.35)
    # The 500 call is in the [0.40, 0.55] band.
    greeks = {
        ".SPY" + date.today().strftime("%y%m%d") + "C495": Greeks(
            symbol="x", price=6.0, volatility=0.18, delta=0.65, theta=-0.10
        ),
        ".SPY" + date.today().strftime("%y%m%d") + "C500": Greeks(
            symbol="x", price=3.0, volatility=0.18, delta=0.50, theta=-0.12
        ),
        ".SPY" + date.today().strftime("%y%m%d") + "C505": Greeks(
            symbol="x", price=1.0, volatility=0.18, delta=0.35, theta=-0.10
        ),
        ".SPY_LONG_C495": Greeks(symbol="x", volatility=0.20),
        ".SPY_LONG_C500": Greeks(symbol="x", volatility=0.20),
        ".SPY_LONG_C505": Greeks(symbol="x", volatility=0.20),
    }

    # Quotes: long calls $8 mid, short call $3 mid.
    def q(bid, ask, oi=500):
        return {"bid": str(bid), "ask": str(ask), "open-interest": str(oi)}

    short_pref = "SPY   " + date.today().strftime("%y%m%d")
    quotes = {
        f"{short_pref}C00495000": q(5.95, 6.05),
        f"{short_pref}C00500000": q(2.95, 3.05),
        f"{short_pref}C00505000": q(0.95, 1.05),
        "SPY   LONG_C_495": q(5.95, 6.05),
        "SPY   LONG_C_500": q(3.95, 4.05),
        "SPY   LONG_C_505": q(1.95, 2.05),
    }

    cand = scanner.build_candidate(
        underlying="SPY",
        spot=500.0,
        short_exp=short_exp,
        long_exp=long_exp,
        side="C",
        quotes=quotes,
        greeks=greeks,
    )
    assert cand is not None
    assert cand.strike == 500.0  # ATM-band strike picked
    assert abs(cand.short_delta - 0.50) < 1e-6


def test_build_candidate_returns_none_when_no_strike_in_band():
    chain = _chain()
    # Tight delta band that excludes all strikes.
    scanner = CalendarScanner(
        client=None,
        entry_config=_entry_config(short_delta_min=0.95, short_delta_max=0.99),
    )
    pairs = scanner.expiration_pairs(chain)
    short_exp, long_exp = pairs[0]
    greeks = {}  # no greeks -> nothing to score
    cand = scanner.build_candidate(
        underlying="SPY", spot=500.0,
        short_exp=short_exp, long_exp=long_exp, side="C",
        quotes={}, greeks=greeks,
    )
    assert cand is None


def test_select_side_auto():
    scanner = CalendarScanner(client=None, entry_config=_entry_config(direction="auto"))
    # spot < strike => call (short call OTM)
    assert scanner.select_side(spot=499.0, strike=500.0) == "C"
    # spot >= strike => put (short put OTM)
    assert scanner.select_side(spot=501.0, strike=500.0) == "P"


def test_select_side_forced():
    scanner = CalendarScanner(client=None, entry_config=_entry_config(direction="call"))
    assert scanner.select_side(spot=505.0, strike=500.0) == "C"
    scanner = CalendarScanner(client=None, entry_config=_entry_config(direction="put"))
    assert scanner.select_side(spot=495.0, strike=500.0) == "P"


def test_sides_to_consider_both():
    scanner = CalendarScanner(client=None, entry_config=_entry_config(direction="both"))
    assert set(scanner.sides_to_consider(500.0, 500.0)) == {"C", "P"}
