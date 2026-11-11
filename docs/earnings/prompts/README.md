# Scheduled task instructions

Since 2026-11-11 the instructions of the head's order-placing tasks live in this folder.
Each scheduled task stores only a short prompt that says: pull, take the lease, then follow
the file. One text, under version control, read by the head and by the standby
(`docs/earnings/FAILOVER.md`). To change a procedure, edit the text block and push.

| File | Task | Id | Schedule (PT) | Source of truth |
|---|---|---|---|---|
| `exit_scan.md` | Earnings daily: exit + scan | `trig_013Ktx56ZUVFeNtAVR475toV` | 06:45 Mon-Fri | this file |
| `midday_scan.md` | Earnings daily: midday scan | `trig_018qBZwkxCi6h76t2PQ2ddGZ` | 09:45 Mon-Thu | this file |
| `entry.md` | Earnings daily: ENTRY | `trig_01Qhfn5qNQaxKvQtse2nevgA` | 11:46 Mon-Thu | this file |
| `entry_backup.md` | Earnings daily: entry backup | `trig_019jPgVcNE935MqnfZedVRLm` | 12:17 Mon-Thu | this file |
| `hourly_monitor.md` | Positions: hourly monitor | `trig_012TXxzQAdCppBr1AWwNEksg` | minute 15, 07 to 12, Mon-Fri | this file |
| `daily_reflection.md` | Daily reflection | `trig_01D3GLpqio93gGPGemaPBKhR` | 14:12 Mon-Fri | the task's stored prompt (this is a copy from 2026-11-11 06:20 PT) |
| `standby_exit_switch.md` | Standby exit switch | `trig_01NmMk2eNXRyukjX8pxGVcX3` | 07:25, one-shot, moved daily | the task's stored prompt (copy) |
| `standby_entry_switch.md` | Standby entry switch | `trig_01E1KZZayvkKf2PJJYhRLY8M` | 12:20, one-shot, moved daily | the task's stored prompt (copy) |

The two standby switches are bound to the standby session, so their stored prompts cannot
be edited from the head session. They only point at `docs/earnings/FAILOVER.md`.
`head_failover_line.md` is the sentence every head instruction starts with.
