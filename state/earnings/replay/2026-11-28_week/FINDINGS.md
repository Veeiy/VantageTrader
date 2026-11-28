# Week replay, 2026-11-28: exits 2026-11-23 to 11-27 added to the sample
Method: docs/earnings/REPLAY.md, lite form (stock bars, K call and put, model wings at multiplier 1.0).
Brief: brief_week.txt. Read-only; no order, alert or watchlist call. Fly costs are 7% of the entry credit.
(Collected by a read-only agent; the harness kept it from writing this file, so the head saved its text.)

## Drawn 50, priced 23, clean 23
- Source: high-cap calendar 11-20..11-27 (pm 11-20..11-25, am 11-23..11-27) plus SHOE (11-23 scan). Left out: GGAL,
  DIDIY (no timing), 11-20 am names (exit 11-20), HUBG (next report 12-11, tentative). TSLA did not report.
- 11-27 is a weekly: no_weekly 24 (exact-strike probes, state expired). no_data 3: CVAC, WNGRF, FORTY.
- All 23 pass put-call parity at entry and 10:30; 5 fail it at 10:00 (flagged, not excluded).

## This week (23 clean), first exit bar (10:00 ET), wins after costs
| Structure | n | Wins | Mean | se | Worst |
|---|---|---|---|---|---|
| Short straddle, share of straddle (no cost) | 23 | 8 | -16.8% | 11.2% | ZS 11-23, -1.88x |
| Fly as traded (aim 1.5x, $600 cap) | 19 | 4 | -$102.0 | $47.7 | ZS 11-23, -$437 |
| Fly as traded, $436 cap | 16 | 4 | -$66.0 | $42.9 | ZS 11-23, -$335 |
| Fly as traded, $350 cap | 13 | 3 | -$52.8 | $32.1 | AMBA 11-24, -$202 |
ADI, BURL, DE and DELL do not fit $600 even at 0.9x (out of the capped rows); ADI is -$1,471 uncapped.
ZS 10:00 rests on one K-call print of 45.98 with the stock at 227.31 (about -1.05x at 10:30).

## Whole sample (206 clean: 32 + 71 + 12 + 68 + 23); no symbol and report date shared across the five files
| Measure (first exit; flies after 7% cost) | n | Wins | Mean | se | Worst |
|---|---|---|---|---|---|
| Short straddle, share of straddle (no cost) | 206 | 132 | +7.0% | 2.9% (t 2.4) | ZS 11-23, -1.88x |
| Fly as traded: aim 1.5x, stepped in to $600 | 198 | 103 | -$7.7 | $10.5 | FTNT 10-28, -$649 |
| Fly as traded, $436 cap (account ceiling) | 192 | 102 | -$2.9 | $8.9 | NTES 11-19, -$386 |
| Fly as traded, $350 cap | 184 | 98 | -$4.1 | $8.0 | NTES 11-19, -$330 |
| Fly 1.5x, no cap | 206 | 109 | -$12.3 | $15.9 | ADI 11-24, -$1,471 |
- Breakeven cost, fly as traded: 5.3% of the credit at $600 (6.3% at $436, 5.9% at $350) vs 7% assumed. At 3% cost
  the $600 fly keeps +$10.3, at 5% +$1.3. Last week (179 events) it was +$2.3 (se $10.2): down about 1 se.
- Cap sweep (aim 1.5x: n, mean, worst): $250 174 -$4.6 -$259; $300 177 -$5.7 -$299; $350 184 -$4.1 -$330;
  $400 190 -$5.2 -$363; $500 195 -$4.8 -$389; $600 198 -$7.7 -$649; none 206 -$12.3 -$1,471. Aim 2x: $350 184
  -$2.7 -$346; $600 198 -$6.6 -$649; none 206 -$11.3 -$2,144. No row is more than 0.8 se from zero.

## Limits (REPLAY.md)
Prices are last trades in 30-minute bars, not quotes: no bid-ask, stale or single prints (every 10:00 option bar
this week is one print), 0.01 = missing. Wings come from a model. The spread gate and the news gate cannot be
replayed. One contract per event, at printed prices. A weekly-expiry week prices about half of what it draws.

## The exit-priced filter on the whole sample (P070, H015), run by the head after the collection
Bar written 2026-11-21, method note and script pushed before the first run (PLAN.md section 9 item 5; commits
c98bae4, ad70e94). `exit_priced_test.json` holds every event. 206 clean, 193 used: 8 have no fly under $600,
5 have under 4 past moves. Results are the fly as traded at its first exit bar after 7% of the credit.
| Row | n | Wins | Mean | se | Worst |
|---|---|---|---|---|---|
| All used | 193 | 99 | -$8.1 | $10.5 | FTNT 10-28, -$649 |
| Kept: projected above zero | 82 | 46 | +$6.8 | $14.0 | DKS 11-24, -$331 |
| Blocked: projected at or under zero | 111 | 53 | -$19.1 | $15.1 | FTNT 10-28, -$649 |
VERDICT: kept minus blocked +$25.9, standard error $14.5 clustered on 36 report dates, t 1.78. The gap passes
$10 and the kept side beats the whole sample; the t is under 2. PARKED.
By batch (kept / blocked): fall 45 +$14.3 / 57 +$0.3; summer 7 +$19.7 / 5 -$58.6; week of 11/16 24 +$0.9 /
36 -$4.0; week of 11/23 6 -$40.1 / 13 -$130.5. Rank correlation, projected against result: 0.13.
Description only, same method, not a second try (kept minus blocked, clustered t): scale 1.05 +$10.3 (0.78);
scale 1.43 +$17.5 (1.14); cap $436 +$13.2 (1.24, n 187); no cap +$85.5 (3.19, n 201, the tail events are
blocked); result at the 10:30 bar +$27.0 (1.55); with the stdev the market really showed after the report
+$51.6 (3.54, kept 52, blocked 141). The stand-in for that stdev ran at a median 0.73 of the real figure
(quartiles 0.56 to 0.91): the projection is too kind, which is why it keeps DKS, ADSK and HPE.
The edge ratio on the same 193: at or under 0.85 -$12.0 (n 74), above -$5.6 (n 119), difference -$6.4, t -0.45.
Inside the 74 the filter blocks 10 (-$32.0 against -$8.9): too few to read.
Scan coverage (P016): 21 of the 23 priced names were on a watchlist that week; CRWD (edge 0.86) and ZS (1.74),
both listed for Monday before the open, were not. Neither is under 0.85.

