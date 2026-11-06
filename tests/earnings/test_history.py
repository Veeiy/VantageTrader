import pytest

from vantage_trader.earnings.config import EngineInputError
from vantage_trader.earnings.history import compute_all, compute_moves


def bars(*rows):
    return [{"date": d, "close": c, "interpolated": i} for d, c, i in rows]


BARS = bars(
    ("2026-07-28", 100.0, False),
    ("2026-07-29", 110.0, False),   # report day
    ("2026-07-30", 99.0, False),
    ("2026-07-31", 101.0, False),
)


def test_amc_move_report_close_to_next_close():
    out = compute_moves(BARS, [{"date": "2026-07-29", "timing": "pm"}])
    assert out["moves"] == [pytest.approx(99.0 / 110.0 - 1, abs=1e-6)]
    assert out["dates"] == ["2026-07-29"]


def test_bmo_move_prior_close_to_report_close():
    out = compute_moves(BARS, [{"date": "2026-07-29", "timing": "am"}])
    assert out["moves"] == [pytest.approx(0.10, abs=1e-6)]


def test_moves_are_signed_and_chronological():
    out = compute_moves(BARS, [{"date": "2026-07-30", "timing": "pm"}, {"date": "2026-07-29", "timing": "pm"}])
    assert out["dates"] == ["2026-07-29", "2026-07-30"]
    assert out["moves"][0] < 0 < out["moves"][1]


def test_interpolated_bar_is_skipped_with_reason():
    b = bars(("2026-07-28", 100.0, False), ("2026-07-29", 105.0, True), ("2026-07-30", 107.0, False))
    out = compute_moves(b, [{"date": "2026-07-29", "timing": "am"}, {"date": "2026-07-28", "timing": "pm"}])
    assert out["moves"] == []
    assert {s["reason"] for s in out["skipped"]} == {"interpolated_or_missing_bar"}


def test_duplicated_last_bar_flagged_interpolated_is_ignored():
    # Broker quirk: last bar repeated and flagged interpolated (same date and next date variants)
    b = BARS + [{"date": "2026-07-31", "close": 101.0, "interpolated": True},
                {"date": "2026-08-03", "close": 101.0, "interpolated": True}]
    out = compute_moves(b, [{"date": "2026-07-30", "timing": "pm"}, {"date": "2026-07-31", "timing": "pm"}])
    assert out["moves"] == [pytest.approx(101.0 / 99.0 - 1, abs=1e-6)]
    assert out["skipped"] == [{"date": "2026-07-31", "reason": "interpolated_or_missing_bar"}]


def test_missing_bars_reasons():
    out = compute_moves(BARS, [
        {"date": "2026-07-31", "timing": "pm"},   # no next bar
        {"date": "2026-07-28", "timing": "am"},   # no prior bar
        {"date": "2026-08-15", "timing": "pm"},   # not in bars
        {"date": "2026-07-29", "timing": "xx"},
    ])
    reasons = [s["reason"] for s in out["skipped"]]
    assert reasons == ["no_next_bar", "no_prior_bar", "report_date_not_in_bars", "bad_timing"]


def test_compute_all_shape_and_missing_symbol():
    out = compute_all({"ARM": BARS}, {"ARM": [{"date": "2026-07-29", "timing": "pm"}],
                                      "NVDA": [{"date": "2026-07-29", "timing": "pm"}]})
    assert set(out["ARM"]) == {"moves", "dates", "skipped"}
    assert out["NVDA"]["skipped"][0]["reason"] == "no_bars_for_symbol"


def test_bad_input_raises():
    with pytest.raises(EngineInputError):
        compute_all([], {})
    with pytest.raises(EngineInputError):
        compute_moves([{"date": "nope", "close": 1}], [])
