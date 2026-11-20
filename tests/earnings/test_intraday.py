"""The same-day pilot gate (rules v1.15, proposal P017)."""
import json

import pytest

from vantage_trader.earnings import calibrate, intraday, journal as jr, rules
from vantage_trader.earnings.cli import main
from vantage_trader.earnings.config import ConfigError, EngineInputError

from .factories import cfg, trade

# IWM at 07:31 PT on 2026-11-16, close to the paper desk's quotes that morning.
IWM = {
    "symbol": "IWM", "spot": 274.23, "prev_close": 273.60, "K": 274, "expiry": "2026-11-16",
    "today": "2026-11-16", "now_pt": "07:31",
    "call": {"bid": 0.98, "ask": 0.99}, "put": {"bid": 0.74, "ask": 0.75},
    "wings": {"call_strike": 276, "put_strike": 272,
              "call": {"bid": 0.22, "ask": 0.23}, "put": {"bid": 0.24, "ask": 0.25}},
    "same_hours_moves": [-0.0077, -0.0136, -0.0028, -0.0027, -0.0284, 0.0041, 0.0153, -0.0020, 0.0016,
                         -0.0051, 0.0030],
    "account_value": 1994.98, "open_risk_usd": 1215, "buying_power": 914,
}
# SPY the same morning: a 4-wide fly, max loss about $124.
SPY = {
    "symbol": "SPY", "spot": 744.06, "prev_close": 739.95, "K": 744, "expiry": "2026-11-16",
    "today": "2026-11-16", "now_pt": "07:31",
    "call": {"bid": 2.25, "ask": 2.27}, "put": {"bid": 2.19, "ask": 2.21},
    "wings": {"call_strike": 748, "put_strike": 740,
              "call": {"bid": 0.81, "ask": 0.82}, "put": {"bid": 0.86, "ask": 0.87}},
    "same_hours_moves": [-0.0107, -0.0111, 0.0008, 0.0, -0.0223, -0.0070, 0.0065, -0.0010, 0.0050,
                         -0.0007, -0.0002],
    "account_value": 1994.98, "open_risk_usd": 0, "buying_power": 1900,
}


def cand(base=IWM, **over):
    c = json.loads(json.dumps(base))
    c.update(over)
    return c


def pilot_trade(symbol, pnl, day, max_loss=76.0):
    out = trade(symbol, "iron_fly", 1.25, 1.0, day, pnl=pnl, max_loss=max_loss)
    for ev in out:
        ev["kind"] = intraday.PILOT_KIND
    return out


def blocked(record):
    return record["blocked_by"]


# ------------------------------------------------------------------ the probe tier

def test_iwm_probe_passes_with_one_contract():
    d, code = intraday.evaluate(cand(), cfg())
    assert code == 0 and d["action"] == "sell" and d["tier"] == "probe" and d["contracts"] == 1
    assert d["kind"] == "intraday_0dte"
    assert d["fly"]["strikes"] == [272.0, 274.0, 276.0]
    assert d["fly"]["credit_mid"] == pytest.approx(1.26) and d["fly"]["credit_floor"] == pytest.approx(1.24)
    assert d["fly"]["max_loss_floor"] == pytest.approx(76.0)
    assert d["plan"]["time_stop_pt"] == "11:00" and d["plan"]["take_profit_close_cost"] is None
    assert d["plan"]["cut_close_cost"] is None
    assert d["metrics"]["premium_ratio"] == pytest.approx(0.8026, abs=1e-3)
    assert len(d["gates"]) == 17 and all(g["pass"] for g in d["gates"])


def test_the_premium_ratio_is_recorded_but_does_not_gate_a_probe():
    rich = cand(same_hours_moves=[0.002] * 10)
    d, code = intraday.evaluate(rich, cfg())
    assert code == 0 and d["tier"] == "probe" and d["metrics"]["premium_ratio"] > 3


def test_spy_is_not_a_probe_name_and_the_signal_tier_is_off():
    d, code = intraday.evaluate(cand(SPY), cfg())
    assert code == 3 and d["action"] == "no_trade" and d["contracts"] == 0 and d["tier"] is None
    assert blocked(d) == ["no_signal"]


def test_a_probe_above_its_max_loss_is_blocked():
    wide = cand(wings={"call_strike": 277, "put_strike": 271,
                       "call": {"bid": 0.10, "ask": 0.11}, "put": {"bid": 0.11, "ask": 0.12}})
    d, code = intraday.evaluate(wide, cfg(intraday_max_wing_over_straddle=1.8))
    assert code == 3 and "max_loss_above_cap" in blocked(d)
    assert d["fly"]["max_loss_floor"] > 150


