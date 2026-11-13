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

## Risk cap decision (2026-11-11): $1,000

Brad, 2026-11-11 06:12 PT: "Also increase the spending limit since we have 1200 in there
now. Lets say 1k limit."

- Total risk cap: max loss across all open positions plus exit reserves at or under
  **min($1,000, 0.93 x account value)**. It was min($650, 0.93 x account value). This
  replaces the $650 figure everywhere in this file, v1.4 included.
- With the account near $1,180 the $1,000 figure binds; under about $1,075 the 0.93
  factor does.
- Unchanged: 1 contract per earnings name (data phase), $350 max loss when the ATM
  spread is between 12% and 25%, $200 for a non-earnings trade, every entry gate, the
  circuit breaker (account under $400, 2 max losses in a row, 3 losses in a row).
- What it means: in the worst case, every position at max loss on the same morning, about
  83% of the account is gone. A realistic bad morning with five or six flies open is a
  loss of $300 to $500.
- Engine note: `config/earnings.yaml` still carries the old hard cap of $700 per
  position in code. It does not bind at 1 contract; it is raised with P004.

## Long-straddle side switched off (2026-11-11, P010)

Brad, 2026-11-11 06:14 PT: "yes p010 and p009".

- No long straddles. The rule "buy an ATM straddle when the edge ratio is 1.25 or more
  and the ATM spread is 12% or less" is set aside.
- Why: in the replay of 2026-11-10, 8 names had an edge ratio of 1.25 or more. The long
  straddle lost on 6 of them, -$755 in total before costs (hypothesis H009, 6 for, 2
  against).
- Names with an edge ratio of 1.25 or more are still scored on paper as long straddles.
  If the next 8 win at least 2 to 1, it comes back to Brad.
- Selling rules are unchanged.
- Engine note: `buy_min_ratio` in `config/earnings.yaml` still marks such names "buy" in
  the dry score. Treat "buy" as "no trade" until the config is updated with P004.

## v1.5 (2026-11-11): entries at any check-in, not only 11:46

Brad, 2026-11-11 06:25 PT: "Doesn't have to just be at 11:46 for entering trades. Whenever
a trade qualifies, it can execute."

### Changed
- A trade may be entered at any check-in on its entry day (the morning scan, the midday
  re-check, the 11:46 run), as soon as it passes every rule and has a clean news check.
  Non-earnings trades were already free of a time window.
- How the agent uses this (its judgment on timing, not a new gate):
  - Edge ratio 0.70 or under: enter as soon as it qualifies. That is where the replay
    found the edge, so there is nothing to wait for.
  - Edge ratio between 0.70 and 0.85: wait for the 11:46 run, when the whole field is
    known, so the risk budget goes to the best names first (lesson L012).
- The 11:46 run is now the final sweep of the day: it skips names already entered and
  decides every name that is left.

### Unchanged
- Every entry rule, 1 contract per name, the $1,000 total risk cap, no long straddles,
  single-leg execution, the 12:50 PT cancel deadline (nothing new is opened after 12:35).
- The body strike is fixed at the moment the short legs are sold (lesson L001).

### The trade-off, stated once
An earnings fly earns its money overnight, on the IV crush. Entering hours earlier adds
ordinary daytime movement before the report and commits budget before later names are
known. It also gives more time to work the legs. Early entry is roughly neutral for a
strong name and not worth it for a marginal one, which is why the two are split above.


### Timing layer removed (2026-11-11 08:00 PT, P020, agent's own layer)
The agent had added "0.70 or under goes early, 0.70 to 0.85 waits for 11:46". Replay batch 2
(103 clean events combined) shows nothing special at 0.70: 15 wins of 25 at +$4.50 a fly
against 46 of 78 at +$17. The layer is dropped. Any name that passes ALL the entry rules
(edge ratio at or under 0.85) with a clean news check may be entered at any check-in on its
entry day, as Brad said: "Whenever a trade qualifies, it can execute".

## Replay batch 2 (2026-11-11): what it says about the rules
`state/earnings/replay/2026-11-11_batch2/FINDINGS.md`. No rule changes without Brad:
- P018 (owner): wings at about 1.5x the straddle, max loss per trade $350 or less.
- P019 (owner): the 0.85 edge gate does not pick winners; keep as a throttle or drop.


