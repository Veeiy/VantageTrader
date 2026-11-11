"""CLI per CONTRACT.md. JSON on stdout.

Exit codes: 0 success (decision may be no_trade), 2 invalid input (stdout is
{"error": ...}), 3 halted by circuit breaker (score only), 4 self-check failed
(selfcheck only). An unexpected internal error exits 1 with {"error": "internal: ..."}
(not an input problem; do not retry blindly).

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
  proposals [--proposals PATH] prints the improvement proposals ledger by status.
  selfcheck [--journal --metrics --positions --lessons --proposals --config] checks that the
    journal, positions file, metrics and ledgers agree; exits 4 when any check fails.
  project --input FILE prices a fly after the report over a spot x volatility grid (FILE is one
    projection input object or a list of them; see projection.py).
  project-check --input FILE --actual FILE splits the projection error into spot, volatility
    and the rest (ACTUAL: {"SYMBOL": {"spot", "straddle_mid", "close_cost_mid", "fill_debit"?}}).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import calibrate as calib
from . import health, history, journal, metrics, projection, proposals, reconcile, reflect, rules, scoring
from .config import EngineInputError, load_config

DEFAULT_CONFIG = "config/earnings.yaml"
DEFAULT_METRICS = "state/earnings/live_metrics.jsonl"
DEFAULT_POSITIONS = "state/earnings/positions.json"
DEFAULT_LESSONS = "state/earnings/lessons.jsonl"
DEFAULT_PROPOSALS = "state/earnings/proposals.jsonl"


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
    pp = sub.add_parser("proposals")
    pp.add_argument("--proposals", default=DEFAULT_PROPOSALS)
    pj = sub.add_parser("project")
    pj.add_argument("--input", required=True)
    pc = sub.add_parser("project-check")
    pc.add_argument("--input", required=True)
    pc.add_argument("--actual", required=True)
    sc = sub.add_parser("selfcheck")
    sc.add_argument("--journal")
    sc.add_argument("--metrics", default=DEFAULT_METRICS)
    sc.add_argument("--positions", default=DEFAULT_POSITIONS)
    sc.add_argument("--lessons", default=DEFAULT_LESSONS)
    sc.add_argument("--proposals", default=DEFAULT_PROPOSALS)
    sc.add_argument("--config")
    return p


def run(argv: list[str] | None = None) -> tuple[dict[str, Any], int]:
    args = build_parser().parse_args(argv)
    if args.cmd == "history":
        return history.compute_all(_load_json(args.bars, "bars"), _load_json(args.events, "events")), 0
    if args.cmd == "live-metrics":
        return metrics.summarize(metrics.read_metrics(args.metrics)), 0
    if args.cmd == "lessons":
        return reflect.lessons_view(reflect.read_lessons(args.lessons)), 0
    if args.cmd == "proposals":
        return proposals.proposals_view(proposals.read_proposals(args.proposals)), 0
    if args.cmd in ("project", "project-check"):
        raw = _load_json(args.input, "projection input")
        items = raw if isinstance(raw, list) else [raw]
        if not items or not all(isinstance(i, dict) for i in items):
            raise EngineInputError("projection input must be an object or a list of objects")
        if args.cmd == "project":
            return {"projections": [projection.project(i) for i in items]}, 0
        actual = _load_json(args.actual, "actual")
        if not isinstance(actual, dict):
            raise EngineInputError("actual must be an object keyed by symbol")
        missing = [i.get("symbol") for i in items if i.get("symbol") not in actual]
        if missing:
            raise EngineInputError(f"actual has no entry for {missing}")
        return {"checks": [projection.attribute(i, actual[i["symbol"]]) for i in items]}, 0
    cfg = _cfg(args)
    if args.cmd == "selfcheck":
        out = health.selfcheck(args.journal or cfg["journal_path"], args.metrics, args.positions,
                               args.lessons, args.proposals)
        return out, 0 if out["ok"] else 4
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