def test_probe_tier_off_blocks_when_there_is_no_signal():
    d, code = intraday.evaluate(cand(), cfg(intraday_probe_enabled=False))
    assert code == 3 and blocked(d) == ["no_signal"]


# ------------------------------------------------------------------ the signal tier

def test_signal_tier_trades_a_larger_fly_inside_the_band():
    c = cfg(intraday_signal_enabled=True, intraday_signal_min_ratio=0.9, intraday_signal_max_ratio=1.2)
    d, code = intraday.evaluate(cand(SPY), c)
    assert d["metrics"]["premium_ratio"] == pytest.approx(1.0984, abs=2e-3)
    assert code == 0 and d["tier"] == "signal" and d["fly"]["max_loss_floor"] <= 200


def test_signal_tier_outside_the_band_is_no_signal():
    c = cfg(intraday_signal_enabled=True, intraday_signal_min_ratio=1.25)
    d, code = intraday.evaluate(cand(SPY), c)
    assert code == 3 and blocked(d) == ["no_signal"]


def test_signal_tier_respects_its_max_loss():
    c = cfg(intraday_signal_enabled=True, intraday_signal_min_ratio=0.9, intraday_max_loss=100.0,
            intraday_probe_max_loss=80.0)
    d, code = intraday.evaluate(cand(SPY), c)
    assert code == 3 and "max_loss_above_cap" in blocked(d)


def test_signal_needs_enough_history_for_the_ratio():
    c = cfg(intraday_signal_enabled=True, intraday_signal_min_ratio=0.9)
    d, code = intraday.evaluate(cand(SPY, same_hours_moves=[0.004] * 5), c)
    assert code == 3 and "insufficient_history" in blocked(d) and d["metrics"]["premium_ratio"] is None


# ------------------------------------------------------------------ single gates

@pytest.mark.parametrize("over,reason", [
    ({"symbol": "TSLA"}, "blocklisted"),
    ({"symbol": "NVDA"}, "not_a_pilot_name"),
    ({"expiry": "2026-11-20"}, "not_same_day_expiry"),
    ({"now_pt": "07:10"}, "outside_entry_window"),
    ({"now_pt": "08:05"}, "outside_entry_window"),
    ({"prev_close": 270.0}, "pre_entry_move_too_large"),
    ({"event_ahead": "Fed decision at 11:00 PT"}, "event_ahead"),
    ({"macro_veto": True}, "macro_veto"),
    ({"macro_veto": "soft: SPY -2.1%"}, "macro_veto"),
    ({"circuit_breaker": "manual halt"}, "circuit_breaker"),
    ({"call": {"bid": 0.90, "ask": 1.07}}, "spread_too_wide"),
    ({"open_intraday": 1}, "pilot_fly_already_open"),
    ({"entries_today": 1}, "pilot_entry_already_made_today"),
    ({"buying_power": None}, "buying_power_missing"),
    ({"buying_power": 250}, "exit_not_feasible"),
    ({"open_risk_usd": 1900}, "max_loss_exceeds_cap"),
    ({"wings": None}, "no_wings"),
    ({"exits_pending": "HD x2 waits for the owner's closing order"}, "morning_exit_pending"),
    ({"exits_pending": True}, "morning_exit_pending"),
    ({"same_hours_moves": [0.004] * 9}, "insufficient_history"),
])
def test_each_gate_blocks(over, reason):
    d, code = intraday.evaluate(cand(**over), cfg())
    assert code == 3 and reason in blocked(d), blocked(d)
    assert d["contracts"] == 0


def test_tsla_is_blocked_even_if_someone_lists_it():
    with pytest.raises(ConfigError):
        cfg(intraday_live_names=["SPY", "TSLA"])
    with pytest.raises(ConfigError):
        cfg(intraday_probe_names=["TSLA"], intraday_live_names=["SPY", "QQQ", "IWM"])


def test_wings_must_sit_near_one_straddle():
    far = cand(wings={"call_strike": 278, "put_strike": 270,
                      "call": {"bid": 0.03, "ask": 0.04}, "put": {"bid": 0.04, "ask": 0.05}})
    d, code = intraday.evaluate(far, cfg())
    assert code == 3 and "wings_out_of_range" in blocked(d)


def test_body_must_be_centered():
    d, code = intraday.evaluate(cand(spot=274.75, prev_close=274.0), cfg())
    assert code == 3 and "body_off_center" in blocked(d)


def test_the_clock_fills_today_and_the_time():
    from datetime import datetime, timezone
    c = cand()
    c.pop("today"), c.pop("now_pt")
    now = datetime(2026, 11, 16, 15, 31, tzinfo=timezone.utc)      # 07:31 PT
    d, code = intraday.evaluate(c, cfg(), now=now)
    assert code == 0 and d["clock"] == {"today": "2026-11-16", "now_pt": "07:31", "source": "clock"}
    late = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)      # 09:00 PT
    d, code = intraday.evaluate(c, cfg(), now=late)
    assert code == 3 and "outside_entry_window" in blocked(d)


