import gzip
import json
from datetime import date, timedelta

import pytest

from vantage_trader.earnings import cli
from vantage_trader.earnings import replay as rp
from vantage_trader.earnings.config import EngineInputError
from vantage_trader.earnings.projection import call_put, straddle

EVENT = {"symbol": "AAA", "report_date": "2026-11-04", "timing": "pm", "E": "2026-11-04", "X": "2026-11-05",
         "expiry": "2026-11-06", "E_prev": "2026-11-03"}


def make_raw(spot=100.0, k=100.0, sig_pre=0.08, exit_spot=103.0, sig_post=0.05, w1=8.0, w2=16.0, symbol="AAA"):
    """Raw record whose every print comes from the pricing model (so model == traded)."""
    def leg(strike, kind):
        i = 0 if kind == "call" else 1
        return {"entry": round(call_put(spot, strike, sig_pre)[i], 4),
                "b1": round(call_put(exit_spot, strike, sig_post)[i], 4),
                "b2": round(call_put(exit_spot, strike, sig_post)[i], 4), "interp": []}
    return {"symbol": symbol, "K": k, "w1c_strike": k + w1, "w1p_strike": k - w1,
            "w2c_strike": k + w2, "w2p_strike": k - w2,
            "stock": {"entry": spot, "x_open": exit_spot, "b1": exit_spot, "b2": exit_spot},
            "legs": {"kc": leg(k, "call"), "kp": leg(k, "put"), "w1c": leg(k + w1, "call"), "w1p": leg(k - w1, "put"),
                     "w2c": leg(k + w2, "call"), "w2p": leg(k - w2, "put")},
            "quality": "ok", "status": "ok"}


def make_bars(report_days, move=0.04, last="2026-11-06", n=140, drift=0.002, prev_close=100.0):
    """Daily bars ending at ``last``; each report day (pm) is followed by a +move day."""
    days, d = [], date.fromisoformat(last)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    closes, c = {}, 50.0
    for i, day in enumerate(days):
        prev = days[i - 1].isoformat() if i else None
        if prev in report_days:
            c *= 1.0 + move
        else:
            c *= 1.0 + (drift if i % 2 else -drift)
        closes[day.isoformat()] = c
    scale = prev_close / closes["2026-11-03"]        # make the close before the entry day a known number
    return [{"date": k, "close": round(v * scale, 6), "interpolated": False} for k, v in closes.items()]


REPORT_DAYS = ["2026-05-06", "2026-06-10", "2026-07-15", "2026-08-12", "2026-09-16", "2026-10-07"]
REPORTS = [[d, "pm", 1] for d in REPORT_DAYS] + [["2026-11-04", "pm", 1], ["2027-02-03", "pm", 0]]


def test_option_sigma_round_trip_and_bounds():
    for spot, strike, sig, kind in ((100.0, 108.0, 0.08, "call"), (100.0, 92.0, 0.08, "put"), (21.2, 18.0, 0.15, "put")):
        price = call_put(spot, strike, sig)[0 if kind == "call" else 1]
        assert rp.option_sigma(spot, strike, price, kind) == pytest.approx(sig, abs=1e-5)
    assert rp.option_sigma(100.0, 95.0, 5.0, "call") is None       # exactly intrinsic
    assert rp.option_sigma(100.0, 95.0, 4.0, "call") is None       # below intrinsic
    assert rp.option_sigma(100.0, 105.0, None, "call") is None
    assert rp.option_sigma(100.0, 105.0, 100.0, "call") is None    # above the no-arbitrage bound
    with pytest.raises(EngineInputError):
        rp.option_sigma(100.0, 105.0, 1.0, "straddle")


def test_placeholder_and_interpolated_prints_are_not_prices():
    raw = {"legs": {"a": {"entry": 0.01, "b1": 0.35, "b2": 0.4, "interp": ["b1"]}}}
    assert rp._leg(raw, "a", "entry") is None      # 0.01 = no trade in the bar
    assert rp._leg(raw, "a", "b1") is None         # flagged interpolated
    assert rp._leg(raw, "a", "b2") == 0.4
    assert rp._leg(raw, "missing", "b2") is None


