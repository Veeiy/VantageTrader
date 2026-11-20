# Summer replay, 2026-11-14: does the Thursday result hold in a second season?

Method and limits: `docs/earnings/REPLAY.md` (lite method: stock bars and the two body options,
model wings at 1x and 2x the straddle). Question: hypothesis H010, "the crush pays when the
expiry is the exit day". Paper only; no order was placed.

## Why this was run
Split by days to expiry at the exit, the fall replay (103 clean events, 2026-10-12 to 11-05)
puts most of its profit in Thursday entries, the ones closed on expiry Friday:

| Exit | Events | Straddle wins | Short straddle | 1x fly | 2x fly |
|---|---|---|---|---|---|
| On expiry day (Thursday entry) | 20 | 15 | +27.5% (se 10.0) | +$50 (se 18) | +$99 (se 35) |
| 1 day before expiry (Wednesday) | 39 | 23 | +6.7% (se 5.9) | +$6 | +$13 |
| 2 days before (Tuesday) | 25 | 16 | -0.5% (se 6.1) | -$4 | +$1 |
| 3 or 4 days before (Mon, Fri) | 19 | 13 | +11.0% | +$18 | +$37 |
| All other days together | 83 | 52 | +5.5% (se 3.6) | +$6 (se 11) | +$15 (se 24) |

It holds in both fall batches (batch 1: +22% against +2.5%; batch 2: +29% against +7%), which the
edge-ratio bands never did. But it is 4 Thursdays, and events on one day move together: at the
day level the gap is +$62 a 2x fly with t about 1.4.

## What was collected
The same 134 symbols that priced in the fall, one quarter earlier (reports 2026-07-13 to 08-28):
all 31 Thursday-entry events and a seeded random sample of 31 from other weekdays
(`events_picked.json`, seed 20261114). Five read-only agents, about 710k tokens.

## Data limit found (lesson L019)
For contracts that expired three or more months ago the broker's 30-minute option history has
real prints **only on the expiry day**. Every bar before that is a carried-forward value.
- All 31 control events (exit before expiry day) came back flat: no real exit price. Unusable.
- The 31 Thursday events have real exit prices (the exit day is the expiry day), but 30 of 31
  entry bars are carried-forward values and only 9 pass put-call parity at the entry.
- So old seasons can only be replayed for exits on expiry day, and entry prices are soft.
- One probe of a non-expiry-day bar before the bulk pull would have saved half the cost.

## Results (Thursday entries, summer)
| Set | Events | Straddle wins | Short straddle | 1x fly | 2x fly |
|---|---|---|---|---|---|
| Parity-clean entry prices | 9 | 7 | +20.1% (se 11.0) | +$20 (se 25) | +$59 (se 51) |
| All 31, soft entry prices | 31 | 20 | +8.3% (se 10.7) | +$13 (se 33) | +$11 (se 66) |
| Stocks $10 to $55, all | 15 | 11 | +11.5% | +$19 | +$28 |

By day (2x fly, mean of the day's events): 07-16 +$58 (2), 07-23 +$56 (3), 07-30 -$75 (9),
08-06 +$43 (15), 08-13 +$33 (1), 08-27 +$51 (1). Five of six Thursdays up.
The big losers were expensive names with wide flies (TEAM -$1,128, COIN -$774, RBLX -$495).

## Both seasons together
- Thursdays: 10 days, 8 up, mean +$48.50 a 2x fly per day (se 21, t 2.3).
- Parity-clean Thursday events: 29, 22 winners, +25% of the straddle, 1x fly +$40 (se 15),
  2x fly +$87 (se 28).
- Stocks the account can trade ($10 to $55): Thursdays 27 events, 21 winners, 1x fly +$41
  (se 18). Other days (fall only) 38 events, 21 winners, 1x fly +$8 (se 7).
- Other days could not be tested in the summer. The gap between Thursdays and other days is
  +$30 a 2x fly at the day level, t 1.2: not established.

## Reading
- Thursday entries are the one part of the strategy with a positive result in two seasons.
  The fall size of the effect (+$99) was partly luck: summer came in at +$11 to +$59.
- Non-Thursday entries average about +$8 a 1x fly before costs on tradable stocks. Legging
  alone cost $20 to $35 a fly in the live week, so after costs they are about break-even or worse.
- Not a rule yet: 10 Thursdays, soft summer entry prices, no summer controls. Proposal P038
  puts the choice to Brad. The live Thursday of 2026-11-12 (three skipped names, all up at the
  planned exit) is an 11th day in the same direction.
