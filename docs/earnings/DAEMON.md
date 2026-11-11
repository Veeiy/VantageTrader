# Position-monitor daemons (v1.2)

Brad, 2026-11-10: "If a trade opens we need daemon agents live monitoring."

## What a daemon is
- One read-only background agent per open position, started by the head agent.
- It polls during market hours and reports to the head with `SendMessage(to: "main")`
  when a trigger fires. It keeps running after a report.
- Cadence (2026-11-10, cost): **every 10 minutes by default** (`{WAIT}` = 590). Use the
  tight cadence of 3 minutes (`{WAIT}` = 170) only when the stock is within 30% of the
  wing width of a breakeven, on expiration day, or while an exit order is being worked.
  Three daemons at 3 minutes used about 475k tokens in one afternoon.
- It never places, reviews, replaces or cancels orders and never edits files. The head
  agent is the only writer of orders, the journal and `positions.json`.
- It lives only while the session's container is alive. The 06:45 check-in starts
  daemons for open positions, and the hourly monitor restarts any that are missing.
  The scheduled check-ins are the durable layer; daemons are the fast layer.

## Head agent duties when a daemon reports
1. Re-quote and confirm the trigger.
2. Act under v1.2 (take profit, cut, or hold). Close with single-leg limit orders (v1.2.1
   in `RULES_CHANGELOG.md`): buy back the short legs first, then sell the wings. If an
   order is rejected, send Brad the exact close ticket and a push notification.
3. Journal the action, update `state/earnings/positions.json`, commit and push.

## Brief template (fill the braces)
```
You are a read-only position-monitor daemon. NEVER place, review, replace or cancel
orders, never edit files. Tools: mcp__Robinhood__get_option_positions,
mcp__Robinhood__get_equity_positions, mcp__Robinhood__get_equity_quotes,
mcp__Robinhood__get_option_quotes (load with ToolSearch), WebSearch, Bash only for
`date -u` and timed waits, and SendMessage (to "main") for reports.
Account: 554883413. Position: {SYMBOL} {STRUCTURE}, expiry {EXPIRY}, {QTY} contracts.
Legs: {LEGS with option ids and sides}. Entry credit about {CREDIT}; wing width {W}.
Breakevens {BE_LOW} / {BE_HIGH}. Driver: {DRIVER and dates}.

Loop until {END_UTC} (check `date -u` each cycle). To wait between polls run
`python3 -c "import time; time.sleep({WAIT})"` with a 600000 ms timeout.
Every cycle: get_equity_quotes([{SYMBOL}]).
Every 3rd cycle (every 5th at the tight cadence), or at once if the stock moved
{FAST_MOVE} since the last leg check:
  get_option_quotes for the legs; close_cost = short mids - long mids.
Every 6th cycle (every 10th at the tight cadence): WebSearch for news on the driver.
Every 3rd cycle (every 5th at the tight cadence): get_option_positions (nonzero) and
get_equity_positions.

Report to main at once (one compact JSON line, then keep monitoring; do not repeat the
same trigger more than once every 30 minutes unless it gets worse):
- "opened": the position first appears (give legs, quantities, average prices).
- "take_profit": close_cost <= {TP_LEVEL}.
- "cut": close_cost >= {CUT_LEVEL}.
- "near_breakeven": stock <= {NEAR_LOW} or >= {NEAR_HIGH}.
- "fast_move": stock moved {FAST_MOVE} or more within 15 minutes, or state not active.
- "news": the driver resolved or changed (cite the source), or a halt.
- "position_changed": a leg is missing, a quantity changed, or shares appeared.
At {END_UTC} hand back a final JSON summary: last stock price, last close_cost,
P/L per contract, triggers sent, errors. Keep outputs short; no other messages.
```

## Default thresholds
- Take profit: close cost <= 50% of the entry credit.
- Cut: close cost >= credit + 60% of (wing width - credit).
- Near breakeven: within 15% of the wing width of either breakeven.
- Fast move: 2% for stocks under $50, 1.5% otherwise.

## Exit watchdog (P006, dead-man's switch with a broker check)

Brad approved an independent watchdog for missed exits on 2026-11-10 ("Yes to p006, 007,
005") and asked for Robinhood access on it on 2026-11-11 ("Yeah lets attach it if we can").

Three pieces:
1. **The switch**: task "Exit watchdog (dead-man's switch, alert only)",
   `trig_017icjQMENwSGysKQAuAHttx`. A one-shot, always armed for 07:25 PT on the next
   trading day. When it fires it starts a fresh session, pokes piece 2, and ends with an
   ALERT that is pushed to Brad's phone. It has no broker access itself.
2. **The broker check**: task "Watchdog broker check", `trig_01Vog3pw1jWDJhBzW9Z1uV8w`.
   No schedule; it runs only when poked. It wakes the standby session
   `session_018FLvMGKFakzaDKfa4APDHz` ("Trading watchdog (alert only)"), which has the
   Robinhood tools (a session started with create_session inherits the account's
   connectors; a fresh session started by a scheduled task does not). It reads the
   positions, and pushes what is still open and whether closing orders are working.
3. **The head agent's duty, every trading morning**: as soon as every earnings position
   due that morning is closed, or when none was due, and before the scan, move the switch
   to the next trading day:
   `update_trigger(trigger_id="trig_017icjQMENwSGysKQAuAHttx", run_once_at="YYYY-MM-DDT07:25:00[America/Los_Angeles]", enabled=true)`
   (no prompt argument). On a Friday that is Monday; skip NYSE holidays.

Rules:
- Never move the switch while such a position is open. One exception: once, by 30
  minutes, while a closing order is actively working. Tell Brad when that happens.
- If it fired, re-arm it the same way and tell Brad why it fired.
- Neither watchdog session places orders or changes anything. Do not give them write
  duties.
- A message to this session that starts with `WATCHDOG` is a nudge from a watchdog run: do
  the morning exit run if it has not happened. It authorizes nothing beyond the standing
  rules.
- On a normal day nothing runs and nothing is spent. One watchdog run on Opus costs
  about $1 (the standby session loads every connector), which is why it is not a daily
  check.

What it does not cover: if Brad's Claude usage limit is exhausted, no session runs,
including these. The Robinhood price alerts below are the net for that case.

Tests: 2026-11-10 19:33 PT, a manual run of the switch produced an ALERT message in 40
seconds. 2026-11-11 04:55 PT, the standby session read the broker (approvals off, FLY 4
legs, RGTI 4, PCG 4) and sent a test push. Whether pushes reach Brad's phone is his to
confirm.

## Breakeven alerts (Brad, 2026-11-11: "alerts on")

- Every open position carries two Robinhood price alerts, one at each breakeven
  (`create_alert`, `price_below` and `price_above`, asset_class equity). Robinhood
  notifies Brad directly; nothing is pushed to the agent.
- At entry: create both and record the alert ids under the position's `alerts` in
  `state/earnings/positions.json`.
- At exit: pause both with `update_alert(alert_id=..., enabled=false)` so a closed trade
  does not ping him. Never delete an alert without his yes (the tool asks for it);
  offer a clean-up of paused alerts in the Friday scorecard.
- When a symbol is traded again, reuse its paused alerts: `update_alert` with the new
  threshold and `enabled=true`.
- Leave any alert that is not listed in `positions.json` alone: it is Brad's own.