def test_derive_matches_the_model_when_prints_come_from_it():
    rec = rp.derive(EVENT, make_raw())
    se = straddle(100.0, 100.0, 0.08)
    assert rec["status"] == "ok" and rec["clean"] is True and rec["flags"] == []
    assert rec["straddle_entry"] == pytest.approx(se, abs=1e-3)
    assert rec["implied_pct"] == pytest.approx(se / 100.0, abs=1e-4)
    assert rec["move_b2"] == pytest.approx(0.03) and rec["week"] == "2026-11-02"
    assert rec["r_over_i_b2"] == pytest.approx(0.03 / (se / 100.0), abs=2e-3)
    assert rec["sigma_pre"] == pytest.approx(0.08, abs=1e-4) and rec["crush_b2"] == pytest.approx(0.625, abs=2e-3)
    f1 = rec["fly1"]
    assert f1["width_call"] == 8.0 and f1["width_over_straddle"] == pytest.approx(8.0 / se, abs=1e-3)
    assert f1["model"]["credit"] == pytest.approx(f1["traded"]["credit"], abs=2e-3)
    assert f1["model"]["pnl_b2_usd"] == pytest.approx(f1["traded"]["pnl_b2_usd"], abs=0.5)
    assert f1["model"]["max_loss_usd"] == pytest.approx((8.0 - f1["model"]["credit"]) * 100.0, abs=0.02)
    assert f1["traded"]["coherent_b2"] is True
    # wider wings keep more of the premium and carry more risk
    assert rec["fly2"]["model"]["credit"] > f1["model"]["credit"]
    assert rec["fly2"]["model"]["max_loss_usd"] > f1["model"]["max_loss_usd"]
    # the market's wing/body ratio is 1.0 here by construction
    for point in ("entry", "b2"):
        for v in rec["wing_sigma_ratio"][point].values():
            assert v == pytest.approx(1.0, abs=0.02)
    assert rec["short_straddle_pnl_b2_usd"] == pytest.approx((se - straddle(103.0, 100.0, 0.05)) * 100.0, abs=0.05)


def test_big_move_loses_about_the_max_loss_and_model_close_is_capped_at_the_width():
    rec = rp.derive(EVENT, make_raw(exit_spot=120.0, sig_post=0.04))
    m = rec["fly1"]["model"]
    assert m["close_b2"] == pytest.approx(8.0, abs=0.01)
    assert m["pnl_b2_usd"] == pytest.approx(-m["max_loss_usd"], abs=1.0)


def test_off_center_body_uses_the_at_the_money_implied_move():
    rec = rp.derive(EVENT, make_raw(spot=46.565, k=47.5, sig_pre=0.05, exit_spot=47.0, sig_post=0.03, w1=2.5, w2=5.0))
    assert rec["straddle_over_spot"] > rec["implied_pct"]          # the raw straddle holds intrinsic value
    assert rec["implied_pct"] == pytest.approx(straddle(46.565, 46.565, 0.05) / 46.565, abs=2e-4)
    assert rec["body_offset_pct"] == pytest.approx(47.5 / 46.565 - 1.0, abs=1e-4)


def test_stale_body_prints_are_floored_and_flagged():
    raw = make_raw(exit_spot=92.0, sig_post=0.03)
    raw["legs"]["kp"]["b2"] = 7.2            # below intrinsic (8.0): a stale print
    rec = rp.derive(EVENT, raw)
    assert "body_floored_b2" in rec["flags"]
    assert rec["straddle_b2"] >= 8.0
    raw = make_raw()
    raw["legs"]["kc"]["entry"] = raw["legs"]["kc"]["entry"] + 2.5     # call print far out of line with the put
    rec = rp.derive(EVENT, raw)
    assert "entry_parity" in rec["flags"] and rec["clean"] is False
    raw = make_raw()
    raw["legs"]["kp"]["b2"] = raw["legs"]["kp"]["b2"] + 3.0
    rec = rp.derive(EVENT, raw)
    assert "exit_parity_b2" in rec["flags"] and rec["clean"] is False


def test_placeholder_wing_removes_the_traded_variant_but_not_the_model():
    raw = make_raw()
    raw["legs"]["w1c"]["entry"] = 0.01
    rec = rp.derive(EVENT, raw)
    assert "traded" not in rec["fly1"] and "model" in rec["fly1"]
    assert "w1c" not in rec["wing_sigma_ratio"]["entry"]
    raw = make_raw()
    del raw["w2p_strike"]
    assert rp.derive(EVENT, raw)["fly2"] is None


