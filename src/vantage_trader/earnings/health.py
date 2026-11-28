"""Self-check: do the files that drive the loop agree with each other?

Run after every journal write and before every commit
(``python -m vantage_trader.earnings selfcheck``). It reads files only. It does not
replace ``reconcile`` (journal vs a broker snapshot); it catches the cheaper class of
error where the journal, positions file and metrics drift apart.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import journal as jr
from . import lease as ls
from . import metrics as mt
from . import proposals as pr
from . import reflect as rf
from .config import EngineInputError


def _positions(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise EngineInputError(f"positions file is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise EngineInputError("positions file must be a JSON object")
    return data


def _lease(path: str | None) -> str:
    current = ls.read_lease(path) if path else None
    if current is None:
        return "no lease file"
    return f"{current['holder']} holds {current['date']}"


FUTURE_TOLERANCE = timedelta(minutes=2)
NAME_CEILING_FRAC = 0.30   # P044: the same line the gate applies to the agent's own entries


def _ts(value: Any) -> datetime | None:
    """A record's ``ts`` as an aware UTC time; None when absent or not ISO."""
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def selfcheck(journal: str, metrics: str, positions: str, lessons: str, proposals: str,
              lease: str | None = None, now: datetime | None = None,
              daytrade: str | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    loaded: dict[str, Any] = {}

    def run(name: str, fn: Callable[[], str]) -> None:
        try:
            checks.append({"check": name, "ok": True, "detail": fn()})
        except (EngineInputError, ValueError, KeyError, TypeError) as e:
            checks.append({"check": name, "ok": False, "detail": str(e)})

    def load(key: str, reader: Callable[[str], Any], path: str) -> Callable[[], str]:
        def inner() -> str:
            loaded[key] = reader(path)
            return f"{len(loaded[key])} records" if hasattr(loaded[key], "__len__") else "ok"
        return inner

    run("journal_parses", load("journal", jr.read_journal, journal))
    run("metrics_parse", load("metrics", mt.read_metrics, metrics))
    run("lessons_parse", load("lessons", rf.read_lessons, lessons))
    run("proposals_parse", load("proposals", pr.read_proposals, proposals))
    run("positions_parse", load("positions", _positions, positions))
    run("lease_parses", lambda: _lease(lease))

    def positions_match_journal() -> str:
        engine = {s: int(v["quantity"]) for s, v in jr.open_state(loaded["journal"])["positions"].items()}
        book = {str(o["symbol"]).upper(): int(o["quantity"]) for o in loaded["positions"].get("open", []) or []}
        if engine != book:
            raise ValueError(f"journal says {engine}, positions file says {book}")
        return f"open: {book or 'flat'}"

    def metrics_match_positions() -> str:
        live = [r for r in loaded["metrics"] if r.get("live", True) and r.get("record") != "paper"]
        entered = {r["trade_id"]: str(r.get("symbol")).upper() for r in live if r["record"] == "entry"}
        exited = {r["trade_id"] for r in live if r["record"] == "exit"}
        open_syms = sorted(sym for tid, sym in entered.items() if tid not in exited)
        book = sorted(str(o["symbol"]).upper() for o in loaded["positions"].get("open", []) or [])
        if open_syms != book:
            raise ValueError(f"metrics show open {open_syms}, positions file shows {book}")
        return f"{len(book)} open trade(s) have entry records"

    def risk_within_cap() -> str:
        risk = loaded["positions"].get("risk")
        opens = loaded["positions"].get("open", []) or []
        if not risk:
            if opens:
                raise ValueError("open positions but no risk block in the positions file")
            return "flat"
        total = float(risk["total_max_loss_usd"]) + float(risk.get("exit_reserves_usd", 0))
        summed = sum(float(o.get("max_loss_usd") or 0) for o in opens)
        if abs(summed - float(risk["total_max_loss_usd"])) > 0.5:
            raise ValueError(f"risk block says {risk['total_max_loss_usd']}, positions sum to {summed}")
        if total > float(risk["cap_usd"]) + 1e-9:
            raise ValueError(f"max loss plus reserves {total} is above the cap {risk['cap_usd']}")
        return f"{total:.0f} of {float(risk['cap_usd']):.0f}"

    def name_within_ceiling() -> str:
        # P044 / P103 (2026-11-27): no name carries more than 30% of the account value in max loss.
        # ANT (Brad's 5 shares, 449.94 at cost) went from 23% to 32% of the account on 2026-11-24
        # when the account shrank (a loss and a withdrawal), and three closes passed without a
        # word to him. A name above the line is allowed only with a ``ceiling_notice`` on the
        # position: the day he was told, with the share and the trim.
        value = loaded["positions"].get("account_value")
        opens = loaded["positions"].get("open", []) or []
        if not opens:
            return "flat"
        if not isinstance(value, (int, float)) or value <= 0:
            return "no account value on file: not checked"
        over, noted = [], []
        for o in opens:
            ml = float(o.get("max_loss_usd") or 0)
            if ml > NAME_CEILING_FRAC * float(value) + 0.005:
                label = f"{str(o.get('symbol')).upper()} {ml:.2f} = {ml / float(value):.1%} of {float(value):.2f}"
                (noted if o.get("ceiling_notice") else over).append(label)
        if over:
            raise ValueError("above the 30% per-name ceiling (P044) with no ceiling_notice on the position: "
                             + "; ".join(over) + ". Tell Brad the share and the trim, then record it")
        if noted:
            return "above the ceiling, owner told: " + "; ".join(noted)
        return f"{len(opens)} name(s) at or under 30% of {float(value):.2f}"

    def no_future_timestamps() -> str:
        # Twice on 2026-11-13 the head wrote ledger times ahead of the clock (P037).
        clock = now or datetime.now(timezone.utc)
        late: list[str] = []
        for key in ("journal", "metrics", "lessons", "proposals"):
            for r in loaded.get(key) or []:
                t = _ts(r.get("ts")) if isinstance(r, dict) else None
                if t is not None and t > clock + FUTURE_TOLERANCE:
                    late.append(f"{key} {r.get('id') or r.get('trade_id') or r.get('symbol') or ''} {r['ts']}".replace("  ", " "))
        t = _ts((loaded.get("positions") or {}).get("as_of"))
        if t is not None and t > clock + FUTURE_TOLERANCE:
            late.append(f"positions as_of {loaded['positions']['as_of']}")
        if late:
            raise ValueError(f"{len(late)} record(s) dated ahead of the clock ({clock:%Y-%m-%dT%H:%MZ}): " + "; ".join(late[:5]))
        return "no record is dated ahead of the clock"

    def exit_ratio_matches_mid() -> str:
        # P085 (2026-11-24): the DKS exit carried fill_vs_mid 0.625, the difference fill - mid;
        # round_trip_cost reads it as the ratio mid / fill and showed 0.49 instead of 0.07.
        bad: list[str] = []
        seen = 0
        for r in loaded["metrics"]:
            if r.get("record") != "exit":
                continue
            x = r.get("execution") or {}
            fvm, mid, debit = x.get("fill_vs_mid"), x.get("close_cost_mid_at_read"), x.get("fill_debit")
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (fvm, mid, debit)) or not debit:
                continue
            seen += 1
            if abs(float(fvm) - float(mid) / float(debit)) > 0.01:
                bad.append(f"{r.get('trade_id')}: fill_vs_mid {fvm}, mid / fill is {float(mid) / float(debit):.4f}")
        if bad:
            raise ValueError("exit fill_vs_mid is the ratio close_cost_mid_at_read / fill_debit: " + "; ".join(bad[:5]))
        return f"{seen} exit record(s) carry a matching ratio"

    def paper_results_within_max_loss() -> str:
        # P094 (2026-11-25): 25 paper desk results read worse than their fly could lose, because
        # deep in-the-money legs were priced from wide quotes; the desk's natural total for the
        # day was -2,205 against -1,575 at the floors.
        openings = {r.get("trade_id"): r for r in loaded["metrics"] if mt._is_paper_opening(r)}
        bad: list[str] = []
        seen = 0
        for r in loaded["metrics"]:
            if r.get("record") != "paper" or not r.get("result"):
                continue
            floors = mt.paper_floors(openings.get(r.get("trade_id")) or r)
            if floors is None:
                continue
            seen += 1
            for field, floor in zip(mt.PAPER_PNL_FIELDS, floors):
                v = r.get(field)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v < floor - 0.01:
                    bad.append(f"{r.get('trade_id')}: {field} {v} under {round(floor, 2)}")
        if bad:
            raise ValueError("a paper result is worse than its structure's max loss (cap it, keep the "
                             "quoted figure): " + "; ".join(bad[:5]))
        return f"{seen} paper result(s) inside their max loss"

    def paper_desk_imported() -> str:
        # P095 (2026-11-25): the desk files of 11/20, 11/23 and 11/24 (69 lines, 23 results) were
        # never imported; the reflections quoted their totals from the hand-back message.
        root = Path(daytrade) if daytrade else Path(metrics).parent / "daytrade"
        if not root.is_dir():
            return "no desk directory"
        today = ls.pacific_today(now)
        have = {mt._paper_key(r) for r in loaded["metrics"] if r.get("record") == "paper"}
        missing: list[str] = []
        files = 0
        for f in sorted(root.glob("*/paper_desk.jsonl")):
            if f.parent.name >= today:      # today's file is imported at the 12:15 PT run
                continue
            files += 1
            n = 0
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if mt._paper_reject_reason(rec) is None and mt._paper_key(rec) not in have:
                    n += 1
            if n:
                missing.append(f"{f.parent.name}: {n} line(s)")
        if missing:
            raise ValueError("paper desk file(s) of an earlier day are not fully imported (run paper-import): "
                             + "; ".join(missing[:5]))
        return f"{files} earlier desk file(s) fully imported"

    run("no_future_timestamps", no_future_timestamps)
    if "metrics" in loaded:
        run("exit_ratio_matches_mid", exit_ratio_matches_mid)
        run("paper_results_within_max_loss", paper_results_within_max_loss)
        run("paper_desk_imported", paper_desk_imported)
    if all(k in loaded for k in ("journal", "positions")):
        run("positions_match_journal", positions_match_journal)
    if all(k in loaded for k in ("metrics", "positions")):
        run("metrics_match_positions", metrics_match_positions)
    if "positions" in loaded:
        run("risk_within_cap", risk_within_cap)
        run("name_within_ceiling", name_within_ceiling)
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
