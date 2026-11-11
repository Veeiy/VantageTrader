# Daily reflection loop

Brad, 2026-11-10: "Lets setup a self reflection learning loop after each trading day."

Every trading day after the close the head agent reviews the day, grades its own
decisions, and records what it learned with evidence. Lessons about HOW to carry out the
rules are applied the next day. Lessons about WHAT to trade or how much to risk are
tested as hypotheses and go to Brad as proposals. The loop never changes a rule itself.

## When
- Scheduled task "Daily reflection", 14:12 PT, Monday to Friday (after the close and the
  first after-hours earnings reactions). Skipped on NYSE holidays.
- The 06:45 and 11:46 check-ins read the lessons first:
  `PYTHONPATH=src python -m vantage_trader.earnings lessons`.

## Steps
1. **Facts.** `PYTHONPATH=src python -m vantage_trader.earnings daily-review --date <today>`
   (journal, fills, realized P/L, execution stats, open positions, lessons) and
   `live-metrics`. Add closing prices and after-hours moves for names that report tonight.
2. **Score what was not traded.** Rule-blocked and passing-but-untraded names from the
   previous session get priced from option history (same method as
   `state/earnings/replay/`): entry at the close before the report, exit the next
   morning. At most 6 names a day (about 16k tokens each) unless Brad asks for more.
   Write them as `paper` records in `live_metrics.jsonl`.
3. **Grade decisions on process.** One row per entry, exit, adjustment, skip and
   cancelled order: was the rule followed, was the information complete, was the size
   right, was the execution clean. Grade A to D on what was known at the time. Record the
   outcome in a separate column, and fill in outcomes for earlier days' decisions when
   they arrive. A good outcome does not raise a grade and a bad one does not lower it.
4. **Lessons** (`state/earnings/lessons.jsonl`, append-only):
   - For every lesson under `apply_now` and `being_tested`, add an `evidence` event when
     today speaks to it: `supports`, `contradicts` or `neutral`, with a reference.
   - New lessons: at most 2 a day. Each needs a statement and a test that could prove it
     wrong. Keep `apply_now` at 10 or fewer; retire the weakest first.
   - Retire a lesson that shows `weak` (4+ observations, more against than for).
5. **One change for tomorrow, at most,** and only of kind `execution`, `process` or
   `data`.
6. **Write** `state/earnings/reflections/<date>.md` (60 lines or fewer, template below),
   commit and push.
7. **Tell Brad** in 6 lines or fewer: the day's P/L, what worked, what did not, the one
   change, and anything waiting for his yes.

## Guardrails
- `execution`, `process` and `data` lessons may be applied at once. They never change
  which trades qualify or how much is at risk.
- `rule` and `risk` lessons start as hypotheses. One is `ready_to_propose` at 8 or more
  observations with at least twice as many for as against. It is then marked `proposed`
  and listed for Brad at the Friday scorecard. It becomes `adopted` only through a status
  event that carries `approved_by` and a matching entry in `RULES_CHANGELOG.md`. The code
  rejects a ledger that breaks this (`vantage_trader/earnings/reflect.py`).
- Hard limits are outside the loop: MCP account only, defined risk, limit orders, never
  TSLA, the $650 cap, the circuit breaker.
- The reflection places no orders and changes no scheduled task.
- Small samples: say how many observations a claim rests on. Threshold changes also need
  8 closed live trades (`calibrate`).

## Ledger events
```
{"event": "lesson",   "id": "L010", "kind": "execution|process|data|rule|risk",
 "statement": "...", "test": "what would prove it wrong", "status": "active|hypothesis", "ts": "..."}
{"event": "evidence", "id": "L010", "date": "YYYY-MM-DD", "verdict": "supports|contradicts|neutral",
 "ref": "trade_id or source", "note": "...", "ts": "..."}
{"event": "status",   "id": "H001", "status": "proposed|adopted|retired", "note": "...",
 "approved_by": "Brad, YYYY-MM-DD (required for adopted rule/risk lessons)", "ts": "..."}
```
Ids: `L###` for execution, process and data lessons; `H###` for rule and risk hypotheses.

## Reflection file template
```
# Reflection YYYY-MM-DD (Day)
## Facts                      (trades, realized P/L, fills, open risk, tool or process failures)
## Decisions graded on process  | Decision | Grade | Why | Outcome |
## What the data said         (scored names, replay, with observation counts)
## Lessons                    (evidence added, new lessons, retired lessons)
## One change for tomorrow
## Open for Brad              (proposals awaiting approval, decisions only he can make)
```

## Friday roll-up
The Friday scorecard adds: lessons applied this week and whether they held, hypotheses
with their tallies, anything `ready_to_propose` or `proposed`, and the week's grade
distribution (how many A/B/C/D decisions).
