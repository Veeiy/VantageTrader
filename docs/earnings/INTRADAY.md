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

- **Probe tier (on).** One contract, max loss at most $150. Today the only name on the live
  list is IWM (about $26 of max loss when the wings are one strike wide, about $75 at two);
  other names join by the rule under "Which names" below. It buys what paper cannot
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
| Probe max loss | $150 | $150 |
| Signal max loss | $200 | $200 |
| Entry window | 07:25 to 07:50 PT | |
| Flat by | 11:00 PT | 12:15 PT |
| Body spread | 3% of the straddle | 5% |
| Pilot pauses at | -$500 in total, or 6 losses in a row | same |
| Review | after 10 closed trades | |

The total risk cap covers both lines: the fly's max loss plus a $50 exit reserve must fit, and
one in-the-money short at the wing must fit the buying power left after entry.

Pilot trades carry `"kind": "intraday_0dte"` in the journal. They have their own breaker and
are **not** counted in the account's loss streaks: a one-contract pilot must not be able to
halt the main line. (P017 as written counted them. Changed on purpose.) The account breaker
still stops the pilot.

Off switch: "day trades paper" from Brad sets `intraday_live_enabled: false`.

## Ninety days, seven names (2026-11-16, later the same evening)
Brad: "What about for using robinhood if we widen the daytrading parameters? Like so it can be
run on other stocks if they meet the criteria? How about we run simulations on the last 90 days
for this". Done the same evening: every session from 2026-08-18 to 2026-11-16 for SPY, QQQ and
IWM (64 each) and every Mon/Wed/Fri same-day session of NVDA, AAPL, AMZN and META (38 each), 344
sessions, 290 with clean entry prints. `scripts/earnings/intraday_replay.py --admission`; numbers
in `state/earnings/daytrade/replay/admission_90d.json`. Result = the average of the 11:00, 11:30
and 12:00 exits, after costs.

| Name | Cost a fly | All flies | Mean | Flies the pilot's gates pass | Mean | Max loss |
|---|---|---|---|---|---|---|
| IWM | $5 | 52 | -$3 | 36 | -$1 | $36 |
| AAPL | $16 | 33 | -$6 | 14 | $0 | $83 |
| QQQ | $8 | 55 | -$13 | 30 | -$3 | $111 |
| NVDA | $8 | 26 | -$9 | 6 | -$7 | $95 |
| SPY | $8 | 57 | -$7 | 43 | -$8 | $77 |
| AMZN | $17 | 34 | -$19 | 10 | -$20 | $99 |
| META | $40 | 33 | -$2 | 3 | too few | $133 |
| All, per day | | 62 days | -$8 | 56 days | -$6 | |

- **No name makes money on this trade.** Before any cost the 290 flies average +$5 (standard
  error $4): nothing. After costs every exit time is negative, and the first 90 minutes are
  significantly so (-$16 at 08:00, t about -5 per day).
- **Widening does not help.** AAPL is the only stock near breakeven and its spread (about 4% of
  the straddle) is over the 3% line. AMZN is clearly negative. META needs more than the $150
  cap and costs about $40 a fly to cross. NVDA is on hold and negative anyway.
- **The two filters, on sessions they were not found in** (index funds, 2026-08-18 to
  2026-10-05): the overnight-gap filter kept its direction (-$4 a fly after a gap under 1%
  against -$20 after a bigger one, the same -$20 as in the first batch) but the flies it keeps
  still lose; the calm-open filter failed (-$9 against -$5). The gap gate stays as a risk
  filter. Neither is an edge.
- **The premium ratio** does nothing in any bucket (-$4, -$8, -$15, -$9, -$5 from cheap to rich).
- **So:** the live list stays IWM alone, the probe keeps its time box, and nothing is scaled.
  The research moves to where the evidence says sellers are paid: overnight
  (`docs/earnings/PLAN.md`).

## Cap levels: what was tested (2026-11-16)
Brad: "$150 is an extremely small cap. Can you test it with different cap levels? Could be a
buying power issue." `scripts/earnings/intraday_caps.py` ran the 77 clean flies of the replay
at an 11:00 PT exit; numbers in `state/earnings/daytrade/replay/cap_levels.json`.

