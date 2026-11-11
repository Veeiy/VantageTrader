# Replay 2026-11-10: an unbiased sample of four weeks of earnings (P007)

Method and limits: `docs/earnings/REPLAY.md`. Numbers come from `summary.json`
(`replay-summary`), one contract per event, exit 60 minutes after the next open, real
at-the-money prices, model wings. "Clean" = the at-the-money prints pass put-call parity.

## Sample
| | Events |
|---|---|
| Earnings events 10/12 to 11/06 in stocks with liquid options ($10 to $150) | 660 |
| Drawn systematically (every 6th) | 108 |
| No weekly expiry at Robinhood, monthlies only (not tradable under the 7-day rule) | 72 |
| Priced | 36 |
| Clean | 32 |

Flagged and left out of the clean numbers: AR, GFL, SHEL, PFE.

## 1. Selling every fly has a small edge that costs wipe out
| 32 clean events | Wins | Before costs | After costs (7% of credit, about $20 a fly) |
|---|---|---|---|
| Fly, wings about 1x the straddle | 16 | +$191 (+$6 a fly) | -$457 |
| Fly, wings about 2x the straddle (31) | 17 | +$823 | about $0 |
| Short straddle, no wings | 19 | +$1,321 | not costed |

The move came in at a median 0.78 of the implied move. The strategy only pays if the
filter picks the right names.

## 2. The edge ratio works at the tight end, and only there
| Edge ratio (narrow fly) | Names | Wins | Before costs | After costs |
|---|---|---|---|---|
| 0.70 or under | 8 | 6 | +$257 | +$92 |
| 0.70 to 0.85 | 3 | 0 | -$186 | -$238 |
| 0.85 to 1.00 | 6 | 3 | -$97 | -$183 |
| 1.00 to 1.25 | 7 | 3 | +$60 | -$61 |
| 1.25 or more | 8 | 4 | +$156 | -$67 |

- Names that pass every gate we can replay (edge, regime, intraday, macro, price):
  at 0.85 or under, 9 names, 6 wins, +$120 before costs, -$75 after;
  at 0.70 or under, **6 names, 6 wins, +$306 before costs, +$162 after** (TFC, PCG, JCI,
  REPL, ON, ECHO). Against the other 26 names (10 wins) that is about a 1-in-100 chance
  result (Fisher, one-sided, p = 0.009). With the 4 flagged events included it is 9 of 9.
- The 0.70 to 0.85 band lost on all three (KGC, CVNA, CPNG), at both wing widths.
- Across the whole range the edge ratio does not rank names (rank correlation with
  move/implied: 0.05). It separates only the low tail: median move/implied 0.59 at 0.70
  or under, 0.88 for the rest.
- Small sample. The 0.70 line was set before this replay (H002), which is the reason to
  take it seriously; nine names are the reason not to change the rule on it yet.

## 3. The long-straddle side shows no edge
Edge ratio 1.25 or more, 8 names: the long straddle gained on 2 and lost on 6, -$755 in
total before costs. H009, proposed to Brad as P010 (switch it off).

## 4. Gates
- **Intraday.** Across all names a big move on entry day made no difference (above 5%:
  8 names, +$5 a fly; 5% or under: 24 names, +$6). But the two sell-zone names the gate
  actually blocked (CORZ -10%, IREN -17%) both lost. Tentative: keep it. H001 now 5 for
  dropping it, 4 against.
- **No-edge.** Names above 0.85: 21 clean, 14 lost or broke even, 7 won, +$6 a fly before
  costs and negative after. H005 at 16 to 8: keep the gate.
- **Regime guard.** Never tripped in this sample (highest ratio 1.24). No information.
- **Macro veto.** One priced name on a veto day. No information.
- **Spread and news gates.** Cannot be replayed.

## 5. Wing width
Per dollar of max loss the two widths earn about the same before costs (4.6% and 6.1% of
total max loss). Wide wings earn more per trade and lose less of it to costs, but the
average max loss is $438 against $130, and 15 of 31 are over $350. They do not rescue the
0.70 to 0.85 band. Recommendation: keep wings near 1x the straddle while the cap is $650;
the narrow fly is only worth trading at the tight end of the edge ratio.

## 6. Other readings
- **Week.** Narrow fly by entry week: +$223 (3), -$22 (3), -$39 (10), +$29 (16). The
  pilot's "0 for 8 in the week of 11/02" was those names (ARM, QCOM, APP, NET, IREN), not
  the market.
- **Exit time.** The average move from the close was 4.8% at the open, 6.3% at 10:00 ET
  and 6.9% at 10:30 ET; 24 of 32 names were further away at 10:30 than at the open.
  Exiting early is right.
- **Projection inputs.** Remaining stdev after the report over before: median 0.65,
  quartiles 0.50 and 0.71 (pilot: 0.61). Wings price at 1.01 to 1.09 times the body's
  stdev. The projection model's inputs hold.
- **Cross-check with the pilot.** IREN 11/05 is in both: -64% of max loss there, -41%
  here (later exit bar, model wings).
- **Universe.** About 165 liquid-option earnings events a week in season, about 55 with
  weekly options, about 10 to 14 passing at 0.70 or under before the spread and news
  gates. Enough for a two-slot book.

## Exploratory splits (found after the fact: not evidence, to be tested on new data)
- Implied move 10% or more: 16 names, 7 wins, -$153. Under 10%: 16 names, 9 wins, +$343.
- Reports before the open did better than after the close (15 of 22 wins against 5 of 14,
  all 36 events).
- Stocks under $25: 3 wins of 10.

## Ledger
- Evidence added: H001 (1), H002 (3), H003 (1), H005 (21), L009 (1), H008 (7), H009 (8).
- New: H008 (the core signal at 0.70 or under), H009 (long straddles lose, proposed),
  L012 (fill slots lowest edge ratio first). L007 retired (built into the tooling).
  Three new entries from one batch, above the two-a-day cap, because the batch is about
  two weeks of daily scoring.
- Queued for the next reflection: a hypothesis on implied move 10% or more, and an
  execution lesson on exit time.
- Proposals: P009 (second batch, lite method), P010 (long straddles off), P011
  (at-the-money implied move in the engine, with P004).

## Cost
About 2.0M tokens: pricing 1.37M (9 agents), history 0.33M (2 agents), sampling about
0.25M. About 55k per priced event. The lite method should bring that to 15k to 20k.
