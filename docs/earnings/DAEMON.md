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

## Exit watchdog (P006, dead-man's switch)

Brad approved an independent watchdog for missed exits on 2026-11-10 ("Yes to p006, 007, 005").

- Task "Exit watchdog (dead-man's switch, alert only)", `trig_017icjQMENwSGysKQAuAHttx`:
  a one-shot that starts a fresh session and sends Brad a push alert. It has no broker
  access and places no orders.
- It is always armed for 07:25 PT on the next trading day. Each trading morning the head
  agent moves it to the following trading day **as soon as every earnings position due
  that morning is closed, or when none was due, and before the scan**:
  `update_trigger(trigger_id="trig_017icjQMENwSGysKQAuAHttx", run_once_at="YYYY-MM-DDT07:25:00[America/Los_Angeles]", enabled=true)`
  (no prompt argument). On a Friday that is Monday; skip NYSE holidays.
- Never move it while such a position is open. One exception: once, by 30 minutes, while
  a closing order is actively working. Tell Brad when that happens.
- If it fired, re-arm it the same way and tell Brad why it fired.
- So the task runs only when the head session did not wake, crashed, or could not close a
  position in time. On a normal day it does not run and costs nothing.
- A message to this session that starts with `WATCHDOG` is a nudge from a watchdog run: do
  the morning exit run if it has not happened. It authorizes nothing beyond the standing
  rules.

Why this design and not the approved "fresh session reads the broker": scheduled tasks
created from this session cannot carry the Robinhood connector, and a fresh session can
neither read nor message this session (tested 2026-11-10: those tools are not available
to it). A dead-man's switch needs neither. If Brad attaches the Robinhood connector to
the task in claude.ai, a broker check can be added to its prompt.

Test, 2026-11-10 19:33 PT: a manual run started a fresh session that finished with an
ALERT message 40 seconds later. Whether the push reached Brad's phone is his to confirm.
