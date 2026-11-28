"""scripts/earnings/exit_priced_test.py: the P070 test, checked on made-up records before any real run."""
import importlib.util
import math
import sys
from pathlib import Path

import pytest

from vantage_trader.earnings.projection import implied_sigma, straddle

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "earnings"


def _load():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("exit_priced_test", SCRIPTS / "exit_priced_test.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _event(sym, day, exit_spot, moves, regime20=0.01, post=0.02, x="2026-11-17", expiry="2026-11-20", edge=0.7):
    """A clean lite-method record: stock 100, body 100, a 10-point straddle before the report."""
    pre = implied_sigma(100.0, 100.0, 10.0)
    return {"symbol": sym, "report_date": day, "status": "ok", "clean": True, "X": x, "expiry": expiry,
            "S_entry": 100.0, "K": 100.0, "straddle_entry": 10.0, "sigma_pre": pre,
            "S_b1": exit_spot, "straddle_b1": straddle(exit_spot, 100.0, post), "sigma_post_b1": post,
            "fly1": {"synthetic_strikes": True}, "history": {"moves": moves}, "regime20": regime20, "edge_ratio": edge}


def test_sessions_left_counts_the_exit_day_and_skips_the_holiday():
    m = _load()
    assert m.sessions_left("2026-11-16", "2026-11-20") == 5
    assert m.sessions_left("2026-11-24", "2026-11-27") == 3      # Thu 11/26 closed, Fri a half day counts as one
    assert m.sessions_left("2026-11-27", "2026-11-27") == 1      # an exit on expiry day


def test_projection_is_the_credit_on_quiet_history_and_the_max_loss_on_wild_history():
    m = _load()
    quiet = _event("Q", "2026-11-16", 100.0, [0.0, 0.0, 0.0, 0.0])
    f = m.capped(quiet, m.AIM, None)
    assert f["width"] == pytest.approx(15.0)
    kept = m.project(quiet, f, 1e-6, 0.07)                       # no move, no time value left: the whole credit
    assert kept == pytest.approx(f["credit"] * 100.0 * 0.93, abs=0.5)
    wild = _event("W", "2026-11-16", 100.0, [0.4, -0.4, 0.3, -0.3])
    lost = m.project(wild, f, 0.02, 0.07)                        # every past move ends beyond a wing
    assert lost == pytest.approx(-f["max_loss"] - 0.07 * f["credit"] * 100.0, abs=0.5)
    assert m.project(dict(quiet, history={"moves": []}), f, 0.02, 0.07) is None


def test_build_drops_events_for_the_stated_reasons_and_keeps_the_same_fly():
    m = _load()
    rows = [_event("A", "2026-11-16", 101.0, [0.01, -0.01, 0.02, -0.02]),
            _event("B", "2026-11-16", 101.0, [0.01, -0.01, 0.02]),                    # three past moves
            _event("C", "2026-11-16", 101.0, [0.01, -0.01, 0.02, -0.02], regime20=None),
            dict(_event("D", "2026-11-16", 101.0, [0.01] * 4), clean=False)]
    evs, drop = m.build(rows, 600.0, 1.31, 0.07)
    assert [e["symbol"] for e in evs] == ["A"]
    assert drop == {"clean": 3, "no_fly_under_cap": 0, "no_exit_price": 0, "under_4_past_moves": 1,
                    "no_regime20": 1, "no_post_stdev": 0, "used": 1}
    e = evs[0]
    assert e["max_loss"] <= 600.0 and e["sigma_exit"] == pytest.approx(1.31 * 0.01 * 2.0)   # 4 sessions left
    assert e["blocked"] is False and e["projected"] > 0
    assert m.build(rows, 100.0, 1.31, 0.07)[1]["no_fly_under_cap"] == 3                    # nothing fits a $100 cap


def test_clustered_standard_error_matches_the_hand_formula_and_grows_with_clustering():
    m = _load()
    kept = [10.0, 30.0, 20.0, 40.0]
    blocked = [-20.0, 0.0, -10.0, -30.0]
    evs = ([{"result": y, "blocked": False, "report_date": f"k{i}"} for i, y in enumerate(kept)]
           + [{"result": y, "blocked": True, "report_date": f"b{i}"} for i, y in enumerate(blocked)])
    out = m.clustered_diff(evs)
    assert out["diff"] == pytest.approx(40.0) and out["clusters"] == 8
    ssk = sum((y - 25.0) ** 2 for y in kept)
    ssb = sum((y + 15.0) ** 2 for y in blocked)
    by_hand = math.sqrt((8 / 7) * (7 / 6) * (ssk / 16 + ssb / 16))      # one event a date: CR1 is the robust formula
    assert out["se"] == pytest.approx(by_hand, abs=0.06)
    # the same eight results on two dates whose events move together: fewer independent looks
    for e in evs:
        e["report_date"] = "d1" if e["result"] in (10.0, 30.0, -20.0, 0.0) else "d2"
    assert m.clustered_diff(evs)["clusters"] == 2
    one_side = m.clustered_diff([e for e in evs if not e["blocked"]])
    assert one_side["diff"] is None and one_side["t"] is None


def test_verdict_needs_the_gap_the_t_the_better_kept_side_and_a_blocked_side_of_fifteen():
    m = _load()

    def sample(n_kept, n_blocked, kept_mean, blocked_mean):
        evs = []
        for i in range(n_kept):
            evs.append({"symbol": f"K{i}", "report_date": f"2026-10-{1 + i % 20:02d}", "blocked": False,
                        "result": kept_mean + (5.0 if i % 2 else -5.0)})
        for i in range(n_blocked):
            evs.append({"symbol": f"B{i}", "report_date": f"2026-09-{1 + i % 20:02d}", "blocked": True,
                        "result": blocked_mean + (5.0 if i % 2 else -5.0)})
        return evs

    good = m.verdict(sample(60, 20, 20.0, -20.0))
    assert good["passes"] is True and good["kept_minus_blocked"]["diff"] == pytest.approx(40.0)
    assert good["kept"]["worst"].startswith("K") and good["blocked"]["n"] == 20
    thin = m.verdict(sample(60, 10, 20.0, -20.0))
    assert thin["diff_10_and_t_2"] is True and thin["blocked_side_big_enough"] is False and thin["passes"] is False
    small_gap = m.verdict(sample(60, 20, 20.0, 15.0))
    assert small_gap["passes"] is False and small_gap["diff_10_and_t_2"] is False
    wrong_way = m.verdict(sample(60, 20, -20.0, 20.0))
    assert wrong_way["passes"] is False and wrong_way["kept_beats_whole_sample"] is False


def test_spearman_is_one_for_the_same_order_and_minus_one_for_the_reverse():
    m = _load()
    same = [{"projected": float(i), "result": float(i * i)} for i in range(6)]
    assert m.spearman(same) == pytest.approx(1.0)
    assert m.spearman([dict(e, result=-e["result"]) for e in same]) == pytest.approx(-1.0)
