# Same-day pilot (rules v1.15, proposal P017)

Brad, 2026-11-16 about 18:15 PT: "Push the day trading pilot" and "Dont need a decision on me.
Remember, self healing and strengthening the model with your own decision making".

Earlier, 2026-11-11: "lets do some day trading for the iv crush/theta decay."

## The trade
An iron fly in options that **expire today**: short the call and the put at the strike nearest
the price, long one wing each side at the listed strikes nearest one body straddle away (at
least one strike). Sold about 07:30 PT, bought back by 11:00 PT. Defined risk, limit orders,
single-leg execution, never TSLA.

## What the evidence says (2026-11-16)
`state/earnings/daytrade/replay/`, scored by `scripts/earnings/intraday_replay.py`: every
session from 2026-10-06 to 2026-11-16 (30 sessions) for SPY, QQQ and IWM, 90 flies, real
30-minute option prices, sold at 07:30 PT. Twelve sessions whose 07:30 prints do not fit the
stock price are left out of the main numbers (keeping them changes nothing below).

| Exit (78 flies) | Mean a fly after costs | Wins | Per-day t |
|---|---|---|---|
| 08:00 | -$15 | 25% | -2.5 |
| 09:30 | -$6 | 54% | -0.6 |
| 11:00 | -$12 | 49% | -0.9 |
| 11:30 | -$6 | 46% | -0.2 |
| 12:30 | -$2 | 42% | +0.2 |

Costs: $8 a fly round trip for SPY and QQQ, $5 for IWM (eight single-leg orders).

- **No edge.** About breakeven before costs, slightly negative after. With all 90 flies the
  11:30 to 12:30 means are -$1 to +$2.
- **The first 90 minutes lose** (t about -3). After 09:30 the hold time makes no difference.
- **Stops hurt** (a stop at half the max loss: -$15 against -$8). **A take profit does
  nothing** to the mean. So the pilot has neither: the wings are the stop.
- **The premium ratio does not work as a trigger.** The 1.10 to 1.25 bucket, where P017's
  1.15 trigger sits, was the worst (-$48 a fly, 15 flies). No bucket pattern is consistent.
- **By name:** IWM is breakeven after costs (mean $0, worst -$54, best +$52 at 11:30); SPY
  -$4 to -$11; QQQ $0 to -$18 with a bigger swing.
- **Two patterns worth testing, neither proven:** an overnight gap under 1% (+$1 a fly
  against -$17 after a bigger gap) and a quiet first hour (+$7 against -$12).
- The paper desk agrees: 26 flies, +$450 at mid, -$92 at worst-case fills, and the index funds
  alone -$31 at mid.

Data caveats: bar-start prints, not quotes; about one mark in nine does not fit the stock
price and is skipped; 30 days is one market regime (a falling one).

## What the pilot does about it
The honest reading is that a larger live fly would be a coin flip that pays costs. So:

- **Probe tier (on).** One contract of the smallest fly, IWM only, max loss at most $80
  (about $26 when the wings are one strike wide, about $75 at two). It buys what paper cannot
  give: real fills on eight single-leg orders in same-day options, the first same-day round
  trip at the broker, and a live record to check the replay against. Expected cost about $5 a
  trade.
- **Signal tier (off).** Up to $200 of max loss on SPY, QQQ or IWM when the premium ratio sits
  inside a configured band. It stays off until a filter passes the test below.
- No entry after a move of more than 1% from the prior close, on a day with a tier-1 release
  or a Fed decision between the entry and the time stop (or within 15 minutes after it), or
  under a macro veto, hard or soft.
