# Failover: one trader at a time (P012)

Brad, 2026-11-11: "You should be monitoring and doing the trades", "Yes p012 you need to
be able to open trades as well" and "Rule should be the ability to exit and enter trades.
No limits per day for trades."

Two sessions share this repo and branch `ccr-ada2dc9a-o9lbyl`:
- **head** (`session_018FLvMEhsok7fEKo5QjYahD`) trades every day.
- **standby** (`session_018FLvMFxVeykhFJeoFnFB57`) acts only when the head misses a
  check-in. It runs the head's own procedures, under the same rules and the same caps.

Only one of them places orders on a given day. The lease file decides which.

## The lease
`state/earnings/trader_lease.json`: `date` (US Pacific trading date), `holder` (`head` or
`standby`), `since` (UTC), `session`, `reason`, and `history` (the last 20 earlier leases).
A session places orders only while it holds today's lease.

| From (same date) | To | Allowed |
|---|---|---|
| no lease | head | yes |
| no lease | standby | yes, with a reason (the head never checked in) |
| head | standby | yes, a takeover, with a reason |
| same holder | same holder | yes, nothing changes |
| standby | head | no: the head stays out until the next trading date |

The one exception to the last row is an owner override: `--owner-override` with a reason
that quotes Brad. A lease for an earlier date never blocks today.

Commands (`PYTHONPATH=src python -m vantage_trader.earnings ...`):
- `lease show` prints who holds today and one plain instruction.
- `lease take --role head|standby --session ID [--reason TEXT]` takes it and writes the
  file. Exit 5 means the other role holds today. `lessons` and `selfcheck` show the lease too.

**The push is the lock.** Pull with rebase, take the lease, commit only the lease file,
push. A rejected push means the other session got there first. Undo your own lease commit
without touching anything else, then look again:

```
git reset --soft HEAD~1                                   # only when that commit is the lease file alone
git restore --staged --worktree state/earnings/trader_lease.json
git pull --rebase origin ccr-ada2dc9a-o9lbyl
PYTHONPATH=src python -m vantage_trader.earnings lease show
```

Never use `git reset --hard` here: it would throw away journal or position edits that are
not committed yet.

## The switches (dead-man's switches)
Each is a one-shot task that fires only when nobody moved it. Move one with
`update_trigger(trigger_id=..., run_once_at="<date>T<time>:00[America/Los_Angeles]", enabled=true)`
and no prompt argument.

| Switch | Task id | Fires | Runs in | Moved by | To |
|---|---|---|---|---|---|
| Standby exit | `trig_01NmMk2eNXRyukjX8pxGVcX3` | 07:25 PT | standby session | head, after the morning exits (or when none was due) | next trading day 07:25 PT |
| Plain alert | `trig_017icjQMENwSGysKQAuAHttx` | 08:00 PT | a fresh session, no broker | head with the exit switch; or the standby after its exit takeover | next trading day 08:00 PT |
| Standby entry | `trig_01E1KZZayvkKf2PJJYhRLY8M` | 12:05 PT | standby session | head, after the day's entry decision (trades placed or a no-trade recorded) | next entry day (Mon to Thu) 12:05 PT |

Order of the nets on a morning with an exit due: head 06:45 PT, head's hourly monitor
07:15 PT, standby exit switch 07:25 PT, plain alert to Brad's phone 08:00 PT. Brad is only
pinged when both sessions failed. The old alert-only broker check
(`trig_01Vog3pw1jWDJhBzW9Z1uV8w`, bound to the first standby session) is switched off.

The prompts of the two standby switches cannot be edited from the head session, so they
only point at this file. Change the procedure here.

## Head: at the start of every check-in
1. `git pull --rebase origin ccr-ada2dc9a-o9lbyl`.
2. `lease take --role head --session session_018FLvMEhsok7fEKo5QjYahD`. If it changed,
   commit only `state/earnings/trader_lease.json` and push.
3. Exit code 5: the standby holds today. Place no orders today. Tell Brad, read what the
   standby did, and stop. The reflection still does its read-only work.
4. After the morning exits (every earnings position due this morning is closed, or none
   was due), move the standby exit switch and the plain alert (table above). After the
   day's entry decision, move the standby entry switch. On a Friday the next trading day
   is Monday; skip NYSE holidays.

Every head instruction in `docs/earnings/prompts/` starts with these steps, and the stored
prompt of each scheduled task repeats them.

## Is the head working? (the test both takeovers use)
The head is working, and the standby stands down, when ANY of these is true:
1. The head session is active: `get_session session_018FLvMEhsok7fEKo5QjYahD` shows a turn
   running, or `list_events` on it shows an assistant or tool event in the last 5 minutes.
