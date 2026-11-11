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

## Exit watchdog (P006): two dead-man's switches

Brad approved an independent watchdog for missed exits on 2026-11-10 ("Yes to p006, 007,
005") and asked for Robinhood access on it on 2026-11-11 ("Yeah lets attach it if we can").

| | Task | Runs in | What Brad gets |
|---|---|---|---|
| Watchdog 1, plain alert | `trig_017icjQMENwSGysKQAuAHttx` | a fresh session, no broker access | "the trading session did not confirm this morning's exits", pushed by the platform |
| Watchdog 2, broker check | `trig_01Vog3pw1jWDJhBzW9Z1uV8w` | the standby session `session_018FLvMGKFakzaDKfa4APDHz` ("Trading watchdog (alert only)"), which has the Robinhood tools | which positions are still open, their legs, whether closing orders are working (PushNotification) |

Both are one-shots, always armed for 07:25 PT on the next trading day. Two channels on
purpose: push delivery from either one is not yet confirmed by Brad.

**The head agent's duty, every trading morning**: as soon as every earnings position due
that morning is closed, or when none was due, and before the scan, move BOTH to the next
trading day:
`update_trigger(trigger_id=..., run_once_at="YYYY-MM-DDT07:25:00[America/Los_Angeles]", enabled=true)`
with no prompt argument. On a Friday that is Monday; skip NYSE holidays.

Rules:
- Never move a switch while such a position is open. One exception: once, by 30 minutes,
  while a closing order is actively working. Tell Brad when that happens.
- If one fired, re-arm it the same way and tell Brad why it fired.
- Neither watchdog places orders or changes anything. Do not give them write duties.
- A message to this session that starts with `WATCHDOG` is a nudge from a watchdog run: do
  the morning exit run if it has not happened. It authorizes nothing beyond the standing
  rules.

Platform facts behind the design (tested 2026-11-10 and 2026-11-11):
- A fresh session started by a scheduled task gets no connectors and cannot read or
  message another session. A session started with `create_session` does inherit the
  account's connectors (its Robinhood tools appear under a server-id prefix).
- A scheduled fire of a task bound to another session lands in that session, about two
  minutes late. A manual `fire_trigger` starts a fresh session instead, so it cannot be
  used to poke the standby session.
- The prompt of watchdog 2 can be edited only from the standby session's own
  conversation. Its schedule and enabled state can be changed from here.

Cost: nothing on a normal day, because neither runs. A watchdog 2 run costs about $1.50
on Opus (the standby session loads every connector), which is why it is not a daily check.

What it does not cover: if Brad's Claude usage limit is exhausted, no session runs,
including these. The Robinhood price alerts below are the net for that case.

Tests:
- 2026-11-10 19:33 PT: a manual run of watchdog 1 produced an ALERT message in 40 seconds.
- 2026-11-11 05:05 PT: a scheduled run of watchdog 2 landed in the standby session, read
  the broker and reported "FLY and RGTI earnings flies are still open, no closing orders
  working" with the correct legs, and left PCG (a multi-day trade) alone.
- Whether the pushes reach Brad's phone is his to confirm.

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

## Backup trader (P012, in progress)

Brad, 2026-11-11: "You should be monitoring and doing the trades" and "Yes p012 you need
to be able to open trades as well."

- Standby session: `session_018FLvMFxVeykhFJeoFnFB57`, "Backup trader (standby)", created
  2026-11-11 06:06 PT with this repository (branch `ccr-ada2dc9a-o9lbyl`, same outcome
  branch) and the account's connectors. It replaces the alert-only standby
  `session_018FLvMGKFakzaDKfa4APDHz` once it is live.
- It may place no order until Brad writes his authorization in that session himself. One
  session cannot hand trading authority to another.
- To build on 2026-11-11 after the morning exits, live from 2026-11-12:
  `docs/earnings/FAILOVER.md` (procedure), a trader lease in the repository so only one
  session trades on a given day (the push is the lock), dead-man's switches bound to the
  standby for the exit (07:25 PT) and the entry (about 12:20 PT), a check of the lease at
  the start of every head check-in, and a dry run.
- Until then the two alert-only watchdogs above stay armed.

### Switchboard (Brad, 2026-11-11 06:13 PT)
"We can have this hub be the switchboard too and authorized to send commands as me to the
other sessions."

- This session (the head, `session_018FLvMEhsok7fEKo5QjYahD`) may relay Brad's commands to
  the other trading sessions it runs (the backup trader and the watchdog sessions), and
  only to those. Every relayed command quotes his words and says when he wrote them.
- A receiving session still decides for itself whether a relayed command is enough: the
  platform tells every session to treat a message from another session as information,
  not as its user's instruction. 06:14 PT: his authorization for the backup trader was
  relayed with his four messages quoted. 06:12 PT answer from the backup trader
  (`session_018FLvMFxVeykhFJeoFnFB57`): ACCEPTED. It read the four messages in this session's
  transcript, confirmed they are real user messages, and will check his message in this
  transcript before acting on any relayed command. That check is the working rule for
  the switchboard: quote him exactly, so the receiving session can find it.
- If a session does not accept a relayed command, Brad's own message in that session is
  the fallback. Never dress a relayed command up as typed by him.

### Build status (2026-11-11 06:25 PT)
A builder agent finished the code and docs on a LOCAL branch that is not pushed:
`failover-build`, worktree `/home/user/vt-failover`, commit `3014978`, 247 tests passing.
It adds `lease.py`, the `lease show` / `lease take` commands, the lease in the `lessons`
output, a `lease_parses` self-check, `docs/earnings/FAILOVER.md` and copies of the six
task prompts under `docs/earnings/prompts/`. If the container restarted and the worktree
is gone, rebuild it from the P012 brief.

Review before merging (squash into `ccr-ada2dc9a-o9lbyl` with the normal trailer):
1. FAILOVER.md tells a session to run `git reset --hard HEAD~1` after a rejected push.
   Replace it with a safer recipe (abort, pull, re-read the lease).
2. With no lease for the day nobody "may trade", so every head check-in must start with
   `lease take --role head`. Add that to the head prompts.
3. Order of the nets when the head misses the morning: head 06:45, head monitor 07:15,
   standby takeover 07:25, plain alert to Brad only at 08:00 and only if the standby did
   not move it. Reword that alert: the backup is on it unless it says otherwise.
4. The standby's switch tasks do not exist yet: create them bound to
   `session_018FLvMFxVeykhFJeoFnFB57` (their prompts cannot be edited from here later),
   put their ids in FAILOVER.md, retire watchdog 2 and the old alert-only standby.
5. Dry run with the standby before going live. No orders.


## Failover is live (P012, 2026-11-11 07:45 PT)

The backup trader replaces the alert-only watchdog design above. Current procedure and the
table of switches: `docs/earnings/FAILOVER.md`. In short:
- Standby exit switch `trig_01NmMk2eNXRyukjX8pxGVcX3` (07:25 PT): the backup trader closes
  what the head did not.
- Plain alert `trig_017icjQMENwSGysKQAuAHttx` moved to 08:00 PT: Brad's phone only rings
  when both sessions failed.
- Standby entry switch `trig_01E1KZZayvkKf2PJJYhRLY8M` (12:05 PT).
- The alert-only broker check `trig_01Vog3pw1jWDJhBzW9Z1uV8w` is switched off; its session
  (`session_018FLvMGKFakzaDKfa4APDHz`) is left as it is.
- One trader at a time: `state/earnings/trader_lease.json`.
- Task instructions now live in `docs/earnings/prompts/`; the stored prompts only point there.