def test_history_is_point_in_time_and_drives_the_gates():
    bars = make_bars(REPORT_DAYS, move=0.04)
    raw = make_raw(spot=101.0, sig_pre=0.08)          # +1% on the day (prior close is 100)
    rec = rp.derive(EVENT, raw, bars, REPORTS, {})
    h = rec["history"]
    assert h["n_hist"] == 6 and h["dates"] == REPORT_DAYS      # this report and the future one are ignored
    assert h["avg_hist_move"] == pytest.approx(0.04, abs=1e-6)
    assert rec["S_prev_close"] == pytest.approx(100.0, abs=1e-4)
    assert rec["intraday_pct"] == pytest.approx(0.01, abs=1e-4)
    assert rec["edge_ratio"] == pytest.approx(0.04 / (0.85 * rec["implied_pct"]), abs=2e-3)
    assert rec["gates"]["edge"] == "sell" and rec["gates"]["intraday"] == "pass" and rec["gates"]["regime_ok"] is True
    assert rec["label"] == "sell_pass"
    # the 20 sessions before the entry day hold 19 quiet days and the 4% day after the October report
    assert rec["regime20"] == pytest.approx((19 * 0.002 + 0.04) / 20, abs=3e-4)


@pytest.mark.parametrize("kwargs, expected", [
    ({"move": 0.065}, "no_edge"),
    ({"move": 0.09}, "buy_zone"),
    ({"move": 0.04, "spot": 108.0}, "sell_blocked:intraday"),
    ({"move": 0.04, "spot": 106.0}, "sell_blocked:intraday_band"),
    ({"move": 0.04, "macro": ["2026-11-04"]}, "sell_blocked:macro"),
    ({"move": 0.04, "drift": 0.06}, "sell_blocked:regime"),
    ({"move": 0.04, "spot": 108.0, "macro": ["2026-11-04"]}, "sell_blocked:intraday+macro"),
])
def test_labels(kwargs, expected):
    bars = make_bars(REPORT_DAYS, move=kwargs["move"], drift=kwargs.get("drift", 0.002))
    spot = kwargs.get("spot", 100.0)
    rec = rp.derive(EVENT, make_raw(spot=spot, exit_spot=spot), bars, REPORTS, {}, kwargs.get("macro", ()))
    assert rec["label"] == expected


def test_too_little_history_and_unpriced_events():
    bars = make_bars(REPORT_DAYS)
    rec = rp.derive(EVENT, make_raw(), bars, REPORTS[:3] + REPORTS[-2:], {})
    assert rec["history"]["n_hist"] == 3 and rec["label"] == "no_history"
    rec = rp.derive(EVENT, make_raw(), bars, [[d, "pm", 0] for d in REPORT_DAYS], {})   # no actual EPS: not used
    assert rec["history"]["n_hist"] == 0
    rec = rp.derive(EVENT, {"symbol": "AAA", "stock": {"entry": 100.0}, "status": "no_weekly", "quality": "x"}, bars, REPORTS)
    assert rec["status"] == "no_weekly" and rec["label"] == "not_priced" and rec["clean"] is False
    assert rec["history"]["n_hist"] == 6            # history is still recorded
    raw = make_raw()
    raw["legs"]["kc"]["entry"] = None
    assert rp.derive(EVENT, raw)["status"] == "no_data"
    with pytest.raises(EngineInputError):
        rp.derive(EVENT, make_raw(symbol="BBB"))
    with pytest.raises(EngineInputError):
        rp.derive({"symbol": "AAA"}, make_raw())


def test_event_row_can_carry_the_history_when_no_bars_are_given():
    ev = dict(EVENT, avg_hist_move=0.04, n_hist=6, prior_close=100.0, regime20=0.01)
    rec = rp.derive(ev, make_raw(spot=101.0))
    assert rec["history"]["n_hist"] == 6 and rec["history"]["avg_hist_move"] == 0.04
    assert rec["intraday_pct"] == pytest.approx(0.01, abs=1e-4) and rec["label"] == "sell_pass"
    assert rec["gates"]["regime_ok"] is True
    assert rp.derive(dict(ev, n_hist=3), make_raw())["label"] == "no_history"
    assert rp.derive(EVENT, make_raw())["label"] == "no_history"       # nothing known: no edge ratio
    # bars win over the row when both are given
    rec = rp.derive(dict(ev, avg_hist_move=0.5), make_raw(), make_bars(REPORT_DAYS, move=0.04), REPORTS)
    assert rec["history"]["avg_hist_move"] == pytest.approx(0.04, abs=1e-6)


def test_entry_price_cross_check_against_the_daily_close():
    bars = make_bars(REPORT_DAYS)
    close_e = next(b["close"] for b in bars if b["date"] == "2026-11-04")
    rec = rp.derive(EVENT, make_raw(spot=round(close_e * 1.03, 2)), bars, REPORTS)
    assert "entry_price_differs_from_daily_close" in rec["flags"]
    rec = rp.derive(EVENT, make_raw(spot=round(close_e, 2)), bars, REPORTS)
    assert "entry_price_differs_from_daily_close" not in rec["flags"]