@pytest.mark.parametrize("bad", [
    {"spot": 0}, {"K": "274"}, {"call": {"bid": 1.0, "ask": 0.9}}, {"same_hours_moves": [0.7] * 10},
    {"open_intraday": -1}, {"now_pt": "7.31"}, {"account_value": None},
])
def test_bad_input_raises(bad):
    with pytest.raises(EngineInputError):
        intraday.evaluate(cand(**bad), cfg())


# ------------------------------------------------------------------ the pilot's breaker

def test_six_pilot_losses_in_a_row_pause_the_pilot_and_three_do_not():
    three = pilot_trade("IWM", -20, 1) + pilot_trade("IWM", -15, 2) + pilot_trade("IWM", -30, 3)
    st = intraday.pilot_state(three, cfg())
    assert not st["paused"] and st["consecutive_losses"] == 3 and st["pnl_usd"] == -65.0
    six = three + pilot_trade("IWM", -10, 4) + pilot_trade("IWM", -10, 5) + pilot_trade("IWM", -10, 6)
    st = intraday.pilot_state(six, cfg())
    assert st["paused"] and st["consecutive_losses"] == 6 and st["pnl_usd"] == -95.0
    d, code = intraday.evaluate(cand(), cfg(), six)
    assert code == 3 and blocked(d) == ["pilot_paused"]
    # a config may tighten the streak, never loosen it
    assert intraday.pilot_state(three, cfg(intraday_max_consecutive_losses=3))["paused"]


def test_a_win_resets_the_streak():
    events = (pilot_trade("IWM", -20, 1) + pilot_trade("IWM", -15, 2) + pilot_trade("IWM", 25, 3)
              + pilot_trade("IWM", -30, 4))
    st = intraday.pilot_state(events, cfg())
    assert not st["paused"] and st["consecutive_losses"] == 1 and st["trades"] == 4 and st["wins"] == 1


def test_the_cumulative_loss_limit_pauses_the_pilot():
    events = pilot_trade("IWM", -76, 1) + pilot_trade("IWM", 10, 2) + pilot_trade("IWM", -76, 3) \
        + pilot_trade("IWM", 5, 4) + pilot_trade("IWM", -20, 5)
    st = intraday.pilot_state(events, cfg())
    assert st["pnl_usd"] == -157.0 and not st["paused"]          # inside the 500 budget
    st = intraday.pilot_state(events, cfg(intraday_pilot_loss_limit=150.0))
    assert st["paused"] and "at or under -150" in st["reasons"][0]
    big = events + pilot_trade("SPY", -140, 6, max_loss=140.0) + pilot_trade("SPY", 30, 7, max_loss=140.0) \
        + pilot_trade("SPY", -140, 8, max_loss=140.0) + pilot_trade("SPY", -100, 9, max_loss=140.0)
    st = intraday.pilot_state(big, cfg())
    assert st["pnl_usd"] == -507.0 and st["paused"] and "at or under -500" in st["reasons"][0]


def test_an_unknown_result_counts_as_its_max_loss():
    events = pilot_trade("IWM", None, 1, max_loss=76.0)
    events[1]["price"] = None                       # no exit price and no pnl: unknown
    st = intraday.pilot_state(events, cfg())
    assert st["pnl_usd"] == -76.0 and st["consecutive_losses"] == 1


def test_a_ledgered_restart_clears_the_record():
    events = pilot_trade("IWM", -60, 1) + pilot_trade("IWM", -60, 2) + pilot_trade("IWM", -60, 3)
    assert intraday.pilot_state(events, cfg(intraday_max_consecutive_losses=3))["paused"]
    st = intraday.pilot_state(events, cfg(intraday_max_consecutive_losses=3,
                                          intraday_pilot_reset_ts="2026-10-04T00:00:00Z"))
    assert not st["paused"] and st["trades"] == 0


def test_review_is_due_after_ten_trades():
    events = []
    for day in range(1, 11):
        events += pilot_trade("IWM", 5 if day % 2 else -5, day)
    assert intraday.pilot_state(events, cfg())["review_due"]


def test_an_owner_override_fly_counts_for_the_breaker_and_not_for_the_test():
    events = []
    for day in range(1, 10):
        events += pilot_trade("IWM", 5 if day % 2 else -5, day)
    owner = pilot_trade("IWM", -40, 10)
    owner[0]["outside_test_data"] = True            # the entry row carries the flag (2026-11-17, "Probe anyway")
    st = intraday.pilot_state(events + owner, cfg())
    assert st["trades"] == 10 and st["test_trades"] == 9 and st["override_trades"] == 1
    assert not st["review_due"]                      # nine probes: the tenth trade is the owner's
    assert st["pnl_usd"] == -35.0 and st["test_pnl_usd"] == 5.0 and st["consecutive_losses"] == 1
    # the money still counts: the loss limit reads every pilot trade
    big = pilot_trade("IWM", -150, 11, max_loss=150.0)
    big[0]["outside_test_data"] = True
    assert intraday.pilot_state(events + owner + big, cfg(intraday_pilot_loss_limit=150.0))["paused"]


