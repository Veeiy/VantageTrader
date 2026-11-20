# The trading plan (v1, 2026-11-16)

Brad, 2026-11-16: "Research it, boss.. I want to harden out such a solid trading plan and algo
that we can continue to iterate and generate money."

This page is the plan the system works to. It says where the evidence points, what is traded
at what size, what is only tested, and what has to be true before anything grows. It changes
by ledgered decisions (`state/earnings/proposals.jsonl`), not by mood.

## 1. Where things stand
- Live record: 5 closed trades, 3 wins, about -$15. Too few to mean anything either way.
- Account about $1,995. Three earnings flies open into the 2026-11-17 reports.
- There is no proven edge yet. One line has good evidence behind it. Two were tested hard on
  2026-11-16 and came up empty.

## 2. What the evidence says

### Ours
| Test | Size | Result |
|---|---|---|
| Earnings, short straddle held over the report | 103 replayed events | Won 72 of 103 at the first exit bar and made 12.7% of the straddle on average, 3.8 standard errors. The premium is real. |
| Earnings, iron fly with no cap on its max loss | 103 events | After a 7% cost: -$8 a fly with wings at 1x the straddle, -$2 at 1.5x, +$3 at 2x. One report in the hundred (FTNT, 2026-10-28: -$1,199 at 1.5x) takes the whole edge. |
| Earnings, iron fly as the rules trade it: aimed at 1.5x, stepped in to a $350 max loss | 101 events that fit | +$7.5 a fly after a 7% cost, standard error $10, worst -$244. Aimed at 2x inside the same cap: +$10. Not distinguishable from zero yet. |
| Earnings, the per-name cap | 103 events | Caps from $250 to $500 all keep $5 to $9 a fly (aim 1.5x). No cap keeps nothing. Raising $350 to $400 adds $0.3 a fly. |
| Earnings, what the trade costs | 101 events, 5 live round trips | The capped fly makes $33 before costs on a credit of about $364: it breaks even at a cost of 9% of the credit. At 7% it keeps $7.5, at 5% $15, at 3% $22. Live so far (`live-metrics`, `round_trip_cost`): 6.3% on the five closed trades, 4.5% on the three earnings trades, range 1% to 12%. |
| Earnings, exit time | 100 events with both prints | 10:00 ET against 10:30 ET on the same events: $3 a fly for the earlier exit, standard error $3.5. No real difference. |
| Earnings, the 0.85 edge gate | 103 events | Throttles more than it selects. No filter holds in both batches. |
| Same-day fly, sold 07:30 PT | 290 flies, 7 names, 90 days | +$5 before costs (se $4), -$6 to -$10 after. No name passes. More names, bigger caps and wider wings do not change it. |
| Overnight fly, sold 12:30 PT, bought back 07:00 PT | 25 nights, SPY | +$2 before costs (se $15), -$6 after. Wins 68% of nights and gives it back on gap nights. Too few nights to call. |