- Morning exits come first. While a position due to close that morning is still open (also
  one waiting on Brad's own closing order) there is no pilot entry: its buying power is not
  lent out. Flat before 07:50 PT: the gate is run again. After 07:50: no pilot trade that day.

## Limits (in code: `config/earnings.yaml`, hard caps in `config.py`)
| | Value | Hard cap |
|---|---|---|
| Contracts | 1 | 1 |
| Entries a day | 1 | 1 |
| Probe max loss | $80 | $80 |
| Signal max loss | $200 | $200 |
| Entry window | 07:25 to 07:50 PT | |
| Flat by | 11:00 PT | 12:15 PT |
| Body spread | 3% of the straddle | 5% |
| Pilot pauses at | -$150 in total, or 3 losses in a row | same |
| Review | after 10 closed trades | |

The total risk cap covers both lines: the fly's max loss plus a $50 exit reserve must fit, and
one in-the-money short at the wing must fit the buying power left after entry.

Pilot trades carry `"kind": "intraday_0dte"` in the journal. They have their own breaker and
are **not** counted in the account's loss streaks: a one-contract pilot must not be able to
halt the main line. (P017 as written counted them. Changed on purpose.) The account breaker
still stops the pilot.

Off switch: "day trades paper" from Brad sets `intraday_live_enabled: false`.

## The day
1. **Timer.** The morning run (`prompts/exit_scan.md`) starts a background timer for 07:27 PT
   once the morning exits are done. The 07:15 hourly run is the second net.
2. **Status.** `PYTHONPATH=src python3 -m vantage_trader.earnings intraday-status`. Paused:
   stop, say why in the day's notes.
3. **Yesterday's move.** One call `get_equity_historicals(symbols=["IWM"], start_time=<the
   previous session, 13:00Z>, end_time=<that day, 22:00Z>, interval="30minute")`. Take the open
   of the bar that begins 07:30 PT (14:30 UTC in summer time, 15:30 UTC from November to March)
   and the close of the last bar, then
   `python3 scripts/earnings/intraday_moves.py add --symbol IWM --date <that day> --open0730 X --close Y`.
   `python3 scripts/earnings/intraday_moves.py show --symbol IWM` prints the ten moves; its
   `last_date` must be the previous session.
4. **Quotes.** `get_equity_quotes(["IWM","SPY"])`: spot and `adjusted_previous_close`.
   `get_option_chains("IWM")`: today must be in `expiration_dates`. Body strike K = the whole
   strike nearest spot. `get_option_instruments(chain_symbol="IWM", expiration_dates=<today>,
   strike_price="<K>.0000")` gives the call and the put (never query without a strike);
   `get_option_quotes` for both. W = the body straddle mid rounded to the nearest whole number,
   at least 1. Look up the K+W call and the K-W put and quote them.
5. **Gate.** Write the candidate (shape at the top of `src/vantage_trader/earnings/intraday.py`:
   symbol, spot, prev_close, K, expiry, call, put, wings, same_hours_moves, event_ahead,
   macro_veto, exits_pending, account_value, open_risk_usd, buying_power from `get_portfolio`,
   open_intraday, entries_today) and run `... intraday-gate --input <file>`. Exit code 3: no trade today;
   write the reason into the day's notes. Exit code 0: enter.
6. **Enter** (four single-leg limit orders, each reviewed first). Buy both wings at the ask in
   one message. When both are filled, sell the body call and the body put at the bid in one
   message. These contracts are a penny wide: cross the spread, do not work the order. The net
   credit may not be under the gate's `limit_floor`; if the market moved, re-quote and run the
   gate again. A body order that is refused or unfilled after 60 seconds: `prompts/entry.md`,
   REFUSED MID-STRUCTURE, with a 5 minute unwind.
7. **Record.** Journal `entry_filled` with `"kind":"intraday_0dte"`, `"tier"`, `price` (net
   credit), `max_loss`, `direction":"credit"`, `expiry`, the legs with order ids. A
   `live_metrics.jsonl` entry record (`trade_id` `IWM-0DTE-<YYYYMMDD>-L1`, kind
   `intraday_0dte`, live true, the gate record, the premium ratio, fills against mid, seconds
   from the first order to the last fill, and a `projection` block: mean, sd and win rate for
   this name at the 11:00 exit from `state/earnings/daytrade/replay/summary.json`).
   `positions.json`: an open entry with `kind`, legs, max loss, `exit_reserve_usd` 50 and the
   plan "flat by 11:00 PT". Add the fly to the monitor's brief. Commit, push, one line to Brad.
8. **Hold.** No stop, no take profit, no add, no roll. Check-ins only mark it.
9. **Exit.** The 10:15 hourly run starts a background timer for 10:57 PT. Then: buy back both
   body legs at the ask in one message; sell each wing at the bid the moment its body leg is
   flat. A wing with no bid is left to expire only if it is more than 1% out of the money;
   otherwise sell it at any price (a long option in the money at the close is exercised). Any
   run that finds the fly open after 11:00 PT closes it at once; so does the standby.
10. **Record.** Journal `exit_filled` with `"kind":"intraday_0dte"`, `pnl` after fees,
    `realized_move`, `max_loss`. A `live_metrics.jsonl` exit record with the fills against mid
    and `projection_error` (result minus the projected mean, and that over the sd). Remove the
    position, commit, push, tell Brad the result in one line.

A closing order that is refused is told to Brad at once with the exact ticket and a push
notification, as for any other position. Robinhood sells out same-day positions at 12:45 PT;
that is the last net and never the plan.

## How it learns
- **Every probe is scored** against the replay's projection. After 10: is the live mean
  inside two standard errors of the replay mean, and is the round-trip cost against mid $6 or
  less?
- **The replay grows.** `brief_replay.txt` and the plan files in the replay folder are
  reusable. Next batch: the 30 sessions before 2026-10-06, on a weekend, as an out-of-sample
  test of the two patterns above. The filters are fixed now, before that data is looked at:
  F1 = overnight gap under 1% (already a gate); F2 = F1 and |price at 07:30 / open - 1| under
  0.2%.
- **The signal tier turns on** only for a filter that, on sessions it was not fitted on, shows
  a mean of at least +$10 a fly after costs with a per-day t of 2 or more over at least 60
  sessions in all. Until then: probes.
- **The probe tier ends** after 20 probes or on 2026-12-18, whichever comes first, unless a
  filter has passed. It also ends at once if the round-trip cost against mid averages more
  than $8 over the first 10, or if a leg is ever left open past the time stop.
- **A pause** (the breaker) is lifted only by a ledgered decision that says what changed, with
  `intraday_pilot_reset_ts` set to its time.
- The paper desk (`prompts/brief_paper_desk.md`) keeps running on all ten names as the control.

## Commands
```
PYTHONPATH=src python3 -m vantage_trader.earnings intraday-gate --input cand.json
PYTHONPATH=src python3 -m vantage_trader.earnings intraday-status
python3 scripts/earnings/intraday_moves.py show --symbol IWM
PYTHONPATH=src python3 scripts/earnings/intraday_replay.py [--names IWM] [--keep-bad-entries]
```
