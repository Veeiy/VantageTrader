import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from vantage_trader.earnings.cli import main

from .factories import snapshot, trade

REPO = Path(__file__).resolve().parents[2]
CONFIG = str(REPO / "config" / "earnings.yaml")


def write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj))
    return str(p)


def write_journal(tmp_path, events):
    p = tmp_path / "journal.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in events))
    return str(p)


def call(capsys, argv):
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_score_subprocess_end_to_end(tmp_path):
    snap = write(tmp_path, "snap.json", snapshot())
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    r = subprocess.run([sys.executable, "-m", "vantage_trader.earnings", "score", "--snapshot", snap,
                        "--config", CONFIG], capture_output=True, text=True, cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    d = json.loads(r.stdout)
    assert d["status"] == "trade" and d["order"]["symbol"] == "ARM"
    assert d["order"]["max_loss_worst"] <= 697.5


def test_score_halted_exit_3(tmp_path, capsys):
    snap = write(tmp_path, "snap.json", snapshot(tv=350.0))
    code, d = call(capsys, ["score", "--snapshot", snap, "--config", CONFIG,
                            "--journal", str(tmp_path / "none.jsonl")])
    assert code == 3 and d["status"] == "halted" and d["order"] is None


def test_score_uses_journal_for_breaker(tmp_path, capsys):
    snap = write(tmp_path, "snap.json", snapshot())
    j = write_journal(tmp_path, trade("A", "iron_fly", 15, 20, 1) + trade("B", "iron_fly", 15, 20, 2))
    code, d = call(capsys, ["score", "--snapshot", snap, "--config", CONFIG, "--journal", j])
    assert code == 3 and "max-loss" in d["reason"]


@pytest.mark.parametrize("argv_fn", [
    lambda t: ["score", "--snapshot", str(t / "missing.json"), "--config", CONFIG],
    lambda t: ["score", "--snapshot", write(t, "bad.json", {"as_of": "x"}), "--config", CONFIG],
    lambda t: ["score", "--snapshot", write(t, "ok.json", snapshot()), "--config", str(t / "nope.yaml")],
    lambda t: ["bogus"],
    lambda t: ["score"],
])
def test_invalid_input_exit_2(tmp_path, capsys, argv_fn):
    code, d = call(capsys, argv_fn(tmp_path))
    assert code == 2 and "error" in d


def test_bad_config_exit_2(tmp_path, capsys):
    cfgp = tmp_path / "e.yaml"
    cfgp.write_text("max_loss_abs: 5000\n")
    code, d = call(capsys, ["score", "--snapshot", write(tmp_path, "s.json", snapshot()), "--config", str(cfgp)])
    assert code == 2 and "hard cap" in d["error"]


def test_corrupt_journal_exit_2(tmp_path, capsys):
    j = tmp_path / "j.jsonl"
    j.write_text("{oops\n")
    code, d = call(capsys, ["calibrate", "--journal", str(j), "--config", CONFIG])
    assert code == 2


def test_history_cli(tmp_path, capsys):
    bars = {"ARM": [{"date": "2026-07-29", "close": 100.0, "interpolated": False},
                    {"date": "2026-07-30", "close": 90.0, "interpolated": False},
                    {"date": "2026-07-30", "close": 90.0, "interpolated": True}]}
    events = {"ARM": [{"date": "2026-07-29", "timing": "pm"}, {"date": "2026-07-30", "timing": "pm"}]}
    code, d = call(capsys, ["history", "--bars", write(tmp_path, "b.json", bars),
                            "--events", write(tmp_path, "e.json", events)])
    assert code == 0
    assert d["ARM"]["moves"] == [pytest.approx(-0.1)] and d["ARM"]["skipped"][0]["reason"] == "no_next_bar"


def test_exit_cli(tmp_path, capsys):
    snap = {"as_of": "2026-11-05T14:45:00Z", "minutes_since_open": 12, "positions": [
        {"symbol": "ARM", "structure": "iron_fly", "direction": "credit", "entry_price": 15.8, "opened": "2026-11-04",
         "legs": [{"option_id": "a", "side_held": "short", "quantity": 1, "bid": 3.0, "ask": 3.2},
                  {"option_id": "b", "side_held": "short", "quantity": 1, "bid": 8.0, "ask": 8.4},
                  {"option_id": "c", "side_held": "long", "quantity": 1, "bid": 0.1, "ask": 0.2},
                  {"option_id": "d", "side_held": "long", "quantity": 1, "bid": 0.5, "ask": 0.7}]}]}
    code, d = call(capsys, ["exit", "--snapshot", write(tmp_path, "x.json", snap), "--config", CONFIG])
    assert code == 0 and d["actions"][0]["symbol"] == "ARM"


def test_reconcile_cli(tmp_path, capsys):
    snap = {"as_of": "2026-11-04T21:00:00Z", "open_positions": [{"symbol": "NVDA", "quantity": 1}],
            "recent_orders": []}
    code, d = call(capsys, ["reconcile", "--snapshot", write(tmp_path, "r.json", snap),
                            "--journal", write_journal(tmp_path, [])])
    assert code == 0 and d["consistent"] is False and d["issues"][0]["type"] == "orphan_position"


def test_calibrate_cli_never_writes_config(tmp_path, capsys):
    cfgp = tmp_path / "e.yaml"
    cfgp.write_text("sell_max_ratio: 0.85\n")
    ev = []
    for i in range(8):
        ev += trade(f"S{i}", "iron_fly", 15, 14, i + 1, realized=0.2, implied=0.1, edge=0.8)
    code, d = call(capsys, ["calibrate", "--journal", write_journal(tmp_path, ev), "--config", str(cfgp)])
    assert code == 0 and d["diff"] and d["writes_config"] is False
    assert cfgp.read_text() == "sell_max_ratio: 0.85\n"