def test_calibrate_wings_needs_enough_prints():
    recs = [rp.derive(EVENT, make_raw())]
    cal = rp.calibrate_wings(recs)
    assert cal["mult"]["1"] == {"entry": 1.0, "exit": 1.0} and cal["prints"]["1"]["entry"] == 2
    cal = rp.calibrate_wings(recs * 5)
    assert cal["prints"]["1"]["entry"] == 10 and cal["mult"]["1"]["entry"] == pytest.approx(1.0, abs=0.02)
    # a market that prices wings richer than the body shows up as a multiplier above 1
    raw = make_raw()
    for name, strike, i in (("w1c", 108.0, 0), ("w1p", 92.0, 1)):
        raw["legs"][name]["entry"] = round(call_put(100.0, strike, 0.08 * 1.2)[i], 4)
    cal = rp.calibrate_wings([rp.derive(EVENT, raw)] * 5)
    assert cal["mult"]["1"]["entry"] == pytest.approx(1.2, abs=0.02)
    rec = rp.derive(EVENT, raw, wing_mult={"1": {"entry": 1.2, "exit": 1.0}, "2": {"entry": 1.0, "exit": 1.0}})
    assert rec["fly1"]["model"]["credit"] == pytest.approx(rec["fly1"]["traded"]["credit"], abs=3e-3)


def test_statistics_helpers():
    assert rp.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert rp.spearman([1, 2, 3, 4], [9, 7, 5, 1]) == -1.0
    assert rp.spearman([1, 2], [1, 2]) is None and rp.spearman([1, 1, 1], [1, 2, 3]) is None
    assert rp.fisher_one_sided(9, 11, 11, 25) == pytest.approx(0.0387, abs=1e-4)
    assert rp.fisher_one_sided(0, 0, 3, 5) is None
    assert rp.fisher_one_sided(5, 10, 5, 10) > 0.5
    s = rp._stats([(100.0, 200.0), (-50.0, 100.0), (25.0, None)])
    assert s["n"] == 3 and s["wins"] == 2 and s["total_usd"] == 75.0 and s["avg_pnl_over_max_loss"] == 0.0
    assert rp._stats([]) == {"n": 0}
    assert rp._bucket(0.70, rp.EDGE_BUCKETS, ">=1.25") == "<=0.70" and rp._bucket(0.71, rp.EDGE_BUCKETS, ">=1.25") == "0.70-0.85"
    assert rp._bucket(2.0, rp.EDGE_BUCKETS, ">=1.25") == ">=1.25" and rp._bucket(None, rp.EDGE_BUCKETS, "x") == "unknown"


def _sample_records():
    recs = []
    for i, (move, exit_spot) in enumerate(((0.03, 101.0), (0.03, 109.0), (0.065, 101.0), (0.09, 112.0))):
        ev = dict(EVENT, symbol=f"S{i}")
        recs.append(rp.derive(ev, make_raw(symbol=f"S{i}", exit_spot=exit_spot), make_bars(REPORT_DAYS, move=move), REPORTS, {}))
    bad = make_raw(symbol="S9")
    bad["legs"]["kc"]["entry"] += 2.5
    recs.append(rp.derive(dict(EVENT, symbol="S9"), bad, make_bars(REPORT_DAYS, move=0.03), REPORTS, {}))
    recs.append(rp.derive(dict(EVENT, symbol="S8"), {"symbol": "S8", "status": "no_weekly", "stock": {"entry": 20.0}}))
    return recs


def test_summarize_counts_filters_and_costs():
    recs = _sample_records()
    s = rp.summarize(recs)
    assert s["counts"]["events"] == 6 and s["counts"]["by_status"] == {"ok": 5, "no_weekly": 1}
    assert s["counts"]["priced"] == 5 and s["counts"]["clean"] == 4 and s["counts"]["used"] == 4
    assert s["counts"]["flags"]["entry_parity"] == 1
    assert rp.summarize(recs, clean_only=False)["counts"]["used"] == 5
    o = s["overall"]["fly1_b2_model"]
    assert o["n"] == 4 and o["wins"] == 2            # small moves win, moves beyond the wings lose
    assert set(s["by_label"]["1"]) == {"sell_pass", "no_edge", "buy_zone"}
    assert s["by_label"]["1"]["sell_pass"]["n"] == 2
    assert s["edge_split"]["passing"]["in"]["n"] == 2 and s["edge_split"]["passing"]["out"]["n"] == 2
    assert s["edge_vs_realized"]["n"] == 4 and s["crush_post_over_pre"]["b2"]["n"] == 4
    assert s["stock_move_abs_mean"]["b2"] == pytest.approx((0.01 + 0.09 + 0.01 + 0.12) / 4, abs=1e-4)
    # a cost haircut comes off every result in proportion to its credit
    rec = recs[0]
    plain = rp.fly_row(rec, "1")
    costed = rp.fly_row(rec, "1", cost_frac=0.07)
    assert costed[0] == pytest.approx(plain[0] - 0.07 * rec["fly1"]["model"]["credit"] * 100.0, abs=0.02)
    assert rp.summarize(recs, cost_frac=0.07)["overall"]["fly1_b2_model"]["total_usd"] < o["total_usd"]
    assert rp.fly_row(recs[-1], "1") is None and rp.fly_row(rec, "1", source="nope") is None


