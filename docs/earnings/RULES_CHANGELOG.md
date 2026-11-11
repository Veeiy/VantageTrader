# Live rule changelog

The scheduled head-agent check-ins trade by these rules. The engine's HARD_CAPS
are still at v1 and get updated in the next engine pass (together with the
early-assignment fix) before the engine trades on its own.

## v1.1 (2026-11-05)

Requested by Brad after two no-trade days: "don't be as strict / slight threshold roll back".

### Loosened (fill quality and coverage)
- ATM bid-ask spread: max 12% -> **25% of mid**. A trade whose spread is between
  12% and 25% is capped at **$350 max loss**. Unchanged: never accept less than
  92% of the mid credit, and keep the $50 exit-slippage reserve.
- Regime guard: trips when the 20-session average absolute daily move is
  **>= 1.25x** the historical average earnings move (was 1.0x).
- Positions: up to **2 open at once**, total max loss <= $650, different sectors.
- Scan breadth: about 60-80 names a day (3-4 vol-analyst agents) instead of about 40.

### Kept, with this week's evidence
- Intraday move <= 5% (5-7% only on a sector move with no stock-specific news):
  ARM was skipped Wed at -5.5%; it fell to about $173 by the Thursday 06:45 exit,
  on the fly's $172.50 lower wing (about -$500 avoided, estimate).
- Edge ratio <= 0.85: QCOM (edge 1.03) moved -9.4% after earnings; APP (no fit)
  moved +31%. Both would have been near max loss.
- Defined risk only, $650 total cap, TSLA blocked, stock-specific bombshell veto,
  price >= $10.
- Clarified 2026-11-09 (not new, left out of this list by mistake): the macro veto in
  `AGENTS.md` still applies. No entries when a tier-1 release (FOMC decision, CPI,
  nonfarm payrolls) lands between today's entry and the next 06:45 PT exit, when
  |SPY today| >= 2%, when VIX >= 30 or is up >= 15% today, or after a market-wide halt.
  The circuit breaker (account value < $400, 2 max losses in a row, 3 losses in a row)
  also stays.

### What v1.1 would have done this week (rough estimates)
- Wed: ALB iron fly (spread 15%, edge 0.66, max loss about $330). ALB rose about
  3.5% after its report: small win, roughly +$50 to +$120.
- Thu: WYNN iron fly 72/79/86 (spread 24.5%, $3.64 mid credit, $336 max loss).
  Result pending its Thursday after-close report.

## Scorecard: week of 2026-11-02 (no live trades)

Prices: Thursday 12:00 PT spot; Thursday close; Friday 06:46 PT. P/L figures are
estimates for one iron fly centered at the strike nearest the entry-time spot.

| Name | Skip rule | Post-report move | Would-be fly result | Rule verdict |
|---|---|---|---|---|
| ARM (Wed) | intraday -5.5% | ~$173 at Thu 06:45 vs 192.5 body | about -$500 (near max loss) | saved |
| QCOM (Wed) | no edge (1.03) | -9.4% | near max loss | saved |
| APP (Wed) | too large for account | +31% | max loss | saved |
| ALB (Wed) | would pass v1.1 | +3.5% | about +$50 to +$120 | missed small win |
| WYNN (Thu) | spread 24.5% | +2.8% (inside 75.36/82.64) | about +$75 at mid, -$65 at natural | neutral |
| VST (Thu, Fri BMO) | regime guard | +7.5% vs 2.11% hist avg | about -$50 to -$150 | saved |
| IREN (Thu) | intraday -13.6% | +22.2% | max loss (~-$340 at 6 contracts) | saved |
| NET (Thu) | intraday -9.4% | +11.9% | near max loss | saved |

Takeaways: the intraday-move rule and the regime guard avoided roughly $1,400 of
would-be losses; the missed upside was small (ALB, possibly WYNN). Long straddles
would not have helped either: IREN and NET roughly matched or undershot their
implied moves from entry time. Account value went from $750 to $650 on 11/05 from
a $100 transfer to checking, not from trading; the risk budget now scales with
buying power: min($650, 0.93 x BP) minus the $50 exit reserve.

## Risk cap decision (2026-11-10)

Brad offered to add up to $1,900 and said the cap can go up "if it makes sense". Decision
(his call was delegated to the head agent): **the $650 total max-loss cap stays for now.**

- No live fills yet; only paper results (week of 11/02 and 11/09).
- A bigger balance does not raise size. It makes the same $650 about 30% of a $2,150
  account instead of about 68% of a $950 account, so one max-loss night no longer trips
  the $400 circuit breaker.
