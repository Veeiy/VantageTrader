"""CLI per CONTRACT.md. JSON on stdout.

Exit codes: 0 success (decision may be no_trade), 2 invalid input (stdout is
{"error": ...}), 3 halted by circuit breaker (score only). An unexpected internal
error exits 1 with {"error": "internal: ..."} (not an input problem; do not retry blindly).

Additive options beyond the contract (all optional, contract invocations work as-is):
  score/exit/reconcile/calibrate --config defaults to config/earnings.yaml (defaults if absent)
  score --journal defaults to config ``journal_path``; used for circuit-breaker streaks.
  exit --journal (same default) adds a ``circuit_breaker`` block for context only; exits
    are produced and the exit code is 0 even when the breaker is tripped.
  reconcile --config for cancel_by.
  live-metrics [--metrics PATH] summarises the live metrics dataset (read-only; an absent
    file gives an empty summary).
  daily-review --date YYYY-MM-DD [--journal --metrics --positions --lessons --config] builds
    the day pack for the daily reflection from files only (docs/earnings/REFLECTION.md).
  lessons [--lessons PATH] prints the lessons ledger grouped as apply_now / being_tested /
    awaiting_approval. Both are read-only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import calibrate as calib
from . import history, journal, metrics, reconcile, reflect, rules, scoring
from .config import EngineInputError, load_config

DEFAULT_CONFIG = "config/earnings.yaml"
DEFAULT_METRICS = "state/earnings/live_metrics.jsonl"
DEFAULT_POSITIONS = "state/earnings/positions.json"
DEFAULT_LESSONS = "state/earnings/lessons.jsonl"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # argparse errors -> JSON + exit 2
        raise EngineInputError(f"usage: {message}")


def _load_json(path: str, what: str) -> Any:
    p = Path(path)
    if not p.exists():
        raise EngineInputError(f"{what} file not found: {path}")
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise EngineInputError(f"{what} is not valid JSON: {e}")


def _cfg(args: argparse.Namespace) -> dict[str, Any]:
    path = getattr(args, "config", None)
    if path is None:
        return load_config(DEFAULT_CONFIG, must_exist=False)
    return load_config(path, must_exist=True)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m vantage_trader.earnings")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    s = sub.add_parser("score")
    s.add_argument("--snapshot", required=True)
    s.add_argument("--config")
    s.add_argument("--journal")
    e = sub.add_parser("exit")
    e.add_argument("--snapshot", required=True)
    e.add_argument("--config")
    e.add_argument("--journal")
    r = sub.add_parser("reconcile")
    r.add_argument("--snapshot", required=True)
    r.add_argument("--journal", required=True)
    r.add_argument("--config")
    c = sub.add_parser("calibrate")
    c.add_argument("--journal", required=True)
    c.add_argument("--config")
    h = sub.add_parser("history")
    h.add_argument("--bars", required=True)
    h.add_argument("--events", required=True)
    m = sub.add_parser("live-metrics")
    m.add_argument("--metrics", default=DEFAULT_METRICS)
    d = sub.add_parser("daily-review")
    d.add_argument("--date", required=True)
    d.add_argument("--journal")
    d.add_argument("--metrics", default=DEFAULT_METRICS)
    d.add_argument("--positions", default=DEFAULT_POSITIONS)
    d.add_argument("--lessons", default=DEFAULT_LESSONS)
    d.add_argument("--config")
    ls = sub.add_parser("lessons")
    ls.add_argument("--lessons", default=DEFAULT_LESSONS)
    return p


def run(argv: list[str] | None = None) -> tuple[dict[str, Any], int]:
    args = build_parser().parse_args(argv)
    if args.cmd == "history":
        return history.compute_all(_load_json(args.bars, "bars"), _load_json(args.events, "events")), 0
    if args.cmd == "live-metrics":
        return metrics.summarize(metrics.read_metrics(args.metrics)), 0
    if args.cmd == "lessons":
        return reflect.lessons_view(reflect.read_lessons(args.lessons)), 0
    cfg = _cfg(args)
    if args.cmd == "daily-review":
        positions = _load_json(args.positions, "positions") if Path(args.positions).exists() else None
        return reflect.day_pack(
            args.date, journal.read_journal(args.journal or cfg["journal_path"]),
            metrics.read_metrics(args.metrics), positions, reflect.read_lessons(args.lessons),
            cfg["max_loss_tolerance"]), 0
    if args.cmd == "score":
        snap = _load_json(args.snapshot, "snapshot")
        jpath = args.journal or cfg["journal_path"]
        events = journal.read_journal(jpath)
        decision, code = scoring.score(snap, cfg, events)
        decision["circuit_breaker"]["journal_path"] = jpath
        decision["circuit_breaker"]["journal_found"] = Path(jpath).exists()
        return decision, code
    if args.cmd == "exit":
        snap = _load_json(args.snapshot, "snapshot")
        out = rules.exit_decision(snap, cfg)
        jpath = args.journal or cfg["journal_path"]
        cb = rules.circuit_breaker(snap.get("account") if isinstance(snap.get("account"), dict) else {},
                                   journal.read_journal(jpath), cfg)
        cb.update(journal_path=jpath, journal_found=Path(jpath).exists(),
                  note="context only: exits always run, even when halted")
        out["circuit_breaker"] = cb
        return out, 0
    if args.cmd == "reconcile":
        snap = _load_json(args.snapshot, "snapshot")
        return reconcile.reconcile(snap, journal.read_journal(args.journal), cfg), 0
    if args.cmd == "calibrate":
        return calib.calibrate(journal.read_journal(args.journal), cfg), 0
    raise EngineInputError(f"unknown command {args.cmd}")


def main(argv: list[str] | None = None) -> int:
    try:
        out, code = run(argv)
    except EngineInputError as e:
        out, code = {"error": str(e)}, 2
    except Exception as e:  # noqa: BLE001
        out, code = {"error": f"internal: {type(e).__name__}: {e}"}, 1
    sys.stdout.write(json.dumps(out, indent=2, sort_keys=False) + "\n")
    return code