def test_cli_replay_end_to_end(tmp_path):
    events = [dict(EVENT, symbol=f"S{i}") for i in range(3)]
    (tmp_path / "events.json").write_text(json.dumps(events))
    raws = [make_raw(symbol="S0", exit_spot=101.0), make_raw(symbol="S1", exit_spot=110.0)]
    (tmp_path / "raw_a.jsonl").write_text(json.dumps(raws[0]) + "\n")
    (tmp_path / "raw_b.jsonl").write_text(json.dumps(raws[1]) + "\n\n")
    bars = {f"S{i}": make_bars(REPORT_DAYS, move=0.03) for i in range(3)}
    (tmp_path / "bars.json.gz").write_bytes(gzip.compress(json.dumps(bars).encode()))
    (tmp_path / "reports.jsonl").write_text("".join(json.dumps({"symbol": f"S{i}", "reports": REPORTS}) + "\n" for i in range(3)))
    out_path = tmp_path / "out" / "derived.jsonl"
    args = ["replay", "--events", str(tmp_path / "events.json"), "--raw", str(tmp_path / "raw_a.jsonl"),
            str(tmp_path / "raw_b.jsonl"), "--bars", str(tmp_path / "bars.json.gz"), "--reports",
            str(tmp_path / "reports.jsonl"), "--macro-entry-dates", "2026-10-13, 2026-11-05", "--out", str(out_path)]
    out, code = cli.run(args)
    assert code == 0 and out["records"] == 2 and out["events_without_raw"] == ["S2"]
    assert out["macro_entry_dates"] == ["2026-10-13", "2026-11-05"]
    assert out["summary"]["counts"]["priced"] == 2 and out["summary"]["overall"]["fly1_b2_model"]["wins"] == 1
    lines = [json.loads(line) for line in out_path.read_text().splitlines()]
    assert [r["symbol"] for r in lines] == ["S0", "S1"] and lines[0]["label"] == "sell_pass"
    again, code = cli.run(["replay-summary", "--input", str(out_path), "--cost-frac", "0.05"])
    assert code == 0 and again["counts"]["cost_frac"] == 0.05
    assert again["overall"]["fly1_b2_model"]["total_usd"] < out["summary"]["overall"]["fly1_b2_model"]["total_usd"]
    # the same symbol twice is an input error, not a silent overwrite
    (tmp_path / "raw_b.jsonl").write_text(json.dumps(raws[0]) + "\n")
    with pytest.raises(EngineInputError):
        cli.run(args)
    (tmp_path / "raw_b.jsonl").write_text("not json\n")
    assert cli.main(args) == 2


def test_missing_wing_strikes_are_synthesized_from_the_entry_straddle():
    """Lite method (REPLAY.md): only the stock and the two body options are collected."""
    raw = make_raw()
    for key in ("w1c_strike", "w1p_strike", "w2c_strike", "w2p_strike"):
        raw.pop(key)
    for leg in ("w1c", "w1p", "w2c", "w2p"):
        raw["legs"].pop(leg)
    rec = rp.derive(EVENT, raw)
    f1, f2 = rec["fly1"], rec["fly2"]
    assert f1["synthetic_strikes"] is True and f2["synthetic_strikes"] is True
    w1 = f1["call_strike"] - 100.0
    assert f1["put_strike"] == pytest.approx(100.0 - w1) and f1["width_over_straddle"] == pytest.approx(1.0, abs=1e-3)
    assert f2["call_strike"] - 100.0 == pytest.approx(2 * w1, rel=1e-3)
    assert "traded" not in f1 and f1["model"]["pnl_b2_usd"] is not None
    assert 0 < f1["model"]["credit"] < w1
    # listed strikes still win when they are given
    assert rp.derive(EVENT, make_raw())["fly1"]["synthetic_strikes"] is False