**The per-trade cap** (contracts = cap / one fly's max loss). A bigger cap scales the result and
the swing together; it does not find an edge.

| Cap | IWM a day | SPY a day | QQQ a day | Buying power needed |
|---|---|---|---|---|
| $80 | -$5 (sd $43) | -$42 | too big | about $300 |
| $150 | -$11 (sd $87) | -$31 | -$36 | $370 to $700 |
| $200 | -$14 (sd $122) | -$49 | -$36 | $390 to $860 |
| $400 | -$28 (sd $254) | -$105 | -$62 | $620 to $1,280 |
| $600 | -$44 (sd $389) | -$147 | -$98 | $800 to $1,560 |

Buying power is not what holds the line back: a $400 cap fits a flat account. With the earnings
book on (about $450 to $900 free) SPY and QQQ flies above about $200 do not fit.

**Wider wings.** The body straddle with no wings at all is the limit of ever wider wings. It did
worse than the 1x fly on every name (all names: -$39 against -$13 a trade, with more than three
times the swing). A wider fly and a bigger cap buy swing, not profit, on this data.

**The budget.** Here he was right. Over 20 one-contract IWM probes with no edge:

| Rule | Stops the pilot by luck |
|---|---|
| -$150 in total | 23% to 26% of runs |
| -$200 | 11% to 13% |
| -$300 | 2% |
| 3 losses in a row | 60% to 79% |
| 5 losses in a row | 12% to 25% |
| 6 losses in a row | 5% to 12% |

With SPY-size flies in the mix (one contract, max loss up to $150) a -$300 budget stops 30% of
runs by luck and -$500 stops 5%.

**Decided the same evening:** probe max loss $150 (was $80), budget -$500 (was -$150), streak 6
(was 3), still one contract and one fly a day. The time box (20 probes or 2026-12-18) is what
bounds the cost: about $20 to $170 in expectation depending on the names.

## Which names
Brad, 2026-11-16: "Scan the market for optimal daytrading options. Lets not lock ourselves to
just a few tickets. But liquidity and tightish spreads is important not to eat into profits".

- **The universe** is rebuilt from the market, not typed in: every name with average options
  volume of 100,000 contracts a day or more, plus the index funds and products, and for each
  the days it has a same-day expiration (`state/earnings/daytrade/universe/`).
- **The spread scan** quotes every universe name that expires that day at about 07:00 PT and
  ranks them by the body straddle's bid-ask spread and by the cost of crossing it as a share
  of the credit (`prompts/brief_daytrade_scan.md`; Tue, Wed and Fri this week, then Fridays).
- **A name joins the live list** (`intraday_probe_names`) when all three hold: its median body
  spread over five scan mornings is 3% of the straddle or less; a replay of at least 20 of its
  sessions shows a mean after costs no worse than IWM's per dollar of max loss; one contract
  fits the probe cap. The decision is ledgered. TSLA never; NVDA not while its hold stands.
- **The day's pick** among live names: the one whose spread cost is the smallest share of its
  credit that morning, and never the same name more than three days running.
- The paper desk keeps its ten names every day as the control.

**The universe on 2026-11-16** (`state/earnings/daytrade/universe/universe_2026-11-16.json`, 72
names: 60 from the scanner, 12 added by hand):
- **A same-day expiration every day (9):** SPY, QQQ, IWM, IBIT, GLD, and the index options XSP,
  SPX, NDX, RUT (cash-settled, no early assignment; SPX, NDX and RUT trade in 5 and 10 cent
  steps and a one-contract fly on them is far above the cap; XSP is SPY-sized).
- **Mon, Wed, Fri (20 tradable):** NVDA (on hold), TLT, MU, XLF, AAPL, AMD, SLV, AMZN, GOOGL,
  LQD, META, SMH, MSFT, TQQQ, AVGO, XLE, GDX, IEF, SPCX, DRAM. TSLA is in this class and blocked.
- **Fridays only (40):** EWZ, HYG, INTC, NFLX, MSTR, SOXL, EEM, ORCL, PLTR, HOOD, COIN and others.
- Spreads cannot be judged with the market closed. What the paper desk saw at 07:15 PT on
  2026-11-16, body spread as a share of the straddle: SPY 0.7%, QQQ 0.7%, NVDA 1.0%, IWM 1.1%,
  META 2.6%, AMZN 2.8%, AAPL 3.8%, IBIT 4.2%, AMD 5.1%, MSFT 5.2%.
- Seven names got their own 90-day replay on 2026-11-16 ("Ninety days, seven names" above)
  and none was admitted besides IWM. IBIT, GLD and XSP are not replayed before the 10-probe
  review: the test found no edge before costs worth protecting with a cheaper name
  (`PLAN.md`, line B). The morning spread scans keep running and are read on Saturdays.

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
   `get_option_chains("IWM")`: today must be in `expiration_dates`. (IWM lists an expiry every trading day; chain id
   `72362eb7-bc7c-4d10-9be4-48a53fffd101`, penny ticks.) Body strike K = the whole
   strike nearest spot. `get_option_instruments(chain_symbol="IWM", expiration_dates=<today>,
   strike_price="<K>.0000")` gives the call and the put (never query without a strike);
   `get_option_quotes` for both. W = the body straddle mid rounded to the nearest whole number,
   at least 1. Look up the K+W call and the K-W put and quote them.
5. **Gate.** Write the candidate (shape at the top of `src/vantage_trader/earnings/intraday.py`:
   symbol, spot, prev_close, K, expiry, call, put, wings, same_hours_moves, event_ahead,
   macro_veto, exits_pending, account_value, open_risk_usd, buying_power from `get_portfolio`,
   open_intraday, entries_today) and run `... intraday-gate --input <file>`. Exit code 3: no trade today;
   write the reason into the day's notes. Exit code 0: enter.
6. **Enter** (four single-leg limit orders; if this is the day's first structure, one
   multi-leg attempt comes first: `prompts/exit_scan.md`, MULTI-LEG FIRST). The entry is ONE
   BLOCK OF WORK (rules v1.16.2, P058): before the first wing order the four contracts are
   quoted, the gate has run, all four orders are reviewed, and every tool the entry needs is
   loaded. From the first wing order until the fly is complete or unwound, nothing else is
   read, written or answered.
   a. Buy both wings in one message as marketable limits (the ask plus 0.02).
   b. The next message reads the two fills and quotes the body.
   c. The message after that sells the body call and the body put together as marketable
      limits (each bid minus 0.03; a sell limit fills at the bid that is there). The floor is
      checked on that read: the two body bids minus the wing fills may not be under the gate's
      `limit_floor`. A straddle's sum does not move with the spot, so limits a few cents
      through the bid cost nothing and stop one leg from being missed.
   d. A body leg still open at the next read: cancel it, confirm zero fills, and sell it at
      once as a marketable limit. The fly is FINISHED when its body strike is still within
      0.5 x the straddle of the spot, even if the total credit is then under the floor: the
      slip between the legs is already lost and unwinding pays the spread on three legs. If
      the spot is further away than that, UNWIND (buy back the lone short, sell both wings).
      Either way the fly is one-sided for at most 60 seconds.
   e. An order the session's own permission check refuses is a different case:
      `prompts/entry.md`, REFUSED MID-STRUCTURE, with a 5 minute unwind.
   Why (2026-11-17, IWM): the body went out 237 seconds after the wings and with the bids of
   20 seconds earlier as limits; the call missed, IWM fell 0.40 in the 187 seconds the fly was
   one-sided, and the credit came in at 1.14 against a mid of 1.28. That $13.5 is more than
   the replay's whole average result for a same-day IWM fly.
7. **Record.** Journal `entry_filled` with `"kind":"intraday_0dte"`, `"tier"`, `price` (net
   credit), `max_loss`, `direction":"credit"`, `expiry`, the legs with order ids. A
   `live_metrics.jsonl` entry record (`trade_id` `IWM-0DTE-<YYYYMMDD>-L1`, kind
   `intraday_0dte`, live true, the gate record, the premium ratio, fills against mid, seconds
   from the first order to the last fill, and a `projection` block: mean, sd and win rate for
   this name at the 11:00 exit from `state/earnings/daytrade/replay/summary.json`).
   `positions.json`: an open entry with `kind`, legs, max loss, `exit_reserve_usd` 50 and the
   plan "flat by 11:00 PT". Add the fly to the monitor's brief. Commit, push, one line to Brad.
   The execution block also carries `seconds_wings_to_first_short`, `seconds_one_sided` and
   `leg_slip.usd` (the mid value of the legs already held when the last leg is sold, against
   their fills). A fly Brad orders outside these rules carries `"outside_test_data": true` on
   its journal entry: it counts for the pilot's breaker and not for the 20-probe test.
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
  reusable. The out-of-sample batch (the 34 sessions before 2026-10-06) was run on 2026-11-16,
  the same evening the two filters were fixed: F1 = overnight gap under 1% (already a gate)
  kept its direction and is no edge; F2 = F1 and |price at 07:30 / open - 1| under 0.2%
  failed ("Ninety days, seven names"). No further same-day batch is planned before the
  10-probe review. The research queue is in `PLAN.md` section 9.
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

## Week of 2026-11-16: spreads and what the probes paid (Saturday 2026-11-21)
Spread scans (`state/earnings/daytrade/<date>/scan.json`), at-the-money spread as a share of mid
and the round trip as a share of the fly's credit:

| Scan | Names | Median spread | Median cost share | IWM spread | IWM cost share |
|---|---|---|---|---|---|
| 2026-11-17 | 9 | 2.7% | 2.6% | 1.0% | 2.9% |
| 2026-11-18 | 31 | 5.8% | 8.1% | 0.8% | 2.7% |
| 2026-11-20 | 40 | 6.4% | 10.5% | 1.5% | 3.1% |

The wider the scan, the worse the median: the names past the index funds and mega caps cost
more than the 9% breakeven. SPY (1.7%), NVDA (2.3%) and IWM (3.1%) led on 2026-11-20.

What the three IWM probes actually paid against mid, round trip as a share of the credit
(`live-metrics` round_trip_cost, P055): 15.4% (11/17), 2.2% (11/18), 12.6% (11/19). Mean
10.1%, worst 15.4%, n = 3. The scan's quoted 3% is the spread; the probes paid about three
times that, mostly on the exit legs bought back into a moving market. The 10-probe review
(PLAN.md line B) uses the fill cost, not the quoted spread. No new same-day name is replayed or
admitted before that review.
