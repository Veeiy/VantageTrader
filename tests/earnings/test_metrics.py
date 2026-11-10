import json

import pytest

from vantage_trader.earnings import cli, metrics
from vantage_trader.earnings.config import EngineInputError


def _entry(tid, sym, edge, implied, fill_vs_mid, spread, tick=0.01, qty=1, max_loss=150):
    return {"trade_id": tid, "record": "entry", "ts": f"2026-11-10T19:0{len(tid) % 9}:00Z", "symbol": sym,
            "kind": "earnings", "live": True, "quantity": qty,
            "signal": {"edge_ratio": edge, "implied_move": implied, "atm_spread_pct": spread},
            "execution": {"fill_credit": 1.0, "fill_vs_mid": fill_vs_mid, "tick": tick,
                          "seconds_first_order_to_last_fill": 100, "reprices": 2},
            "risk": {"max_loss_usd": max_loss}}


def _exit(tid, sym, pnl, realized, **extra):
    d = {"trade_id": tid, "record": "exit", "ts": "2026-11-11T14:50:00Z", "symbol": sym, "live": True,
         "pnl_usd": pnl, "realized_move": realized, "execution": {"fill_vs_mid": 0.9}}
    d.update(extra)
    return d


def _write(tmp_path, recs):
    p = tmp_path / "live_metrics.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return p


def test_missing_file_gives_empty_summary(tmp_path):
    out = metrics.summarize(metrics.read_metrics(tmp_path / "nope.jsonl"))
    assert out["counts"] == {"entries": 0, "closed": 0, "open": 0, "adjusts": 0, "paper": 0}
    assert out["outcomes"]["win_rate"] is None and out["trades"] == []


def test_open_and_closed_trades_and_edge_bias(tmp_path):
    recs = [
        _entry("AAA-1", "AAA", 0.8, 0.10, 0.96, 0.05),
        _entry("BBB-1", "BBB", 0.6, 0.12, 0.90, 0.17, tick=0.05),
        _entry("CCC-1", "CCC", 0.7, 0.10, 1.00, 0.08),
        _exit("AAA-1", "AAA", 60.0, -0.05),    # |0.05| / 0.10 = 0.5
        _exit("BBB-1", "BBB", -40.0, 0.18),    # 0.18 / 0.12 = 1.5
    ]
    out = metrics.summarize(metrics.read_metrics(_write(tmp_path, recs)))
    assert out["counts"]["entries"] == 3 and out["counts"]["closed"] == 2 and out["counts"]["open"] == 1
    o = out["outcomes"]
    assert o["n"] == 2 and o["wins"] == 1 and o["win_rate"] == 0.5 and o["total_pnl_usd"] == 20.0
    assert o["avg_realized_over_implied"] == 1.0
    assert o["edge_bias"] == round(1.0 / 0.7, 4)
    ex = out["entry_execution"]
    assert ex["tight_spread"]["n"] == 2 and ex["wide_spread"]["n"] == 1
    assert ex["wide_spread"]["avg_fill_vs_mid"] == 0.9
    assert set(ex["by_tick"]) == {"0.01", "0.05"}
    status = {t["trade_id"]: t["status"] for t in out["trades"]}
    assert status == {"AAA-1": "closed", "BBB-1": "closed", "CCC-1": "open"}


def test_adjust_sets_quantity_and_is_reported_as_cost_not_outcome(tmp_path):
    recs = [
        _entry("AAA-1", "AAA", 0.8, 0.10, 0.96, 0.05, qty=2),
        {"trade_id": "AAA-1", "record": "adjust", "ts": "2026-11-10T19:54:00Z", "symbol": "AAA", "live": True,
         "tag": "rebalance", "closed_quantity": 1, "open_quantity": 1, "pnl_usd": -10.32,
         "risk": {"max_loss_usd": 75}},
    ]
    out = metrics.summarize(metrics.read_metrics(_write(tmp_path, recs)))
    assert out["adjust_cost_usd"] == -10.32
    assert out["outcomes"]["n"] == 0 and out["counts"]["open"] == 1
    assert out["trades"][0]["quantity"] == 1 and out["trades"][0]["max_loss_usd"] == 75


def test_rebalance_exit_is_left_out_of_edge_statistics(tmp_path):
    recs = [
        _entry("AAA-1", "AAA", 0.8, 0.10, 0.96, 0.05),
        _exit("AAA-1", "AAA", -12.0, 0.01, tag="rebalance"),
    ]
    out = metrics.summarize(metrics.read_metrics(_write(tmp_path, recs)))
    assert out["counts"]["closed"] == 1 and out["outcomes"]["n"] == 0


def test_paper_records_are_counted_separately(tmp_path):
    recs = [
        _entry("AAA-1", "AAA", 0.8, 0.10, 0.96, 0.05),
        {"trade_id": "ZZZ-P1", "record": "paper", "ts": "2026-11-10T19:46:00Z", "symbol": "ZZZ", "live": False,
         "pnl_mid_usd": 110.0, "pnl_natural_usd": 87.0},
        {"trade_id": "YYY-P1", "record": "paper", "ts": "2026-11-10T19:46:00Z", "symbol": "YYY", "live": False},
    ]
    out = metrics.summarize(metrics.read_metrics(_write(tmp_path, recs)))
    assert out["counts"]["entries"] == 1 and out["counts"]["paper"] == 2
    assert out["paper"] == {"n": 2, "pnl_mid_usd": 110.0, "pnl_natural_usd": 87.0, "scored": 1}


def test_bad_lines_are_input_errors(tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_text("{not json}\n")
    with pytest.raises(EngineInputError):
        metrics.read_metrics(p)
    p.write_text(json.dumps({"record": "entry"}) + "\n")
    with pytest.raises(EngineInputError):
        metrics.read_metrics(p)


def test_cli_live_metrics(tmp_path):
    p = _write(tmp_path, [_entry("AAA-1", "AAA", 0.8, 0.10, 0.96, 0.05)])
    out, code = cli.run(["live-metrics", "--metrics", str(p)])
    assert code == 0 and out["counts"]["entries"] == 1