## Delegation (2026-11-11 08:13 PT): the agent decides rule iterations
Brad: "for these iterations like p018 and p019, youre good to push. but i want you to push
these reccommendations and changes if you see fit. you have owners permission to automate."

What it changes: proposals of kind `rule`, `risk` and `cost` no longer wait for his yes. The
agent decides them when it sees fit, logs the decision as "agent, under Brad's standing
delegation of 2026-11-11" with his words, implements, and tells him the same day under
"Changed today". He can reverse any of them with one word.

The agent's reading of the scope (its own interpretation; Brad corrects it if it is wrong):
- **Covered:** iterations of the strategy's parameters and rules, like P018 (wing width) and
  P019 (entry filter): thresholds, gates, structure, timing, exits, paper tests.
- **Still only on his words:** the account (MCP only), never TSLA, defined risk only, limit
  orders only, the total risk cap min($1,000, 0.93 x account value), a max loss per name
  above $350, a new live strategy line, anything that moves money in or out. (The item
  "more than 1 contract per earnings name before 10 live trades are closed" stood here until
  08:25 PT the same day, when he lifted it: see v1.7.)
- **Standard the agent holds itself to:** a written proposal with numbers and a measure; at
  least 50 replay events or 8 live observations behind a rule change; one change per rule at
  a time; a review date; roll back what does not work.

## v1.6 (2026-11-11): wider wings (P018, decided under the delegation)
- Wings at the listed strikes nearest **1.5x the entry straddle** on each side (was about
  1x), at least one strike step from the body.
- If the max loss at the credit floor would exceed $350, step the wings in one strike at a
  time until it fits. 1 contract per name and the $1,000 total cap are unchanged.
- Evidence (combined replay, 103 clean events, 10:00 ET exit, after a 7% cost): 1x wings
  -$1.5 a fly, 1.5x +$8.7 (standard error $11.9), 2x +$16.9 but an average max loss of $486.
  With the $350 cap: 69 events, +$10.5 a fly. Not statistically solid; the direction is
  consistent across both batches.
- Applies from the next entry. LUNR (opened 07:57 PT with 1.5-wide wings, about 0.9x) stays
  as it is: rolling its wings would cost more than the expected gain.
- Review after 10 live trades with the new wings, or at once if a trade's max loss comes out
  above $350.

### Edge gate kept for now (P019, decided under the delegation)
The 0.85 edge gate does not pick winners in the replay, but dropping it would about triple
nightly exposure on a net edge that is not proven. It stays as a throttle until 2026-11-25.
A selector test on the full replay set (price band, implied move level, report timing,
regime ratio) runs at the Friday scorecard; the gate is replaced when one of them holds up.

### Same-day flies stay on paper (P017, decided under the delegation)
Brad asked for day trades on theta and IV crush. The 2026-11-11 market-wide scan found no
edge (`state/earnings/daytrade/2026-11-11/FINDINGS.md`), and a new live strategy line is
outside the delegation. So: one SPY and one IWM same-day iron fly are recorded on paper every
session at the 07:15 run, marked at every hourly run, final mark at 12:15 PT. After 10
sessions the result after costs goes to Brad with a go or no-go.

## v1.7 (2026-11-11 08:25 PT): contracts by risk, and scaling in
Brad: "you can open more contracts for one ticker if it meets the criteria. or want to scale
in as well."

This lifts the v1.3 data-phase limit (1 contract per earnings name until 10 live trades are
closed) on his words. How the room is used is the agent's design under the delegation; he
changes any number below with one word.

### Sizing: by risk, not by count
- Every earnings name gets a **target max loss of 12% of account value** at the credit floor
  (about $159 on $1,327), never above the $350 per-name limit. New contracts = (target minus
  the max loss already held on the name) / max loss of one contract, rounded to the nearest
  whole number. It is a target, not a ceiling: a name lands a little under or over it.
- One contract is always allowed on a new name whose max loss fits $350, as before.
- Ceilings, all rounded down: $350 of max loss per name, 10 contracts per name, and the
  total cap min($1,000, 0.93 x account value) with a $50 reserve per earnings contract. On
  a busy day the budget shrinks the later names.
