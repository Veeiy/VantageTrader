# Position-monitor daemons (v1.2)

Brad, 2026-11-10: "If a trade opens we need daemon agents live monitoring."

## What a daemon is
- One read-only background agent per open position, started by the head agent.
- It polls about every 3 minutes during market hours and reports to the head with
  `SendMessage(to: "main")` when a trigger fires. It keeps running after a report.
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
`python3 -c "import time; time.sleep(170)"` with a 300000 ms timeout.
Every cycle: get_equity_quotes([{SYMBOL}]).
Every 5th cycle, or at once if the stock moved {FAST_MOVE} since the last leg check:
  get_option_quotes for the legs; close_cost = short mids - long mids.
Every 10th cycle: WebSearch for news on the driver.
Every 5th cycle: get_option_positions (nonzero) and get_equity_positions.

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
