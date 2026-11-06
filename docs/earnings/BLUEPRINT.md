# Mission: Earnings Vol Engine (Robinhood agentic account)

Run id: 2026-11-04-earnings-vol-engine
Execution autonomy: FULL. External authority: live trading, explicitly authorized by Brad
in-session on 2026-11-04 ("automate the trades"), limited to the Robinhood agentic account
nicknamed "MCP" (last 4: 3413) and the hard caps below. This narrows, it does not remove,
the orchestrator safety floor: no transfers, no deposits/withdrawals, no other accounts,
no credentials, no settings changes.

## Objective
Every trading day, find earnings events whose options misprice the earnings move,
pick ONE defined-risk structure, size it to the account, enter near the close before
the report, exit after the IV crush, log everything, and get better from outcomes.

## Definition of done (v1)
1. Pure-Python engine `vantage_trader.earnings` (no broker SDK): scoring, structure
   selection, sizing, entry/exit rules, journal, reconciliation, calibration, CLI.
2. Unit tests for every rule, all green with `python -m pytest -q`.
3. `docs/earnings/RUNBOOK.md`: step-by-step agent procedure per phase
   (SCAN, ENTRY, EXIT, RECONCILE, CALIBRATE) using Robinhood MCP tools, with failure
   handling ("self-healing") for every step.
4. `config/earnings.yaml` with all thresholds and hard caps.
5. Scheduled tasks wired (fresh session per fire) for weekday SCAN+EXIT (6:45 PT),
   ENTRY (12:00 PT), weekly CALIBRATE (Sat).
6. Auditor PASS on math, rule consistency, and hard-cap enforcement.

## Hard caps (code-enforced AND runbook-enforced)
- Account: agentic "MCP" account only. Re-read buying power + approval setting every run.
- Max ONE open earnings position at a time (v1).
- Max loss per trade <= min($700, 0.93 x buying power). Defined risk only
  (iron fly, iron condor, long straddle/strangle). No naked shorts, no undefined risk.
- Blocklist: TSLA (insider restriction), plus anything with stock price < $10 or
  ATM option bid/ask spread > 12% of mid.
- Circuit breaker: halt new entries if account value < $400, or 2 consecutive
  max-loss trades, or 3 losing trades in a row. Halt = log + notify Brad, exits still run.
- Limit orders only, priced at mid, walked toward natural in $0.05-0.10 steps,
  floor/ceiling from the engine. Cancel unfilled entries by 12:50 PT.
- Never hold a short leg into expiration day close: exit next session after report.

## Strategy core
edge_ratio = avg(|historical 1-day earnings move|, last N reports) / implied_move
implied_move = 0.85 x ATM straddle / spot   (straddle on first expiry after report)
- edge_ratio <= sell_max_ratio (0.85)  -> SELL premium: iron fly, wings sized by budget
- edge_ratio >= buy_min_ratio (1.25)   -> BUY premium: long ATM straddle
- otherwise skip. Rank by expected value, take top 1 that fits caps.
Historical move: AMC report = close(report day) -> close(next day);
BMO report = close(prior day) -> close(report day).