- Why a target and not "as many as fit". The replay (103 clean events, 10:00 ET exit, after
  costs) puts the 1.5x fly at about +3% to +6% of its max loss per trade, with a standard
  error as large as the average. Per dollar of max loss the results spread about 0.25 to
  0.45. On those numbers the size that grows the account fastest is somewhere between 18%
  and 50% of the account per name; half of that or less is the usual discount for an edge
  that is not proven, and a few bad nights in a row must not end the test. 12% is in the low
  part of that range. More contracts multiply the result and the swings alike. They add no
  edge.
- Why not more contracts on "better" setups. In the replay the edge ratio does not pick
  winners (rank correlation 0.00; at or under 0.70: 15 wins of 25, the rest 46 of 78). There
  is no measured basis for betting more on one passing name than on another, so every
  passing name carries about the same risk. What several contracts fix is the cheap name:
  LUNR at $44 of max loss was a quarter of RGTI at $172.

### Scaling in
- Before 11:30 PT ("early") a name carries at most **half its target**, rounded down (one
  contract is still allowed). An early fly can drift off its body strike before the report.
  The part entered in the final window cannot.
- From 11:30 PT ("final") an open name is completed to its target and a new name goes in at
  full size. Nothing new after 12:35 PT, as before.
- An add is a new entry decision: fresh quotes, the gate again, every rule passing. Two
  extra conditions: the same body strike and expiry as the open tranche, and spot within
  0.25 x the body straddle of that strike. If the stock has left the strike there is no add
  and no second fly at another strike. The open tranche is kept as it is.
- The wings of an add follow the wing rule in force (v1.6), so they may differ from the
  first tranche's.
- The one-name-per-sector rule does not apply to an add.
- Non-earnings flies (v1.2): an add at a later check-in or on a later day is allowed while
  the v1.2 entry conditions still hold, the position is not at or past its cut level, and
  the name stays at or under $200 of max loss.

### Execution with several contracts
- Each order carries the tranche's quantity. Wings first, then the shorts, for the same
  quantity. At no moment more shorts than wings on either side.
- A partly filled wing order sets the tranche: cancel the rest and sell only that many shorts.
- A partly filled short order is repriced under the credit floor rule. At 12:50 PT cancel
  what is unfilled, buy back the surplus shorts of the fuller side so both sides match, and
  sell surplus wings if they have a bid (else list them under `leftover_long_wings`).
- Exit: buy back every short first (ITM side first), then sell the wings.

### Records
- Journal: an add is an `entry_filled` with `"add": true`. It joins the open trade: one name
  is one trade, so its loss counts once in the circuit breaker.
- `positions.json`: one position per name with `quantity`, the average `credit`, the total
  `max_loss_usd` and a `tranches` list (time, quantity, strikes, credit, max loss, order
  ids). Breakevens are the body plus and minus the average credit; move the two price
  alerts when they change.
- `live_metrics.jsonl`: an `adjust` record with `tag: "add"` (docs/earnings/LIVE_METRICS.md).

### In code
`sizing.plan`, the gate checks `add_centered` and `name_risk`, the candidate fields `held`
and `phase` (docs/earnings/GATE.md). `data_phase_trades` is gone. `max_quantity` 10 (hard
cap), `name_risk_frac` 0.12 (hard cap 0.15), `name_risk_cap` 350 (hard cap). The gate now
blocks a max loss above $350 per name at any spread, which v1.6 already required.

### Review
After 10 closed trades under v1.7: early against final tranche credits on the same name,
and the result per dollar of risk against the 1-contract trades. The agent may move the
target between 0 and 15% of the account under the delegation. More than $350 on one name
needs Brad.

## v1.8 (2026-11-11 11:00 PT): a bigger target per name
Brad, with $266 of the $1,000 cap in use: "we have a ton of buying power. start putting the money to work."

### Changed
- The target max loss per earnings name goes from 12% to **20% of account value** (about
  $267 on $1,336). Everything else in v1.7 stands: contracts rounded to the nearest whole
  number, at most half the target before 11:30 PT, the add checks, and the ceilings ($350
  per name, 10 contracts, the $1,000 total cap with reserves).
- In code: `name_risk_frac` 0.20, hard cap 0.27 (the $350 name cap binds before it).

### Unchanged
- Every gate. A name that fails a rule is still not traded: more size goes only to names
  that pass. Today that is LUNR (earnings) and PCG (non-earnings, limit $200 per name).