def test_pilot_losses_do_not_halt_the_main_line():
    events = pilot_trade("IWM", -20, 1) + pilot_trade("IWM", -15, 2) + pilot_trade("IWM", -30, 3) \
        + pilot_trade("IWM", -20, 4)
    cb = rules.circuit_breaker({"total_value": 2000}, events, cfg())
    assert not cb["halted"] and cb["consecutive_losses"] == 0


def test_main_line_losses_still_halt_everything_including_the_pilot():
    events = []
    for day in (1, 2, 3):
        events += trade("ABC", "iron_fly", 1.0, 2.0, day, pnl=-100.0, max_loss=300.0)
    assert rules.circuit_breaker({"total_value": 2000}, events, cfg())["halted"]
    d, code = intraday.evaluate(cand(), cfg(), events)
    assert code == 3 and "circuit_breaker" in blocked(d)


def test_closed_trades_carry_the_kind_and_calibration_skips_the_pilot():
    events = pilot_trade("IWM", -20, 1)
    events += trade("ABC", "iron_fly", 2.0, 1.0, 2)
    kinds = [t["kind"] for t in jr.closed_trades(events)]
    assert kinds == ["intraday_0dte", None]
    assert calibrate.calibrate(events, cfg())["closed_trades"] == 1


# ------------------------------------------------------------------ hard caps

@pytest.mark.parametrize("over", [
    {"intraday_max_quantity": 2},
    {"intraday_max_entries_per_day": 2},
    {"intraday_probe_max_loss": 160.0},
    {"intraday_max_loss": 250.0},
    {"intraday_pilot_loss_limit": 600.0},
    {"intraday_max_consecutive_losses": 7},
    {"intraday_max_spread_pct": 0.08},
    {"intraday_max_pre_move": 0.05},
    {"intraday_time_stop": "12:30 America/Los_Angeles"},
    {"intraday_entry_end": "11:45 America/Los_Angeles"},
    {"intraday_probe_names": ["DIA"]},
    {"intraday_signal_enabled": True},
    {"intraday_live_enabled": "false"},
    {"intraday_take_profit_frac": 1.5},
])
def test_config_may_only_tighten_the_pilot(over):
    with pytest.raises(ConfigError):
        cfg(**over)


def test_config_can_switch_the_line_off():
    d, code = intraday.evaluate(cand(), cfg(intraday_live_enabled=False))
    assert code == 3 and "intraday_off" in blocked(d)


def test_take_profit_and_cut_levels_when_set():
    d, _ = intraday.evaluate(cand(), cfg(intraday_take_profit_frac=0.25, intraday_cut_frac=0.6))
    assert d["plan"]["take_profit_close_cost"] == pytest.approx(0.94, abs=0.011)
    assert d["plan"]["cut_close_cost"] == pytest.approx(1.26 + 0.6 * (2.0 - 1.26), abs=0.011)


# ------------------------------------------------------------------ CLI

def _call(capsys, argv):
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_cli_intraday_gate_exit_codes(tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(IWM))
    code, d = _call(capsys, ["intraday-gate", "--input", str(p), "--journal", str(tmp_path / "none.jsonl")])
    assert code == 0 and d["action"] == "sell" and d["tier"] == "probe" and d["journal"]["found"] is False
    p.write_text(json.dumps(cand(now_pt="09:00")))
    code, d = _call(capsys, ["intraday-gate", "--input", str(p), "--journal", str(tmp_path / "none.jsonl")])
    assert code == 3 and d["blocked_by"] == ["outside_entry_window"]
    p.write_text(json.dumps({"symbol": "IWM"}))
    code, d = _call(capsys, ["intraday-gate", "--input", str(p), "--journal", str(tmp_path / "none.jsonl")])
    assert code == 2 and "error" in d


def test_cli_intraday_status(tmp_path, capsys):
    j = tmp_path / "j.jsonl"
    j.write_text("\n".join(json.dumps(e) for e in pilot_trade("IWM", -20, 1)) + "\n")
    code, d = _call(capsys, ["intraday-status", "--journal", str(j)])
    assert code == 0 and d["pilot"]["trades"] == 1 and d["pilot"]["pnl_usd"] == -20.0
    assert d["probe_names"] == ["IWM"] and d["signal_tier"] is False
