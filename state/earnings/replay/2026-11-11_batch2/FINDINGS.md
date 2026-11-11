# Replay batch 2 (2026-11-11) and the combined sample (P009)

Method and limits: `docs/earnings/REPLAY.md` (lite method: stock bars and the two body
options, wings from the model at exactly 1x and 2x the entry straddle). One contract per
event. "Clean" = at-the-money prints pass put-call parity. Costs = 7% of the entry credit.
Exits: `b1` = 10:00 ET, `b2` = 10:30 ET on the day after the entry. Our live exit is about
09:46 ET, closest to `b1`.

## Sample
| | Batch 1 | Batch 2 | Combined |
|---|---|---|---|
| Events drawn | 108 | 276 | 384 |
| No options for that Friday | 72 | 176 | 248 |
| Priced | 36 | 98 | 134 |
| Clean | 32 | 71 | 103 |

Batch 2 is every second event of the 552 liquid-option earnings events of 10/12 to 11/06
that batch 1 did not draw. 27 of its priced events exit on the expiry day itself.

## 1. The premium is real, the narrow fly gives it back (combined, 103 clean)
| Structure | Exit | Wins | Before costs | After costs |
|---|---|---|---|---|
| Short straddle (no wings) | 10:30 | 67 of 103 | +$39 a trade | not costed |
| Fly, wings 1x the straddle | 10:00 | 72 of 101 | +$21 a fly | -$1 |
| Fly, wings 1x | 10:30 | 61 of 103 | +$14 | -$9 |
| Fly, wings 1.5x | 10:00 | 72 of 101 | +$36 | +$9 |
| Fly, wings 2x | 10:00 | 69 of 100 | +$47 | +$17 |
| Fly, wings 2x | 10:30 | 64 of 102 | +$31 | +$1 |

The median move was 0.64 of the implied move. Average max loss: $140 (1x), $294 (1.5x),
$486 (2x). Standard errors of the after-cost averages at 10:00: $7.5 (1x), $11.9 (1.5x),
$14.6 (2x): none is more than about one standard error from zero. With the $350 per-trade
cap: 1.5x wings, 69 events, +$10.5 a fly after costs (5.7% of max loss).

## 2. The edge ratio does not pick winners
| Edge ratio (narrow fly, 10:30 exit) | Batch 2 | Combined |
|---|---|---|
| 0.70 or under | 9 of 17, -$144 | 15 of 25, +$113 |
| 0.70 to 0.85 | 8 of 9, +$420 | 8 of 12, +$235 |
| 0.85 to 1.00 | 13 of 14, +$968 | 16 of 20, +$871 |
| 1.00 to 1.25 | 7 of 11, -$312 | 10 of 18, -$251 |
| 1.25 or more | 8 of 20, +$344 | 12 of 28, +$500 |

- Names passing every replayable gate (edge 0.85 or under): 17 of 25, +$12 a fly. The other
  78: 44 wins, +$15 a fly. Fisher one-sided p = 0.22.
- Passing with edge 0.70 or under: 11 of 15, +$16 a fly; the other 88: 50 wins, +$14.
  p = 0.18. Batch 1's 6 of 6 did not repeat (batch 2: 5 of 9, -$61).
- Rank correlation of the edge ratio with move/implied: 0.00.

## 3. Long straddles
Edge 1.25 or more, combined: the long straddle won 11 of 27, -$1,530 before costs. Off stays
right (P010).

## 4. Gates (small counts, batch 2 unless noted)
- Intraday gate: 6 of the 7 names it blocked won. H001 is now 11 to 5 for dropping it.
- Regime guard: tripped 3 times, 0 wins, -$116. The only gate with the right sign.
- Macro veto: 2 of 3 blocked names lost; combined veto days 7 of 10 wins. No information.
- No-edge gate: names above 0.85 won 28 of 44 in batch 2. H005 is now 32 to 36: not supported.

## 5. Exit time
Combined, narrow fly: 10:00 ET beats 10:30 ET by $6 a fly, wide fly by $16. The stock was
further from the close at 10:30 than at the open in 71 of 103 events (4.6% at the open,
5.5% at 10:00, 5.9% at 10:30). Exit at the first liquid quotes.

## What this changes
- Proposed to Brad: P018 (wings about 1.5x the straddle, max loss $350 or less per trade),
  P019 (keep the 0.85 gate as a throttle for now, or drop it).
- Done by the agent: P020, the 0.70 early-entry layer is dropped.
- H008 reads "ready" in the ledger (11 to 5) but is NOT proposed: the names outside it do as
  well, so it is not a selector.
- Next: test other selectors (price band, implied move level, report timing) on the full
  set at the Friday scorecard; the $25 to $50 band won 16 of 19 (found after the fact).

## Cost
About 2.76M tokens: 12 pricing agents 2.44M, 2 history agents 0.31M. 27.6k per priced event
(batch 1: 55k). The quote was 1.5M to 1.8M.