- Step-up plan, each step only with Brad's yes at a Friday scorecard:
  1. After 5 closed live trades with net P/L >= 0 and clean execution (no missed exit,
     no unplanned assignment): cap -> $1,000.
  2. After 10 closed live trades with positive net P/L: cap -> 30% of account value.
- Step down: unchanged circuit breaker (2 max losses in a row, 3 losses in a row,
  account value < $400).

## v1.2 (2026-11-10): non-earnings trades and active management

Brad, after funding the account to $1,250: "Its ok to place non earnings trades. Just
continuously monitor and take profit when you see fit or cut when as well."

### Added: non-earnings premium-selling trades (head agent's discretion)
- Allowed when a liquid name's options are rich for a reason we can name:
  1. Screen: IV rank >= 0.8 and 30-day IV >= 1.15x the 10-day realized volatility,
     average options volume >= 15,000 a day, price >= $10.
  2. A news check names the driver and its dates (ruling, vote, FDA date, deadline).
  3. Defined risk only (iron fly or iron condor), ATM bid-ask <= 25% of mid.
- At most 1 non-earnings position at a time, risking at most $200 of the cap.
- Open positions: up to 3 in total (2 earnings + 1 non-earnings).
- Unchanged hard limits: MCP account only, limit orders only, never TSLA, total max
  loss across ALL open positions <= $650 (shared cap), circuit breaker, flat by
  11:00 PT on expiration day.
- Exit reserve: $50 per contract for earnings flies (unchanged). For flies with wings
  of $1.50 or less: $10 per contract, and never pay more than the wing width to close.

### Added: active management (all positions)
- Monitoring: hourly check-ins from 07:15 to 12:15 PT on market days while a position
  is open, on top of the 06:45, 09:45, 11:46 and 12:17 check-ins. This is not
  tick-by-tick; the wings cover the gaps.
- Take profit: close at >= 50% of max profit, or once the driver has passed and the
  premium has deflated, or earlier when the remaining upside is small next to the risk.
- Cut: close when the stock holds beyond a breakeven for 30 minutes, when the mark shows
  a loss >= 60% of max loss with more than a day left, or when the thesis breaks.
- Earnings flies: still closed the morning after the report. The order may be worked
  through the morning; never held past that day's close.
- Every entry, adjustment and exit goes in `state/earnings/journal.jsonl` with the
  reason, and open positions live in `state/earnings/positions.json`.

## v1.2.1 (2026-11-10): execution by single-leg orders (legging)