- The non-earnings screen (v1.2). NVDA did not pass it on 2026-11-11; the NVDA fly opened
  that day is an owner-directed trade, tagged `owner_directed` in the journal and the live
  metrics so it can be scored apart from the model's own trades.

### What it means, said once
- Two earnings names at the new target plus reserves use about $750 of the $1,000 cap. A
  night on which both hit their max loss costs about $530, 40% of the account, and two max
  losses in a row trip the circuit breaker.
- The agent's own read has not changed: the replay edge is about +3% to +6% of max loss per
  trade with an error bar as large, and this size is near the growth-optimal bet only if
  that edge is real. The size is the owner's call inside his limits. He reverses it with
  one word ("back to 12%").

### Review
Same as v1.7: after 10 closed trades, result per dollar of max loss; and at once if the
account falls under $1,000, where the agent will ask Brad whether to keep 20%.

### Paper test widened (2026-11-11 12:19 PT)
Brad: "lets add meta, nvdia and some of those other high liquidity stocks to the paper testing"

- From 2026-11-12 the same-day paper flies cover 10 liquid names: SPY, QQQ, IWM, NVDA, META,
  AAPL, AMZN, MSFT, AMD and IBIT (never TSLA). A name is recorded only on days it has a
  same-day expiry: the three funds every day, the stocks on Mondays, Wednesdays and Fridays.
- Same design as before: opened at the 07:15 PT run, take-profit check at 10:15 PT (close
  cost at or under half the credit), result at 12:15 PT. Still paper only (P017).
- A read-only paper-desk agent does the quoting; the head only imports its file
  (`paper-import`). Cost: about 150,000 tokens a day.
- Day 1 (2026-11-11, SPY and IWM only): -$111 at mid, -$120 at natural. META, recorded as
  an extra, made +$132 at mid and +$73 at natural.
- With about 8 flies a day instead of 2, the 10-session test holds roughly 80 results
  instead of 20.


## v1.2.2 (2026-11-12): a position at its max loss is held, not legged out
Decided by the agent under Brad's standing delegation of 2026-11-11 ("you have owners
permission to automate"). Brad was told the same morning. He reverses it with one word.

### What happened
NVDA's CEO resigned overnight and the stock opened 13% lower, 19 points under the put wing of
the 170/175/180 fly. The cut rule (v1.2) said close. Three things stood in the way:
- Robinhood refused the 4-leg closing order: "this account requires the customer to approve
  agent-placed trades, and a multi-leg strategy cannot be sent for approval yet".
- Buying back the short 175 put alone cost about $1,545. Buying power was $994.
- Legging would have left the long 170 put (about $1,100, $80 per $1 in the stock) alone
  between two orders, in a stock moving $1 a minute.
The fly cost 4.65 to close against a width of 5.00: closing saved about $35 at best.

### Changed
- A position whose cost to close is **at or above 90% of its wing width** is at its max loss.
  The cut rule no longer forces a single-leg close of it.
- The agent tries ONE multi-leg closing order at the mid. If the broker refuses it, the
  position is held at its defined max loss and Brad is told he can close it in the app in
  one order, with the limit.
- At every check-in the agent looks for assigned shares first. Assigned shares are sold with
  a limit order and the long wing is sold right after (or exercised); the loss stays the
  max loss.
- If the stock comes back, the position's own rules in `positions.json` say when a
  single-leg close is allowed again (the short leg must cost less than the buying power).
- On expiration morning a position with both legs of the losing side in the money is left
  to expire: exercise and assignment offset, and the loss is the max loss.

### Unchanged
- Every limit. The max loss was counted in full against the $350 per name and the $1,000
  total from the start, so holding adds no risk that was not already in the budget.
- The cut rule for every position that is not yet at its max loss.

### Execution notes from the same morning (P027)
- Review every leg before the first closing order; sell a wing the moment its short leg is
  flat, at one tick under its mid.
- A wide in-the-money short leg starts at its parity value, not at the quoted mid.

### One contract per name: the last traces removed (2026-11-12 08:40 PT)
Brad: "Get rid of the one contract per name rule"

