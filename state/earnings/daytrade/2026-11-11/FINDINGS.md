# Day-trade scan, 2026-11-11

Brad, 07:09 PT: "lets do some day trading for the iv crush/theta decay", and 07:17 PT:
"doesnt just have to be spy. look across the market and scan optimal day trades for us to
leverage the theta decay and iv crush".

## Facts
- Day trades are allowed: the pattern-day-trader rule ended 2026-06-04 (FINRA Notice 26-10).
  Not yet confirmed at the broker by an actual same-day round trip.
- Theta is only large enough to day trade in options that expire the same day. An option
  with two days left loses about 5% of its value in a session.

## 1. Day after earnings (leftover IV crush), live at 10:21 ET
`post_earnings_scan.json`. Implied move per day over the stock's normal daily move:
PBR 0.81, RGTI 0.78, FLY 0.78 (spread 28%), CRWV 0.80 (head's own check), ODD 1.21 (spread
45%). Nothing to sell. Note: the scanner's earnings-date field rolls to the next quarter once
a company has reported, so names that reported the night before must be added by hand.

## 2. Day after earnings, replay
`replay_intraday_raw.jsonl` (32 events, 13 half-hour bars of day X each, stock and the two
body options) and `replay_intraday_1030_1530.json`. At-the-money iron fly with model wings
at 1x the straddle, priced from the implied stdev of the real body prices:

| Sold | Closed | Usable events | Wins | Total before costs | After 7% of credit |
|---|---|---|---|---|---|
| 10:30 ET | 15:30 ET | 19 | 11 | +$25 | -$241 |
| 10:30 | 16:00 | 17 | 10 | +$53 | -$202 |
| 11:00 | 15:30 | 19 | 9 | -$75 | -$328 |
| 12:00 | 15:30 | 18 | 10 | -$24 | -$278 |
| 13:00 | 15:30 | 20 | 11 | -$9 | -$269 |

The implied stdev fell about 6% from 10:30 to 15:30 (median ratio 0.935); stock moves ate it.
No edge. Limits: 30-minute last-trade prints, 13 events dropped for missing or incoherent
prints, model wings.

## 3. Same-day expiry, 23 names, live at 10:21 ET
`zero_dte_scan.json`, `zero_dte_fly_ev.json`. For each name: the same-day straddle against
the move from 10:00 ET to the close over the last 15 sessions, and the result an
at-the-money iron fly (wings 1x the straddle) would have had on each of those sessions.
- Fly result after rough costs: positive for IWM, META, SPY; negative for the other 20
  (QQQ -$36, GOOGL -$65, AMD -$186 a day).
- With real listed strikes, natural credit and costs: IWM 281/282/283 +$6.6 a day
  (standard error $9.8, max loss $30); SPY 753/756/759 about -$3; META 630/637.5/645
  -$13 to -$45 (body 2 points off spot, past moves skewed down).
- No same-day expiry: DIA PLTR COIN MSTR HOOD EEM FXI KWEB HYG SOXL NFLX INTC BABA UBER SOFI.

## Verdict
No day trade with a demonstrable edge today. Paper entries recorded for SPY, IWM and META
(`live_metrics.jsonl`, kind `intraday_0dte`), scored at the reflection from 5-minute bars.
Live trading of same-day flies is outside rules v1.2 and waits for Brad's answer on P017.

## Where to look next
- Event days after the event (Fed decision 11:00 PT, CPI mornings): same-day premium is
  inflated and deflates the same day.
- Fridays: weekly-expiry single names become same-day.
- The straddle-against-average-move test picks names that are moving on news that day
  (META). The 15-session fly result is the better ranking for capped flies.
