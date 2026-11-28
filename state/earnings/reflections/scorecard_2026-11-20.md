# Weekly scorecard, 2026-11-16 to 2026-11-20

## Result (after fees)
| Trade | Line | Edge | Move / implied | P/L |
|---|---|---|---|---|
| PCG 12/13/14 x5 | non-earnings | | 0.02 move | +19.37 |
| JD 25/27.5/30 x3 | earnings | 0.60 | 0.93x | +3.16 |
| AS 26/29.5/33 | earnings | 0.87 | 0.91x | -0.28 |
| HD 140/157.5/175 (partial + exit) | earnings | 0.64 | 0.64x | +379.68 |
| TGT | earnings | 0.58 to 0.64 | 0.6x | +100.84 |
| TJX 123/131/139 | earnings | 0.58 | 1.60x | -125.16 |
| WMT 119/127/135 | earnings, near-miss | 0.89 | 0.38x | +182.84 |
| PANW (Brad's close) | earnings, owner lane | | | +163.84 |
| PDD 72/78/84 | earnings, near-miss, soft news | 1.07 | 1.52x | -197.29 |
| IWM same-day x3 | pilot | | | -27.92 |
| ANT 10 sh (Brad's hand buy, closed on his word) | owner hand | | | -110.72 |
- Week +388.36: earnings flies +507.63 (8 trades, 5 wins), pilot -27.92, non-earnings +19.37, owner hand -110.72.
- Since the start: 17 closed +183.34, adjustments +170.98, total +354.32. Win rate 59%, edge bias 1.10 (moves ran 10% over what the ratio implied), realized/implied 0.84 on average.
- Cost against mid: 0.051 of the credit over 9 closed trades, 0.020 on earnings flies (replay assumes 0.07, breakeven 0.09).
- The two near-miss flies split: WMT +183, PDD -197. Near-miss tier: 2 trades, net -14.

## Names we skipped, scored
| Name | Blocked by | Result | Did the rule help? |
|---|---|---|---|
| FRO | passed; declined on the exit-priced check | +78 mid / -40 natural | yes at the natural |
| INTU | edge 1.06 near-miss, no fly fit the half cap | +210 mid / -585 natural | unclear: $6 wide puts at the open |
| ROST | wide spread, no fly fit the half cap | 1x +356 (last trades) | no on outcome |
| ESTC | wide spread, no fly fit the 175 cap | 1x +611 (last trades) | no on outcome |
| GAP | edge 1.25 | 1x -45 | yes |
| P (11/18) | edge | 1x +41 | no difference |
| BABA (11/18) | edge above 1.10 | 2x +129 | no on outcome |
- Paper ledger: 183 records, 70 scored: +3,344 at the mid, -1,258 at the natural. The gap between the two is the week's main lesson: fills, not signals, decide these small trades.

## Rules: helped or hurt this week
- Exit-priced view (H015, P070): FRO and PDD both point the same way; replay on Saturday.
- Near-miss tier (v1.10): net -14 on 2 live trades, too few to judge.
- Same-day pilot (v1.15): -27.92 on 3 trades; the paper desk lost 9 of 9 on Friday's trend day. H016 filter goes to Saturday's replay.
- v1.2.2 at max loss: right for NVDA-type deep losers, wrong on expiry day near the long strike (P071).
- Grades this week: A 16, A- 10, B+ 11, B 10, B- 1, C+ 1, C 11, D 4 (64 decisions). The D's were all process: timers and switches.

## Lessons ledger
- Held: L010 selfcheck (+9), L014 do it now (+7), L017 executable plans (+7), L027 owner ticket disclosure (+3), L028 timers (+2, yet broken twice in practice).
- Hypotheses: H008 tight-end edge +14/-7 neutral today; H009 long straddle +15/-13 (GAP contradicts); H011 same-day no edge +3/-1; H012 small gap +1/-3 (weakening); H015 exit-priced +2/-0; H016 new.
- Proposals verified this week: P060 and P068 did_not_work (replaced by P072); P065 inconclusive.
- Open with Brad: P053 data feed, P050 tastytrade (hard limits). Multi-leg: review step now accepts 2-leg orders, place still refuses (retried Friday).
