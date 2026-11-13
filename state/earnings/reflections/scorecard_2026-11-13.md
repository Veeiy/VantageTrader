# Weekly scorecard, 2026-11-09 to 2026-11-13 (first live week)

## Result
| Trade | Kind | Contracts | Edge | Stock move / implied | P/L after fees |
|---|---|---|---|---|---|
| RGTI 9/12/15 | earnings | 1 (2, trimmed) | 0.78 | 0.39x | +$28.76 |
| RGTI trim | rebalance | 1 | | | -$10.32 |
| FLY 19/23.5/27 | earnings | 1 | 0.61 | 0.48x | +$44.72 |
| LUNR 12.5 body | earnings | 3 | 0.69 | 1.23x | -$26.88 |
| NVDA 170/175/180 | owner-directed, pre-earnings | 1 | | CEO resigned overnight | -$70.32 |
| PCG 12/13/14 | non-earnings, open | 5 | | stock on the body | open: +$28 conservative, +$68 at mid |

- Realized: -$34.04. Earnings flies alone: +$36.28. With PCG marked conservatively: about -$6.
- Account $1,275.91. Risk in use $224 of $1,000. Two losses in a row: a third pauses entries.
- Projection made 11/11 for the week: +$68 realized expected. Actual -$34. The gap is LUNR
  (+$15 expected, -$27) and NVDA (-$10 expected, -$70: a CEO resignation is outside any model).

## Names we skipped, scored on real prices at the planned exit
| Name | Blocked by | Result | Did the rule help? |
|---|---|---|---|
| NBIS | intraday +14%, edge 1.21 | -$407 | yes, the biggest save of the week |
| FPS | intraday +8.8%, spread 42% | -$19 | yes |
| CRWV | edge 0.96, news flags | -$51 | yes (news) |
| FIGR, XE | spread 38% and 60% | +$1, +$13 | no difference |
| PBR | edge 0.95 | +$9 | no, slightly |
| NU | edge 1.01 only | +$4 a contract | no difference |
| CSCO | edge 1.03, name cap, exit gate | +$180 | no on outcome |
| AMAT | edge 0.96, exit gate | +$296 at 06:45 PT, +$60 at 07:30 PT | edge gate no; exit gate yes (the 380 put cost $818 to $2,155 against $716 of room) |

- The after-hours estimate given to Brad on 11/12 (+$358, +$448, +$27 a contract) was about
  double the real result (+$296, +$180, +$4). All three were up, so his read was right.

## What the data says
- Edge gate (P019 selector test, 103 clean replay events): 0.85 or under won 25 of 37, mean
  +8% of the straddle; 0.85 to 1.10 won 22 of 26, +20%; above 1.10 won 24 of 38, +14%. The
  0.85 line throttles, it does not select. Price band, implied move and report timing do not
  hold across both replay batches either. The premium itself is real: short straddles won
  71 of 101, +13% (4 standard errors); the fly keeps +$9 to +$18 of it after costs.
- Exit time: the three skipped flies were worth +$500 at 06:45 PT and +$102 at 07:30 PT.
  Replay: 10:00 ET beats 10:30 ET by $2 to $16 a fly. Exit at the first liquid quotes.
- Intraday gate (P024): the 5% to 7% band did worst in replay (5 of 9, -$17 to -$24 a fly).
- Execution: entries filled at 96.7% of mid, exits at 97.9%. Legging cost $55 of Thursday's
  $97 loss. Multi-leg orders: refused again today (review clean, placement refused).
- Paper desk (same-day flies): 2 sessions, 6 flies, 4 wins, +$219 at mid. Day 3 is running.
- Calibration: needs 8 closed trades to move a threshold, has 4.

## Decisions (agent, under Brad's delegation of 11/11)
| | Decision | Why |
|---|---|---|
| v1.10 / P032 | Names with edge 0.85 to 1.10 trade at half size from Monday | selector test above; "tier off" reverses it |
| P031 | Pre-open wake 05:52 PT and an in-session timer at 06:36 PT | the 06:45 task fired 52 minutes late today |
| P024 | Intraday gate stays | its own band did worst; NBIS and FPS both lost |
| P019 | Stays open to 11/25, now with the tier feeding it live data | |

## Ledger
- Hypotheses: H001 +11/-7 (declined above), H008 +11/-6, H004 +4/-1, H006 +2/-2, H003 +1/-1,
  H007 +0/-1. Lessons in force: 10.
- Grades this week (31 decisions): A 3, A- 6, B+ 3, B 5, B- 4, C+ 3, C 6, D 1.
- Proposals: 6 verified as worked, 4 inconclusive, 19 implemented and waiting for their measure.

## For Brad
1. The repo is public. Make it private when you have a minute.
2. Robinhood: ask support when agents can place multi-leg option orders. That one change
   removes the legging cost and opens names like AMAT and CSCO.
3. NVDA 11/17 earnings trade is on hold since the CEO resigned. "NVDA on" re-enables it.
4. P017 (live same-day flies) comes to you after 10 paper sessions (3 done by today's close).
