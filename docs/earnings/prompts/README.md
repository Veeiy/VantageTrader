# Scheduled task instructions

Since 2026-11-11 the instructions of the head's order-placing tasks live in this folder.
Each scheduled task stores only a short prompt that says: pull, take the lease, then follow
the file. One text, under version control, read by the head and by the standby
(`docs/earnings/FAILOVER.md`). To change a procedure, edit the text block and push.

| File | Task | Id | Schedule (PT) | Source of truth |
|---|---|---|---|---|
| `preopen.md` | Pre-open wake: lease and exit timer | `trig_01S3WvuyCCJtpJkXCkxen4qV` | 05:52 Mon-Fri | this file |
| `exit_scan.md` | Earnings daily: exit + scan | `trig_013Ktx56ZUVFeNtAVR475toV` | 06:45 Mon-Fri | this file |
| `midday_scan.md` | Earnings daily: midday scan | `trig_018qBZwkxCi6h76t2PQ2ddGZ` | 09:45 Mon-Thu | this file |
| `entry.md` | Earnings daily: ENTRY | `trig_01Qhfn5qNQaxKvQtse2nevgA` | 11:46 Mon-Thu | this file |
| `entry_backup.md` | Earnings daily: entry backup | `trig_019jPgVcNE935MqnfZedVRLm` | 12:17 Mon-Thu | this file |
| `hourly_monitor.md` | Positions: hourly monitor | `trig_012TXxzQAdCppBr1AWwNEksg` | minute 15, 07 to 12, Mon-Fri | this file |
| `daily_reflection.md` | Daily reflection | `trig_01D3GLpqio93gGPGemaPBKhR` | 13:12 Mon-Fri | this file (since 2026-11-16) |
| `standby_exit_switch.md` | Standby exit switch | `trig_01NmMk2eNXRyukjX8pxGVcX3` | 07:25, one-shot, moved daily | the task's stored prompt (copy) |
| `standby_entry_switch.md` | Standby entry switch | `trig_01E1KZZayvkKf2PJJYhRLY8M` | 12:05, one-shot, moved daily | the task's stored prompt (copy) |

The two standby switches are bound to the standby session, so their stored prompts cannot
be edited from the head session. They only point at `docs/earnings/FAILOVER.md`.
`head_failover_line.md` is the sentence every head instruction starts with.

The same-day pilot (rules v1.15) has no scheduled task of its own. Its entry is a timer the
morning run starts (`exit_scan.md`, part A2), its exit a timer the 10:15 hourly run starts
(`hourly_monitor.md`). The procedure is `docs/earnings/INTRADAY.md`.

The Saturday research day (`trig_01KLhgm9Zmpwv2gFcbHkeFAv`, one-shot, Sat 2026-11-21 09:00 PT,
re-armed for the next Saturday when it runs) places no orders. It works the research queue of
`docs/earnings/PLAN.md` section 9: the next test in line, a replay of the week's earnings
reports, the week's spread scans. Its instruction is the task's stored prompt.

`docs/earnings/PLAN.md` is the plan every one of these tasks works to: which lines are traded,
at what size, what is only tested, and what a line has to show before it grows.

`brief_staging_desk.md` (rules v1.16.1) is the brief for a Claude session on Brad's own computer
with the Chrome extension: it fills in a 4-leg ticket on robinhood.com in the account ending
3413 and stops; Brad reviews and submits. Not tested yet (2026-11-17).

The trading hub page (live P/L, every trade, what the model is learning) and how it is refreshed: `docs/earnings/HUB.md`.

Timers (P060, 2026-11-17). The harness stops an in-session background timer after two hours: a 12:28 PT timer started at 08:18 PT died at 10:18 PT. A timer is started from the last check-in within two hours of its event (the 05:52 wake for 06:36, the morning run for 07:27, the 10:15 run for 10:57, the 12:15 run for 12:57). An event further away is written into `positions.json` `pending` with its clock time; the hourly run starts its timer.

Usage (P063, 2026-11-17). No agent waits longer than 240 seconds in one piece: a subagent's
prompt cache lives 5 minutes and a call after it pays for the whole conversation again. The
reflection runs at 13:12 PT, inside the head's one-hour cache. `scripts/earnings/usage_scan.py`
prints the day's usage line and keeps one row a day in `state/earnings/usage.jsonl`.