Robinhood rejects every agent-placed multi-leg order ("requires the customer to approve
agent-placed trades, and a multi-leg strategy cannot be sent for approval yet"), even with
`human_must_approve_trades=false`. Single-leg orders are accepted with no approval, so all
entries and exits are built leg by leg until multi-leg orders work again. Retry one
multi-leg order once a week (Friday) to see whether the block is gone.

### Entry (iron fly)
1. Buy both wings first (single-leg limit orders, start at mid, step up a penny at a time).
2. Check `review_option_order` for the first short leg: collateral must equal the spread
   width (wing held), with no alert. If it shows a cash-secured or naked amount, stop.
3. Sell one short side, then the other. With one side on, the other side should need $0
   extra collateral (Robinhood recognizes the iron fly). Confirm in the review.
4. Never leave a short leg on without its wing. Finish both short sides in one sitting: a
   single side on its own is a directional spread with a larger max loss than the fly.
5. Net credit floor is unchanged: sum of fills >= max(natural, 0.92 x mid) of the fly.
   Work out the minimum price for the last leg from the fills so far before sending it.
6. To change a working order: cancel it, confirm `cancelled` with zero fills, then place
   the new one with a new ref_id (there is no replace tool in this session).
7. When the broker rejects an order type, test the alternative with the cheapest possible
   leg before committing size (the $4 put on 11/10).

### Exit
1. Buy to close the short legs first (single-leg limits at mid, walk toward the ask).
   Start with the short leg that is in the money or closest to it.
2. Only after a short leg is flat, sell its wing (or let a worthless wing expire when its
   bid is zero; never sell a wing while its short leg is still open).
3. The price caps are unchanged: total cost to close (short buybacks minus wing sales)
   never above the wing width (+$0.50 only for earnings flies with wings over $1.50).

### Proven on 2026-11-10
- RGTI 12P x2 short: review collateral $2,400 with no wing, $600 with the 9P wing held.
- PCG fly x4: put side on = $400 collateral; call side review then showed $0 extra.
- PCG fills, all at or near mid within seconds: 12P 0.11, 14C 0.30, 13P 0.43, 13C 0.65.

## v1.3 (2026-11-10): data phase, more names at smaller size

Brad, 11:45 PT: "Make sure you enter/exit atleast a few. We need to start getting data and
training this model off of live metrics."

More live round trips come from more names, not from more risk. The $650 cap stays.

### Sizing while fewer than 10 live trades are closed
- **1 contract per earnings name**, up to 2 earnings names a day (different sectors), plus
  at most 1 non-earnings position. A third earnings name only if the total max loss plus
  reserves still fits $650.
- If the cap is full and a new name passes every rule, the head agent may trim an existing
  position to 1 contract to make room (done on 11/10: RGTI 2 -> 1 for FLY, cost $10.32).
- A name must still pass every v1.1/v1.2 rule. No rule is waived to reach a trade count.
- Clarified: the cap is min($650, 0.93 x account value). It used to say buying power, which
  already drops by the collateral of open positions and would count them twice.
- Every passing name that is not traded still gets a paper entry (mid and natural).

### Exits
- Earnings flies: closed the morning after the report, as before.
- Non-earnings: take profit at 50% of max profit, cut per v1.2, and do not let a position
  sit past its plan date. A closed trade is a data point; an open one is not.

### What gets recorded (see `docs/earnings/LIVE_METRICS.md`)
- `state/earnings/live_metrics.jsonl`: one `entry` record per trade (signal numbers, fill
  quality, risk) and one `exit` record (move, P/L, exit slippage, rule verdicts).
- Journal exits must carry `pnl`, `realized_move` and `max_loss` so
  `vantage_trader.earnings.calibrate` can use them. A partial close is a `heal` event with
  `as_event: "qty_adjust"`, never `exit_filled` (that would pair with the entry).
- Threshold changes still need 8 closed trades (`calibrate_min_trades`) and Brad's yes at
  a Friday scorecard. Until then the numbers are reported, not acted on.

## Daily reflection loop (2026-11-10)

Brad: "Lets setup a self reflection learning loop after each trading day." Procedure in
`docs/earnings/REFLECTION.md`; scheduled task "Daily reflection" at 14:12 PT, Mon-Fri.
The loop can change how the rules are carried out (execution, process and data lessons in
`state/earnings/lessons.jsonl`). It cannot change a rule or a risk limit: those stay
hypotheses until Brad approves them, and each approval is recorded in this file.

## Owner decision: NVDA is tradable (2026-11-10)

Brad, asked whether to trade or skip NVDA's 11/17 report with a board investigation open:
"We can trade nvdia. Probably some good opportunities with the higher iv."

- The stock-specific-news veto is waived for NVDA for the board investigation announced
  2026-11-08 and the House briefing request (proposed for 11/18). Both are public and in
  the option prices.
- Every other gate still applies: edge ratio, regime guard, intraday move, spread, macro
  veto, the $650 cap, 1 contract (v1.3).
- A new development of a different kind (the CEO stepping aside, a restatement, charges,
  an export or regulatory action) is a new event: check with Brad before trading.
- Earnings trade: enter Tue 11/17 near the close, exit Wed 11/18 at the 06:45 PT check-in,
  before the proposed briefing can produce headlines.
- A pre-earnings NVDA premium sale is a non-earnings trade under v1.2: one such position
  at a time (PCG holds the slot as of 11/10) and at most $200 at risk.

## v1.4 (2026-11-11): no daily limit on the number of trades

Brad, 2026-11-11 06:08 PT: "Rule should be the ability to exit and enter trades. No limits
per day for trades."

### Changed
- There is no limit on the number of trades per day or on the number of open positions.
  This replaces "up to 2 earnings names a day" and "3 open positions in total" (v1.2,
  v1.3) and "one non-earnings position at a time" (v1.2).
- Every name that passes ALL the rules is entered, lowest edge ratio first (lesson L012),
  for as long as the total risk budget allows.
- The same applies to the backup trader (P012): it may exit and enter trades.

### Unchanged (the agent's reading of the instruction; Brad to correct if he meant more)
- Total risk cap: max loss across all open positions plus exit reserves at or under
  min($650, 0.93 x account value). This is now the only limit on how many trades fit.
- Every entry gate (edge ratio, regime guard, intraday move, spread, news check, macro
  veto, price), defined risk only, limit orders only, never TSLA, the circuit breaker.
- 1 contract per earnings name during the data phase (v1.3). A non-earnings trade still
  risks $200 at most.
- No two earnings names from the same sector on the same day (they move together).
- Nothing is entered to reach a trade count.

### Why the gates matter more now (replay of 2026-11-10)
Selling every fly made about $6 a trade before costs and lost money after them. Only
names at edge ratio 0.70 or under paid. More trades a day is fine; weaker trades are not.
