# Week replay, 2026-11-21: exits 2026-11-16 to 11-20 added to the sample
Method: docs/earnings/REPLAY.md, lite form (stock bars, K call and put, model wings with multiplier 1.0).
Brief: brief_week.txt. Read-only; no order, alert or watchlist call. Costs are 7% of the entry credit.
(Collected by a read-only agent; the harness kept it from writing this file, so the head saved its text.)

## Drawn 111, priced 83, clean 68
- Source: the high-market-cap calendar for 11-13..11-20, plus SHAZ, PERI and DAO from the scans. Left out:
  SGAPY, CSANY and TKOMY (the calendar gives no timing). TSLA did not report.
- 11-20 is the monthly expiry, so nearly every optionable name lists it. no_weekly 4 (WF, TCEHY, MSADY,
  SUBCY). no_data 24: 5 symbols the broker does not know (RAMP, CEP, ZK, HI, ATKR) and 19 with no body
  entry trade. 15 priced events fail put-call parity.

## This week (68 clean)
| Structure | Exit | n | Wins | Mean | se | Worst |
|---|---|---|---|---|---|---|
| Short straddle, share of straddle | 10:00 | 68 | 45 | +6.7% | 5.2% | SNEX 11-18, -1.52x |
| Fly as traded (aim 1.5x, $350 cap) | 10:00 | 58 | 30 | -$10.9 | $16.1 | NTES 11-19, -$330 |
| Fly as traded | 10:30 | 58 | 36 | +$8.6 | $17.0 | NTES 11-19, -$354 |
| Fly as traded, 10:00 minus 10:30 | paired | 58 | | -$19.5 | $7.0 | |
Nearly every 10:00 option bar this week is a single print, and the two exits differ by 2.8 se on the same events.

## Whole sample (183 clean: fall 32 + 71, summer 12, this week 68)
Batch 2's derived.jsonl shares no symbol and report date with 11-10, so all four files are used.
fly_table.json is scored at the rules' $600 name cap (v1.16); fly_table_cap350.json at the old $350.
| Measure | n | Wins | Mean | se | Worst |
|---|---|---|---|---|---|
| Short straddle, first exit, share of straddle | 183 | 124 | +10.0% | 2.9% (t 3.5) | SNEX 11-18, -1.52x |
| Fly as traded, $600 cap, first exit | 179 | 123 | +$2.3 | $10.2 | -$649 |
| Fly as traded, $350 cap, first exit | 171 | 95 | -$0.4 | $8.3 | NTES 11-19, -$330 |
| Fly 1.5x with no cap, first exit | 183 | 125 | +$5.9 | $13.8 | FTNT 10-28, -$1,199 |
| Paired 10:00 minus 10:30, $600 cap | 177 | | -$6.4 | $3.7 | |
- Breakeven cost of the fly as traded: 7.6% of the credit at the $600 cap, 6.9% at $350, against the 7%
  assumed. At the 3.9% live cost (11 earnings trades) the $600-cap fly keeps about $15 (at 3%: $19, 5%: $11).
- On the earlier 113 events the $350 fly was +$5.0 (se $9.4). The change is within 1 se.
- Cap sweep (aim 1.5x, first exit, n, mean, worst): $250 163 -$2.8 -$259; $300 166 -$4.0 -$299;
  $350 171 -$0.4 -$330; $400 175 +$1.6 -$363; $500 177 +$3.3 -$389; $600 179 +$2.3 -$649; no cap 183 +$5.9 -$1,199.
  Aim 2x: $350 171 +$1.2 -$346; $600 179 +$4.0 -$649; no cap 183 +$12.9 -$1,589. No row is more than 0.75 se from zero.

## Limits (REPLAY.md)
Prices are last trades in 30-minute bars, not quotes: no bid-ask, stale or single prints, 0.01 = missing. Wings
come from a model. The spread gate and the news gate cannot be replayed. One contract per event, at printed
prices. This week is unusual: the monthly expiry priced 75% of drawn events (normally about a third), and it
adds monthly-only names with $5 grids and K 2-3% off spot. GLNG has an unconfirmed report (null EPS); without
it the week moves by under $1 a fly.
