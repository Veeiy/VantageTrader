"""CLI per CONTRACT.md. JSON on stdout.

Exit codes: 0 success (decision may be no_trade), 2 invalid input (stdout is
{"error": ...}), 3 halted by circuit breaker (score) or blocked (gate), 4 self-check failed
(selfcheck only), 5 lease held by the other session (lease take only). An unexpected internal error exits 1 with {"error": "internal: ..."}
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
  lessons [--lessons PATH] [--lease PATH] prints the lessons ledger grouped as apply_now /
    being_tested / awaiting_approval, plus "trader_lease": today's lease view (null when there
    is no lease file). Both are read-only.
  proposals [--proposals PATH] prints the improvement proposals ledger by status.
  selfcheck [--journal --metrics --positions --lessons --proposals --lease --config] checks that
    the journal, positions file, metrics and ledgers agree and that the lease file parses;
    exits 4 when any check fails.
  lease show [--lease PATH] [--date YYYY-MM-DD] prints who holds the trader lease for the date
    (default: today, US Pacific) and what that means (docs/earnings/FAILOVER.md).
  lease take --role head|standby --session ID [--lease PATH] [--date D] [--reason TEXT]
    [--owner-override] takes the lease, writes the file and prints the view. Exits 5 when the
    other role holds the date and the change is not allowed; stdout is then
    {"error": ..., "lease": view}. The standby needs --reason. The default lease path is
    state/earnings/trader_lease.json. The caller commits and pushes the file (the push is the lock).
  project --input FILE prices a fly after the report over a spot x volatility grid (FILE is one
    projection input object or a list of them; see projection.py).
  project-check --input FILE --actual FILE splits the projection error into spot, volatility
    and the rest (ACTUAL: {"SYMBOL": {"spot", "straddle_mid", "close_cost_mid", "fill_debit"?}}).
  replay --events FILE --raw FILE [FILE ...] [--bars FILE] [--reports FILE [FILE ...]]
    [--macro-entry-dates D1,D2] [--out FILE] [--all] [--no-calibrate] [--cost-frac X] [--config]
    scores past earnings events from raw option prices collected by read-only agents
    (docs/earnings/REPLAY.md). Writes one derived record per event to --out (JSONL) and prints
    the summary. --all keeps events whose at-the-money prints fail the put-call parity check;
    --cost-frac takes that share of the entry credit off each result as trading cost.
    --bars may be a .json or a .json.gz file.
  replay-summary --input FILE [--all] [--cost-frac X] re-summarises a derived file.
  gate [--input FILE|-] [--config] [--journal] runs ONE candidate through every entry rule
    (v1.1-v1.5) and prints the decision record (docs/earnings/GATE.md). Reads stdin when
    --input is absent or "-". Exit 0 = may be entered, 3 = blocked, 2 = bad input.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import calibrate as calib
from . import gate as gate_mod
from . import health, history, journal, lease, metrics, projection, proposals, reconcile, reflect, replay, rules, scoring
from .config import EngineInputError, load_config

DEFAULT_CONFIG = "config/earnings.yaml"
DEFAULT_METRICS = "state/earnings/live_metrics.jsonl"
DEFAULT_POSITIONS = "state/earnings/positions.json"
DEFAULT_LESSONS = "state/earnings/lessons.jsonl"
DEFAULT_PROPOSALS = "state/earnings/proposals.jsonl"
DEFAULT_LEASE = "state/earnings/trader_lease.json"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # argparse errors -> JSON + exit 2
        raise EngineInputError(f"usage: {message}")


def _load_json(path: str, what: str) -> Any:
    p = Path(path)
    if not p.exists():
        raise EngineInputError(f"{what} file not found: {path}")
    try:
        if p.suffix == ".gz":
            return json.loads(gzip.decompress(p.read_bytes()).decode())
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise EngineInputError(f"{what} is not valid JSON: {e}")


def _load_jsonl(path: str, what: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise EngineInputError(f"{what} file not found: {path}")
    out = []
    for n, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise EngineInputError(f"{what} {path} line {n} is not valid JSON: {e}")
        if not isinstance(obj, dict):
            raise EngineInputError(f"{what} {path} line {n} must be an object")
        out.append(obj)
    return out


def _replay(args: argparse.Namespace, cfg: dict[str, Any]) -> dict[str, Any]:
    events = _load_json(args.events, "events")
    if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
        raise EngineInputError("events must be a list of objects")
    raw: dict[str, dict[str, Any]] = {}
    for path in args.raw:
        for obj in _load_jsonl(path, "raw"):
            sym = obj.get("symbol")
            if not sym:
                raise EngineInputError(f"raw record without symbol in {path}")
            if sym in raw:
                raise EngineInputError(f"raw record for {sym} appears twice")
            raw[sym] = obj
    bars = _load_json(args.bars, "bars") if args.bars else {}
    reports: dict[str, Any] = {}
    for path in args.reports or []:
        for obj in _load_jsonl(path, "reports"):
            reports[obj.get("symbol")] = obj.get("reports") or []
    macro = [d.strip() for d in (args.macro_entry_dates or "").split(",") if d.strip()]
    missing = [e.get("symbol") for e in events if e.get("symbol") not in raw]

    def run_all(mult: dict[str, dict[str, float]] | None) -> list[dict[str, Any]]:
        return [replay.derive(e, raw[e["symbol"]], bars.get(e["symbol"]), reports.get(e["symbol"]), cfg, macro, mult)
                for e in events if e.get("symbol") in raw]

    records = run_all(None)
    calibration = replay.calibrate_wings(records)
    if not args.no_calibrate:
        records = run_all(calibration["mult"])
    if args.out:
        outp = Path(args.out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))
    return {"records": len(records), "events_without_raw": missing, "out": args.out,
            "wing_multipliers_used": None if args.no_calibrate else calibration["mult"],
            "macro_entry_dates": macro,
            "summary": replay.summarize(records, clean_only=not args.all, cost_frac=args.cost_frac)}


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
    ls.add_argument("--lease", default=DEFAULT_LEASE)
    pp = sub.add_parser("proposals")
    pp.add_argument("--proposals", default=DEFAULT_PROPOSALS)
    pj = sub.add_parser("project")
    pj.add_argument("--input", required=True)
    pc = sub.add_parser("project-check")
    pc.add_argument("--input", required=True)
    pc.add_argument("--actual", required=True)
    rp = sub.add_parser("replay")
    rp.add_argument("--events", required=True)
    rp.add_argument("--raw", required=True, nargs="+")
    rp.add_argument("--bars")
    rp.add_argument("--reports", nargs="+")
    rp.add_argument("--macro-entry-dates", dest="macro_entry_dates")
    rp.add_argument("--out")
    rp.add_argument("--all", action="store_true")
    rp.add_argument("--no-calibrate", dest="no_calibrate", action="store_true")
    rp.add_argument("--cost-frac", dest="cost_frac", type=float, default=0.0)
    rp.add_argument("--config")
    rs = sub.add_parser("replay-summary")
    rs.add_argument("--input", required=True)
    rs.add_argument("--all", action="store_true")
    rs.add_argument("--cost-frac", dest="cost_frac", type=float, default=0.0)
    g = sub.add_parser("gate")
    g.add_argument("--input", default="-")
    g.add_argument("--config")
    g.add_argument("--journal")
    sc = sub.add_parser("selfcheck")
    sc.add_argument("--journal")
    sc.add_argument("--metrics", default=DEFAULT_METRICS)
    sc.add_argument("--positions", default=DEFAULT_POSITIONS)
    sc.add_argument("--lessons", default=DEFAULT_LESSONS)
    sc.add_argument("--proposals", default=DEFAULT_PROPOSALS)
    sc.add_argument("--lease", default=DEFAULT_LEASE)
    sc.add_argument("--config")
    le = sub.add_parser("lease")
    lsub = le.add_subparsers(dest="lease_cmd", required=True, parser_class=_Parser)
    lshow = lsub.add_parser("show")
    lshow.add_argument("--lease", default=DEFAULT_LEASE)
    lshow.add_argument("--date")
    ltake = lsub.add_parser("take")
    ltake.add_argument("--role", required=True, choices=lease.ROLES)
    ltake.add_argument("--session", required=True)
    ltake.add_argument("--lease", default=DEFAULT_LEASE)
    ltake.add_argument("--date")
    ltake.add_argument("--reason")
    ltake.add_argument("--owner-override", dest="owner_override", action="store_true")
    return p


def _lease_cmd(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    now = datetime.now(timezone.utc)
    date = args.date or lease.pacific_today(now)
    current = lease.read_lease(args.lease)
    if args.lease_cmd == "show":
        return lease.view(current, date), 0
    try:
        new, changed = lease.take(current, args.role, args.session, date, now, args.reason, args.owner_override)
    except lease.LeaseHeld as e:
        return {"error": str(e), "lease": lease.view(e.lease, date)}, 5
    if changed:
        lease.write_lease(args.lease, new)
    return {**lease.view(new, date), "changed": changed}, 0


def _lessons_lease(path: str) -> dict[str, Any] | None:
    try:
        current = lease.read_lease(path)
    except EngineInputError as e:
        return {"error": str(e)}
    return None if current is None else lease.view(current, lease.pacific_today())


def run(argv: list[str] | None = None) -> tuple[dict[str, Any], int]:
    args = build_parser().parse_args(argv)
    if args.cmd == "history":
        return history.compute_all(_load_json(args.bars, "bars"), _load_json(args.events, "events")), 0
    if args.cmd == "live-metrics":
        return metrics.summarize(metrics.read_metrics(args.metrics)), 0
    if args.cmd == "lessons":
        return {**reflect.lessons_view(reflect.read_lessons(args.lessons)),
                "trader_lease": _lessons_lease(args.lease)}, 0
    if args.cmd == "lease":
        return _lease_cmd(args)
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
    if args.cmd == "replay-summary":
        return replay.summarize(_load_jsonl(args.input, "replay records"), clean_only=not args.all,
                                cost_frac=args.cost_frac), 0
    cfg = _cfg(args)
    if args.cmd == "replay":
        return _replay(args, cfg), 0
    if args.cmd == "selfcheck":
        out = health.selfcheck(args.journal or cfg["journal_path"], args.metrics, args.positions,
                               args.lessons, args.proposals, args.lease)
        return out, 0 if out["ok"] else 4
    if args.cmd == "daily-review":
        positions = _load_json(args.positions, "positions") if Path(args.positions).exists() else None
        return reflect.day_pack(
            args.date, journal.read_journal(args.journal or cfg["journal_path"]),
            metrics.read_metrics(args.metrics), positions, reflect.read_lessons(args.lessons),
            cfg["max_loss_tolerance"]), 0
    if args.cmd == "gate":
        if args.input == "-":
            try:
                cand = json.loads(sys.stdin.read())
            except json.JSONDecodeError as e:
                raise EngineInputError(f"candidate on stdin is not valid JSON: {e}")
        else:
            cand = _load_json(args.input, "candidate")
        jpath = args.journal or cfg["journal_path"]
        out, code = gate_mod.evaluate(cand, cfg, journal.read_journal(jpath))
        out["journal"] = {"path": jpath, "found": Path(jpath).exists()}
        return out, code
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