2. An option order was created in the account in the last 15 minutes.
3. The work this switch guards is already done (exits: every earnings position due this
   morning is closed; entry: trades placed today, or a no-trade decision recorded in the
   day's watchlist file).

If the standby stands down because of 1 or 2 while the work is NOT done yet, it moves its
own switch 15 minutes later (`update_trigger`, schedule only) and looks again then; at most
twice. On the third look test 1 no longer counts: a head that is busy but has placed no
option order for 15 minutes while the work is still not done is not doing this job. The
standby then takes the lease and does the work, and tells Brad with a push that the head was
alive but not acting. (The head re-checks the lease before its first order, so it stops.)
If the head session cannot be read, rely on 2 and 3.

The head, for its part, pulls and runs `lease show` again right before the FIRST order of
every run. If the standby holds today's lease by then, the head stops.

## Standby: exit takeover
Fires at 07:25 PT when the head did not move the exit switch.
1. `git pull --rebase origin ccr-ada2dc9a-o9lbyl`. Run `lease show`.
2. Read the broker: `get_option_positions`, `get_equity_positions` and today's
   `get_option_orders`. Read `state/earnings/positions.json` and today's commits.
3. Apply "Is the head working?" above. If it is working, say so in one line and stop (after
   moving this switch 15 minutes on when the exits are not done yet).
4. Take the lease: `lease take --role standby --session session_018FLvMFxVeykhFJeoFnFB57
   --reason "<evidence: last order time, positions still open>"`. Commit only the lease
   file and push. On a rejected push, follow "The push is the lock".
5. Follow `docs/earnings/prompts/exit_scan.md` part A as the head would (that file is the
   head's own instruction; skip its FAILOVER sentence, which is for the head): rules v1.1 to
   v1.5, the $1,000 cap, single-leg limit orders, buy the short legs back first. Journal
   every fill, append the exit records to `live_metrics.jsonl`, update `positions.json`,
   pause the breakeven alerts of closed positions.
6. Then run part B (the scan) and write the day's watchlist file, so the entry has it.
7. Move this switch to 07:25 PT and the plain alert to 08:00 PT on the next trading day
   (table above).
8. Run `selfcheck`, commit and push. Tell Brad (below).

## Standby: entry takeover
Fires at 12:05 PT when the head did not move the entry switch.
1. `git pull --rebase origin ccr-ada2dc9a-o9lbyl`. Run `lease show`.
2. Read the broker: open positions and today's `get_option_orders`. Read the repo: today's
   journal entries and commits.
3. Apply "Is the head working?" above. If it is working, say so in one line and stop (after
   moving this switch 15 minutes on when the entry decision is not made yet; never past
   12:35 PT).
4. Take the lease with a reason (skip this if the standby already holds today), commit
   only the lease file and push. On a rejected push, follow "The push is the lock".
5. Use `state/earnings/scan/<date>/watchlist.json` if the head wrote one. If not, run the
   scan in `docs/earnings/prompts/exit_scan.md` part B first, quickly.
6. Follow `docs/earnings/prompts/entry.md` as the head would (skip its FAILOVER sentence): rules v1.1 to v1.5, the
   $1,000 cap, iron flies only, single-leg limit orders, the net credit floor. Place
   nothing after 12:50 PT; cancel anything unfilled by then.
7. Journal, append the entry records, update `positions.json`, create the two breakeven
   alerts per position and record their ids, start a monitor daemon (`DAEMON.md`).
8. Move this switch to 12:05 PT on the next entry day (Mon to Thu). Run `selfcheck`, commit and
   push. Tell Brad (below).

The standby keeps the day. The head's hourly monitor fires into the head session, so on a
takeover day the standby schedules its own check-ins: `send_later` to itself every 60
minutes until 12:55 PT, each one following `docs/earnings/prompts/hourly_monitor.md` (skip
its FAILOVER sentence) for anything it opened or still holds, plus one read-only monitor
daemon per open position (`docs/earnings/DAEMON.md`, brief template). A head that comes back
the same day gets exit code 5 from `lease take` and stays out.

## What the standby tells Brad
In 10 lines or fewer, with a push notification:
- which switch fired, and the evidence that the head was not working;
- the time it took the lease;
- what it did: fills, legs, credits or closing costs, realized P/L, what is still open;
- the commit it pushed;
- that the head places no orders for the rest of the day.

## Head: the next morning
1. `git pull --rebase origin ccr-ada2dc9a-o9lbyl`.
2. Read what the standby did: `lease show` (the history holds yesterday's lease), the
   journal, `positions.json` and the standby's commits.
3. Run `selfcheck` and `reconcile` against a fresh broker snapshot. Fix any drift first.
4. Take the new day's lease (`lease take --role head`), commit and push.
5. Re-arm any switch that fired. Tell Brad what the standby did and why the head missed.

## Limits
- The standby cannot help when Brad's Claude usage limit is exhausted (no session runs)
  or when the Robinhood connector is down (no session can trade). The breakeven price
  alerts are the net for those cases.
- A lease is for one day. The head gets the next trading day back by taking it.
- Never two sessions placing orders. When in doubt, the standby does nothing and tells Brad.
