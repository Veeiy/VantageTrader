"""Same-hours moves for the same-day pilot gate (rules v1.15, docs/earnings/INTRADAY.md).

The gate's premium ratio needs, for each of the last 10 sessions, the move from the entry time
(the bar that begins 07:30 Pacific) to that session's close. This keeps them in one small file.

    python3 scripts/earnings/intraday_moves.py seed
        build state/earnings/daytrade/same_hours_moves.json from the replay's stock bars
    python3 scripts/earnings/intraday_moves.py add --symbol IWM --date 2026-11-17 --open0730 273.41 --close 272.90
        add (or correct) one session: the open of the 07:30 Pacific bar and the session's last close
    python3 scripts/earnings/intraday_moves.py show --symbol IWM [--n 10] [--before 2026-11-18]
        print {"symbol", "dates", "same_hours_moves", "avg_abs", "last_date"} for the gate candidate

Prices come from get_equity_historicals (interval "30minute"): the bar that begins 14:30 UTC
(15:30 UTC from November to March) is 07:30 Pacific; the session's last bar begins 12:30 Pacific.
Nothing here places an order.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FILE = Path("state/earnings/daytrade/same_hours_moves.json")
BARS = Path("state/earnings/daytrade/replay/equity_30min.json")


def load() -> dict:
    return json.loads(FILE.read_text()) if FILE.exists() else {}


def save(data: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({s: dict(sorted(d.items())) for s, d in sorted(data.items())}, indent=0) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    a = sub.add_parser("add")
    a.add_argument("--symbol", required=True)
    a.add_argument("--date", required=True)
    a.add_argument("--open0730", type=float, required=True)
    a.add_argument("--close", type=float, required=True)
    s = sub.add_parser("show")
    s.add_argument("--symbol", required=True)
    s.add_argument("--n", type=int, default=10)
    s.add_argument("--before", default=None, help="only sessions before this date (YYYY-MM-DD)")
    args = ap.parse_args(argv)

    data = load()
    if args.cmd == "seed":
        bars = json.loads(BARS.read_text())
        for sym, days in bars.items():
            for day, b in days.items():
                if "07:30" in b and "12:30" in b:
                    data.setdefault(sym, {})[day] = {"o0730": round(b["07:30"]["o"], 4), "close": round(b["12:30"]["c"], 4)}
        save(data)
        print(json.dumps({s: len(d) for s, d in data.items()}))
        return 0
    sym = args.symbol.strip().upper()
    if args.cmd == "add":
        if args.open0730 <= 0 or args.close <= 0:
            print("prices must be > 0", file=sys.stderr)
            return 2
        move = args.close / args.open0730 - 1.0
        if abs(move) > 0.15:
            print(f"a same-hours move of {move:.1%} is not plausible: check the two prices", file=sys.stderr)
            return 2
        data.setdefault(sym, {})[args.date] = {"o0730": args.open0730, "close": args.close}
        save(data)
        print(json.dumps({"symbol": sym, "date": args.date, "move": round(move, 6)}))
        return 0
    days = sorted(d for d in data.get(sym, {}) if args.before is None or d < args.before)[-args.n:]
    moves = [round(data[sym][d]["close"] / data[sym][d]["o0730"] - 1.0, 6) for d in days]
    out = {"symbol": sym, "dates": days, "same_hours_moves": moves,
           "avg_abs": round(sum(abs(m) for m in moves) / len(moves), 6) if moves else None,
           "last_date": days[-1] if days else None}
    print(json.dumps(out))
    return 0 if len(moves) >= args.n else 1


if __name__ == "__main__":
    raise SystemExit(main())