- The rule itself ended on 2026-11-11 with v1.7 (his words that day: "you can open more
  contracts for one ticker if it meets the criteria. or want to scale in as well"). Since
  then the `gate` command sizes every live entry by risk: LUNR went to 3 contracts, PCG to 5.
- What was left and is now gone: the older `score` command still returned one contract per
  name. It now uses the same plan as the gate (target 20% of account value per name, up to
  10 contracts, never above $350 of max loss per name). No live instruction used it.
- Wording fixed in the engine notes and in the vol-analyst brief ("a 1-contract iron fly").
- What still limits size is risk, not a contract count: the per-name target (20% of the
  account), the $350 per name, $200 on a non-earnings name, half the target before
  11:30 PT, and the $1,000 total. The $350 and the $1,000 change only on Brad's own words.

## v1.9 (2026-11-12 10:40 PT): a fly must be closable with single-leg orders
Decided by the agent under Brad's standing delegation of 2026-11-11. It only removes trades.

### Why
- NVDA, 2026-11-12: the short 175 put cost $1,545 at the open, the buying power was $994 and
  the 4-leg closing order was refused. The fly could not be closed until the stock bounced.
- AMAT and CSCO the same day (Brad, 10:19 PT: "Those 3 stocks you listed look like good
  trades"): an ordinary earnings move would put AMAT's short leg at about $2,800 and
  CSCO's at $900 to $1,300, against about $1,040 of buying power.

### Changed
- New gate 16, `exit_feasible`. With the stock between the body and a wing, the
  in-the-money short leg costs up to the wing width. One such buyback, 1.1 x width x 100,
  must fit the buying power left after the entry (buying power - contracts x max loss at the
  credit floor). The contract count is cut to what fits; if not even one fits, the name is
  blocked (`exit_not_feasible`).
- The gate input carries `buying_power` (from get_portfolio at that moment). Without it the
  name is blocked (`buying_power_missing`).
- Exits: when the buying power does not cover all the in-the-money shorts at once, the
  position is closed one contract at a time.

### What it means
- With about $1,000 of buying power, a fly wider than about $7 does not pass. In practice
  that is stocks under roughly $60: the range of RGTI, FLY, LUNR and PCG.
- Beyond a wing the position is at its max loss and v1.2.2 applies.
- The gate stops binding the day Robinhood accepts the agent's multi-leg orders (P005) or
  the account holds more buying power.

### Not tested
- Whether Robinhood refuses a buy-to-close whose cost is above the buying power. The review
  call shows no alert for it. It is treated as refused until a live order shows otherwise.

## v1.10 (2026-11-13): a half-size tier for names just above the edge gate
Decided by the agent under Brad's standing delegation of 2026-11-11, which named P019 ("for
these iterations like p018 and p019, youre good to push"). Brad, 2026-11-12 10:19 PT, on
AMAT, CSCO and NU: "Those 3 stocks you listed look like good trades". Live from Monday
2026-11-16 (no earnings entries on a Friday).

### Why
- The Friday selector test on the full replay set (103 clean events, exit 10:00 ET):

  | Edge ratio | Short straddle won | Mean, % of the entry straddle | 1x fly after costs | 2x fly after costs |
  |---|---|---|---|---|
  | 0.85 or under (what the gate lets in) | 25 of 37 | +8.3 (se 6.1) | -$9 | -$3 |
  | 0.85 to 1.10 (blocked until today) | 22 of 26 | +20.3 (se 5.5) | +$10 | +$43 |
  | above 1.10 | 24 of 38 | +13.6 (se 5.3) | -$1 | +$21 |

  The blocked band did no worse than the band we trade. The gap (12 points, z = 1.5) is not
  proof that it is better, and it flips between the two replay batches. Price band, implied
  move level and report timing were tested the same way: none holds in both batches.
- This week's blocked names in that band, scored on real prices at the planned exit: PBR
  +$9, AMAT +$296, CSCO +$180, NU +$4 a contract, CRWV -$51. Four of five; CRWV also
  carried news flags, which block a name in any band.
- So the 0.85 line is a throttle, not a selector (P019). It kept the account out of every
  earnings name on 2026-11-12.

### Changed
- Gate 4: an edge ratio above 0.85 and up to 1.10 passes in the band `near_miss`.
- Size: a near-miss name gets half the name target (10% of account value instead of 20%)
  and half the name cap ($175 of max loss at the credit floor instead of $350).
- Every other gate applies unchanged: spread, regime, intraday move, news, macro veto,
  circuit breaker, structure, risk budget and gate 16 (the exit must be feasible).
- Config: `near_miss_max_ratio` 1.10 and `near_miss_size_frac` 0.5, both hard-capped at
  those values. Setting `near_miss_max_ratio` to 0.85 switches the tier off.
- Above 1.10 nothing changes: `no_edge`, and `long_straddle_off` from 1.25.

### What it means in dollars
- With $1,276 in the account the tier target is about $128 a name. On 2026-11-12 it would
  have entered NU x3 (max loss $118): +$12 at the 06:45 PT exit, -$12 at 07:30 PT.
- AMAT and CSCO stay blocked: both need more than $175 a contract and both fail gate 16.
  Trades of that size need multi-leg orders (P005) or more buying power.

### Review
- After 10 closed tier trades or on 2026-11-25 with P019, whichever comes first: result per
  trade after fees against the core names over the same days.
- Off at once if the tier's first five closed trades lose more than $150 in total.

## v1.11 (2026-11-13 07:53 PT): the total risk cap is the whole account
Owner decision. Brad: "I want you to be able to use the entire funds in the mcp account. I allocated funds specifically for you to trade with."

### Changed
- Total risk cap: was min($1,000, 0.93 x account value). Now the account value itself
  (`get_portfolio` total_value at the moment of the entry). Max loss plus exit reserves of
  all open positions, earnings and non-earnings, must stay inside it.
- Config: `max_loss_abs: null` (no dollar ceiling) and `max_loss_bp_frac: 1.0`. The code's
  hard cap of $1,000 is gone; the fraction is hard-capped at 1.0 (never more than the
  account: defined risk, no leverage). A dollar ceiling can be put back in the config.
- The cap follows the account: money Brad adds is usable at once, and losses shrink it.

### Not changed (each needs Brad's own words)
- Max loss per name: $350 (near-miss names $175). Non-earnings names: $200.
- Per-name target: 20% of account value (v1.8).
- Defined risk only, limit orders only, this account only, never TSLA.
- Circuit breaker: no new entries after 2 max losses or 3 losses in a row, or under $400.
- Gate 16: every new fly must leave buying power for its own single-leg exit. With the whole
  account usable this gate, not the cap, is what stops the last few hundred dollars.

### What it means today
- Account $1,275.91, at risk $224: $1,052 free instead of $776.
- At $350 a name, about four full-size names fit at once, and a morning where all of them
  hit max loss can now take the whole account instead of $1,000 of it.

### Standby
- Brad's words were relayed to the backup trader on 2026-11-13. It verified them in the
  head's transcript, accepted v1.11 and updated the cap sentence in both of its switch tasks
  (07:59 PT). The head read both tasks back at 08:14 PT: same cap in both sessions.

## v1.12 (2026-11-13 08:15 PT): non-earnings names may risk up to $400
Owner decision. Brad: "Raise the non earnings limit to 400"

### Changed
- Max loss on one non-earnings name (rules v1.2 trades such as PCG): $400, was $200.
  It is counted like every other risk: max loss at the credit floor, plus the exit reserve,
  inside the total cap (the account value, v1.11).
- Earnings names are unchanged: $350 a name, $175 for a near-miss name (v1.10).

### Unchanged for a non-earnings trade (rules v1.2)
- The screen (IV rank 0.8 or more, 30-day IV at least 1.15x the 10-day realized volatility,
  15,000 options a day, price $10 or more), a named driver with its dates, defined risk,
  an at-the-money spread of 25% or less, take profit at 50% of max profit and the cut rules.
- The exit must be feasible with single-leg orders (the gate 16 arithmetic applies to any
  fly): Brad, same message: "Dont think robinhood supports multileg trading with mcp atleast
  not yet." P005 is parked; the Friday retry of one multi-leg order stays, so the day it
  works is noticed.

### First use
- None on 2026-11-13. An add to PCG (5 contracts, max loss $174) was priced and passed over:
  about +$9 to +$17 a contract by Tuesday if nothing happens against $44 a contract if the
  special session is called over the weekend; the 13 put's market was 27% wide; the stock
  sat $0.19 above the body with heavy buying of the 14 calls.
- The backup trader's switch prompts say "max $350 per name". It opens earnings flies only,
  so that stricter number changes nothing for it.