Corrected 2026-11-16: the table of 2026-11-11 (+$9 a fly at 1.5x, +$17 at 2x, "the early exit
saves $6 to $16") compared the 10:00 ET exit with the 10:30 ET exit on different events. The
10:00 rows left out the events with no 10:00 print, and one of those is the largest loss in the
sample. `scripts/earnings/earnings_fly_table.py` prices every clean event at its first exit
bar and steps the wings in to the cap the way the rules do; its output is
`state/earnings/replay/2026-11-11_batch2/fly_table.json`.

### Published research
- **Option sellers are paid overnight, not during the day.** S&P 500 option returns are about
  -1% a day from close to open and +0.3% from open to close, and the same holds for stock and
  ETF options (Muravyev and Ni, 2020). A same-day short-premium trade is on the wrong side.
- **Retail overpays for options before earnings.** Retail buyers lose 5 to 9% around earnings
  on average and 10 to 14% on high expected-volatility names; implied variance runs up about
  40% more where retail buying is heaviest (de Silva, Smith and So, 2025). The seller of that
  premium is on the right side. Implied moves have averaged about 85% realized over implied,
  but the sign flips in some seasons (ORATS).
- **Same-day options are a cost game.** Retail loses on them and about 60% of the loss is
  transaction cost (Beckmeyer, Branger and Gayda, 2023).
- **Selling index premium has paid over decades**, with deep drawdowns in selloffs: the Cboe
  PutWrite index returned about 9.4% a year from 1986 to 2023 against 9.9% for the S&P 500,
  with a third less volatility.
- **Costs decide it at this size.** Every one of these premiums is a few percent of the option
  price. Eight single-leg orders that cross a spread can eat all of it.

### What follows
1. The earnings line sits where both our replay and the research find a premium. It is the core.
2. The same-day line has no edge on our data and none in the research. It stays a time-boxed
   probe and is not widened.
3. The overnight line is the right idea on paper and unproven on 25 nights. It needs a bigger
   test before a dollar goes on it.
4. The per-name cap is part of the edge, not only a risk rule. A fly with no cap keeps
   nothing, because one bad report in a hundred takes it all. With the cap the same trades
   keep $5 to $9.
5. On the earnings line the whole margin is a gross edge of about 9% of the credit against a
   cost of 6 to 7%. One point of cost is about $4 a fly. Execution is worth as much as any
   selection rule found so far.

## 3. The lines

### A. Earnings premium (core, live)
- Sell an iron fly the day before the report, buy it back the next morning. Rules:
  `RULES_CHANGELOG.md` v1.1 to v1.14, gate in code.
- Size: about 20% of the account a name, total risk never above the account.
- Being hardened, in this order:
  1. **Cost.** Measured on every closed trade as a share of its credit (`live-metrics`,
     `round_trip_cost`). Target 5% or less: penny-wide names first, patient limits walked one
     tick at a time, one multi-leg attempt a day until Robinhood allows it.
  2. **The cap.** It is what holds the tail. Brad raised it from $350 to $600 on 2026-11-17
     (rules v1.16): that morning every priced name was over $350 at its narrowest fly. The
     replay supports caps up to $500 ($9 a fly) and has a single event beyond that, the
     sample's largest loss. Names with a wide market stay at $350. Reviewed after 10 trades
     above $350 or on 2026-12-18 (P056).
  3. **Sample.** Replay every week's reports the following Saturday, so the 103 events become
     300 or more by year end and the bands can be judged. Every table says which events each
     row holds.
  4. **Width.** Inside the $350 cap, aiming the wings at 2x the straddle kept $10 a fly
     against $7.5 for 1.5x. The rule today aims at 1.5x (v1.13); whether to aim wider where
     the cap and the single-leg exit check allow is decided at its review (by 2026-11-27).
  5. **Exit.** The 06:36 PT exit stays: on the same events half an hour of waiting made no
     real difference, and less time in the trade is less risk.
  6. **Projection.** A range before every report, scored the next morning, constants refit by
     written rules (`REFLECTION.md`).
- Grows when: 30 closed live flies average at least +$8 after costs, or the replay passes 300
  events with the traded band above +$10 a fly and 2 standard errors.
- Shrinks when: the account breaker fires, or 20 closed live flies average under -$15, or the
  round-trip cost of 10 closed earnings flies averages above 9% of the credit (the line is
  then trading at breakeven: half size until the cost is fixed).

### B. Same-day fly (probe, time-boxed)
- One IWM fly a day, one contract, 07:30 to 11:00 PT (`INTRADAY.md`, rules v1.15.1).
- It is there for real fills and the first same-day round trip, at an expected cost of about
  $1 to $3 a trade. It ends after 20 probes or on 2026-12-18. Review after 10.
- No other name is admitted: none passed the 90-day test.
- It restarts at size only for a filter that shows +$10 a fly after costs with a per-day t of 2
  on at least 60 sessions it was not found in.

### C. Overnight fly (research only)
- Hypothesis: a next-day-expiry fly sold near the close and bought back by 07:00 PT earns the
  overnight premium the research describes.
- First read (SPY, 25 nights): nothing after costs. Quiet nights paid +$28, gap nights cost $54.
- Next test, written before the data: 64 nights each for SPY, QQQ and IWM, buy-back at 07:00
  PT. It goes to paper only with a mean of at least +$10 a fly after costs and a per-night t of
  2. Otherwise it is dropped.

### D. Not started
- Monthly index premium (put spreads or condors, 30 to 45 days). The research supports it. It
  cannot be tested here: Robinhood's option history older than three months has no usable
  intraday prices except on expiry day.

## 4. What would speed this up most
**Deeper price history.** Everything above was tested on 6 to 13 weeks, one falling market.
With several years of option prices the earnings line could be checked on thousands of events
and the overnight line on hundreds of nights, in an evening. That means a paid data feed (about
$30 to $100 a month). It is the owner's spend to decide. Without it the sample grows by about
40 events and 5 nights a week.

## 5. How anything gets real money
1. A written reason it should work, from the research or from our own data.
2. A replay with costs in, sized so a real edge would show.
3. A check on sessions the idea was not found in.
4. Paper with real quotes.
5. A pilot at one contract with a loss budget sized from the trade's own noise.
6. More size only after a mean of at least +$10 a trade after costs and 2 standard errors on 60
   or more independent days.
A line that fails a step is dropped or parked, in writing.

## 6. Limits that do not move without the owner's words
The account ending 3413 only. Never TSLA. Defined risk only. Limit orders only. Total risk no
larger than the account. No money in or out.

## 7. Costs
- Measure them: `PYTHONPATH=src python3 -m vantage_trader.earnings live-metrics` gives
  `round_trip_cost`, the cost against mid of each closed trade as a share of its entry credit.
  The earnings replay assumes 7% and breaks even at about 9%.
- Count costs in every test, at what the paper desk actually quoted.
- Prefer penny-wide contracts. A spread above 3% of the straddle is a no for a day trade.
- One multi-leg attempt on the first trade of each day; legs otherwise.
- Never widen a universe to "get more trades". More trades of a zero edge is more cost.

## 8. What to expect
- The best single estimate for the fly as the rules trade it is +$7.5 after costs (101
  replayed reports). Its standard error is $10, so the true number may be zero.
- If it is true and 8 to 12 flies a week fit, that is roughly $60 to $90 a week on this
  account. One fly swings about $100, so a ten-fly week swings about $300 either way. Most
  single weeks will say nothing about the edge.
- Each point of cost saved is worth about $4 a fly, $30 to $45 a week at that pace. At a 5%
  cost the same flies keep $15.
- That "if" is not settled. The live record is five trades and this season realized moves have
  run above implied.
- Nothing here is fast money. The firms that make it with algorithms sell speed and scale. A
  small account's edge is patience, no market impact and never paying for a trade that has not
  earned its place.

## 9. The week
- Mon to Fri: exits 06:36, probe 07:27 to 10:57, scans, entry sweep 11:46, reflection 13:12.
- Friday: scorecard, multi-leg check, spread scan of the whole same-day universe.
- Saturday: replay the week's earnings reports; the next research test in the queue.
- Research queue: (1) overnight test at 64 nights x 3 names; (2) the week's earnings replay;
  (3) the 10-probe review; (4) the data-feed decision; (5) the exit-priced filter (P070): on the
  earnings replay, flies whose average payoff at the planned exit, after the legging cost, is at or
  under zero against the rest (FRO and PDD passed the edge ratio with that average near zero).

## Sources
- Muravyev and Ni, "Why do option returns change sign from day to night?", Journal of Financial
  Economics 136 (2020): https://econpapers.repec.org/RePEc:eee:jfinec:v:136:y:2020:i:1:p:219-238
- de Silva, Smith and So, "Losing is Optional: Retail Option Trading and Expected Announcement
  Volatility": https://www.gsb.stanford.edu/faculty-research/publications/losing-optional-retail-option-trading-expected-announcement
- Beckmeyer, Branger and Gayda, "Retail Traders Love 0DTE Options... But Should They?", summary:
  https://www.cxoadvisory.com/individual-investing/retail-0dte-option-trader-performance
- Cboe, cash-secured put writing and the PUT index:
  https://www.cboe.com/insights/posts/generating-income-and-managing-risk-cash-secured-put-writing-in-a-low-equity-return-environment
- ORATS, earnings straddles this season: https://orats.com/blog/earnings-straddles-strong-season-2026
- Straddle returns and the historical against the implied earnings move (MDPI, Journal of Risk
  and Financial Management): https://mdpi.com/1911-8074/16/5/270
