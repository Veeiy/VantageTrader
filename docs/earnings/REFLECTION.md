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
   previous session get priced from option history with the lite method in `REPLAY.md`:
   collect the stock bars and the two body options only (three small calls a name), write
   raw records and an events file (with the scan's `avg_hist_move`, `n_hist`,
   `prior_close`, `regime20`) under `state/earnings/scan/<date>/`, and run
   `python -m vantage_trader.earnings replay`. Entry at the close before the report, exit
   60 minutes after the next open, wings at 1x and 2x the straddle priced by the model.
   At most 6 names a day unless Brad asks for more. Write them as `paper` records in
   `live_metrics.jsonl`. Results with a failed put-call parity check are not evidence.
   Paper day trades (`live_metrics.jsonl`, record `paper`, kind `intraday_0dte`): score each
   from 5-minute bars of its four legs (`get_option_historicals`, through a read-only agent,
   never in the head session): the first touch of its take-profit or stop, else its time
   stop, and the 12:45 PT mark as the hold-to-the-end case. Write `pnl_mid_usd` on a new
   `paper` record with the same `trade_id` and add the day to the tally in
   `state/earnings/daytrade/` (P017 is decided on 10 sessions).
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
5. **Health.** Run `selfcheck`. List the scheduled tasks and check each one's last run,
   that it is enabled, and that the day's expected outputs exist (watchlist, entry
   decision, journaled exits). Anything missed or failed becomes a `heal` proposal today.
6. **Proposals** (`state/earnings/proposals.jsonl`, see "Daily proposals" below): fixes
   the agent can make are made and logged; anything touching rules, risk or cost goes to
   Brad, at most 3 a day, ranked.
7. **Write** `state/earnings/reflections/<date>.md` (60 lines or fewer, template below),
   run `selfcheck`, commit and push.
8. **Tell Brad** in 10 lines or fewer: the day's P/L, what worked, what did not, what was
   fixed, and the numbered proposals that need his yes or no.

## Guardrails
- `execution`, `process` and `data` lessons may be applied at once. They never change
  which trades qualify or how much is at risk.
- `rule` and `risk` lessons start as hypotheses. One is `ready_to_propose` at 8 or more
  observations with at least twice as many for as against. It is then marked `proposed`
  and listed for Brad at the Friday scorecard. It becomes `adopted` only through a status
  event that carries `approved_by` and a matching entry in `RULES_CHANGELOG.md`. The code
  rejects a ledger that breaks this (`vantage_trader/earnings/reflect.py`).
- Hard limits are outside the loop: MCP account only, defined risk, limit orders, never
  TSLA, the total risk cap ($1,000 since 2026-11-11), the circuit breaker.
- The reflection places no orders and changes no scheduled task.
- Small samples: say how many observations a claim rests on. Threshold changes also need
  8 closed live trades (`calibrate`).

## Daily proposals (heal and strengthen)

Brad, 2026-11-10: "Propose changes and iterations daily for us to heal and strengthen the
trading loop."

- **heal** fixes something that broke or could break: a missed run, a ledger error, a
  broker limitation, a single point of failure. **strengthen** makes decisions or
  execution better.
- Every proposal states the problem with evidence, the change, and a measure that will
  show whether it worked. Proposals without a measure are not logged.
- Who decides:
  - `execution`, `process`, `data`, `tooling`: the agent approves, implements and reports.
  - `rule`, `risk`, `cost`: since 2026-11-11 08:13 PT the agent, under Brad's standing
    delegation ("you have owners permission to automate"; scope and limits in
    RULES_CHANGELOG.md, "Delegation"). The decision event names the delegation and quotes
    him. What the delegation does not cover (the hard limits, a max loss per name above
    $350, a new live strategy line) still needs his own words: flag such a proposal with
    `"needs_owner": true`. Sizing above 1 contract was on this list until he lifted it the
    same day (RULES_CHANGELOG v1.7). In the
    ledger a delegated decision reads `"by": "agent, under Brad's standing delegation of
    2026-11-11: ..."` and carries a `ts`; the code accepts that form only, only from the
    delegation's date on, and never for a flagged proposal.
- Every decision taken under the delegation is listed in that day's message to Brad under
  "Changed today", with the numbers behind it. He reverses any of them with one word.
- Every implemented proposal is checked against its measure and marked `worked`,
  `did_not_work` or `inconclusive`. A change that did not work is rolled back or replaced.
- `PYTHONPATH=src python -m vantage_trader.earnings proposals` shows what is waiting on
  whom.

```
{"event": "proposal", "id": "P008", "date": "YYYY-MM-DD", "type": "heal|strengthen",
 "kind": "execution|process|data|tooling|rule|risk|cost", "decider": "agent|owner",
 "title": "...", "problem": "...", "change": "...", "measure": "...", "ts": "..."}
{"event": "decision",    "id": "P008", "decision": "approved|declined|deferred", "by": "agent | Brad, date, his words", "ts": "..."}
{"event": "implemented", "id": "P008", "ref": "commit, file or task id", "ts": "..."}
{"event": "verified",    "id": "P008", "result": "worked|did_not_work|inconclusive", "note": "...", "ts": "..."}
```

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
## Health                     (selfcheck, scheduled tasks, anything missed)
## Proposals                  (fixed today; awaiting Brad, numbered; verified or rolled back)
```

## Friday roll-up
The Friday scorecard adds: lessons applied this week and whether they held, hypotheses
with their tallies, anything `ready_to_propose` or `proposed`, and the week's grade
distribution (how many A/B/C/D decisions).
