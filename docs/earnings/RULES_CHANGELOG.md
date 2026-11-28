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
multi-leg order once a week (Friday) to see whether the block is gone. (Since 2026-11-16, P051: once a day, on the first structure traded.)

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
  *Correction, 2026-11-16:* these are 10:00 ET numbers and leave out the events with no 10:00
  print, the largest loss among them. On every clean event at its first exit bar: 1x -$8,
  1.5x -$2, 2x +$3 with no cap; +$7.5 a fly (standard error $10) for wings aimed at 1.5x and
  stepped in to the $350 cap, +$10 aimed at 2x. The wider-wings decision stands on the capped
  numbers; the cap itself is what holds the tail (`PLAN.md` section 2).
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

## v1.13 (2026-11-13, daily reflection): a floor under the wing width (P036, decided under the delegation)
A tightening. It blocks trades and adds no risk.

### Changed
- Gate 12 (structure) also needs the narrower wing to sit at least **0.9 x the body straddle**
  from the body. A fly that fails is blocked with `wings_too_narrow`. Config
  `min_wing_over_straddle: 0.9`, a hard floor: the config may only raise it.
- Wings are still aimed at 1.5x the straddle (v1.6) and still stepped in one strike at a time
  when the max loss is above the name cap. That stepping now stops at 0.9x. A name that does
  not fit its cap or the exit check (gate 16) at 0.9x is not traded; nobody narrows it further.

### Why
- The replay priced flies with wings at 1x and at 2x the straddle. Nothing narrower was ever
  tested, and at 1x the result was already about zero at mid (edge 0.85 or under: -$9 a fly
  at 1x against -$3 at 2x, 37 events; edge 0.85 to 1.10: +$10 against +$43, 26 events).
- With single-leg exits and about $1,040 of buying power, gate 16 passes flies up to about $7
  wide. Stepping the wings in until a fly fits is the easy way around it: a $200 stock with a
  $16 straddle would pass at 7 wide, 0.44x the straddle, breakevens inside half the implied
  move. No rule stopped that. From Monday the near-miss tier ($175 a name) adds the same pull.
- Found on 2026-11-13 while pricing the Friday paper flies: BIDU's 1.5x fly (86/70) was
  stepped to 85/71 for the $350 cap, failed gate 16, and passed at 84/72 (1.09x).
- Nothing traded so far is affected: LUNR 0.94x, PCG 0.97x, BIDU paper 1.09x all pass.

### What this means for which names can be traded
- With single-leg exits the account trades flies up to about $7 wide. At 1.5x wings that is a
  straddle of about $4.70, so stocks under roughly $55 when the options price an 8.5% move.
- More names need multi-leg orders (no gate 16, cheaper exits), more buying power, or both.
  Raising the $350 name cap is Brad's call and is not proposed.

## v1.14 (2026-11-16): one prudential condition at half size, two block (P040, decided under the delegation)
Brad, 2026-11-16 12:48 PT: "no i want you to be slightly more aggressive with the trades."
The rule is the agent's design under his standing delegation of 2026-11-11, the smallest
step that answers him. He changes or reverses it with one word. Applies from the next entry.

### Why
- 2026-11-16: JD passed every numeric gate (edge ratio 0.56 to 0.60) and was skipped on one
  mild news flag, a deal that had already closed. From about 11:15 PT the macro veto stopped
  all new entries (S&P down 2.0%, VIX up 23% at 12:46 PT). Brad overrode both.
- Both checks were all or nothing. A mild objection blocked a name the same way a serious
  one does.

### The rule
- One mild prudential objection no longer blocks a trade. It halves its size. Two at once
  still block.
- The two objections are a soft news flag on the name and the soft macro band (both below).
- With one of them the name gets half its target and half its name cap ($175, not $350),
  the same mechanism as the near-miss tier (v1.10). The halves do not multiply: a near-miss
  name with one soft condition is sized at 0.5, not 0.25.
- A hard flag or a hard macro veto blocks as before. So does every other gate.

### Soft and hard: the news check
- Hard (blocks): the report date is unconfirmed; a pre-announcement or guidance change in
  the last 10 days; a pending acquisition, vote or tender; an offering or lock-up expiry
  inside the holding window; a dated legal or regulatory decision inside the holding window;
  a management change in the last 10 days; an investor or product event inside the holding
  window; a short-seller report in the last 10 days; a halt.
- Soft (the flag starts with `soft:`, for example `soft:ceconomy_acquisition_closed`):
  context that is public and already priced and has no date inside the holding window. For
  example a deal that has already closed, a sector story, an old analyst day.
- When unsure, the sentinel uses a hard flag.
- The holding window runs from the entry to the planned exit.

### Soft and hard: the macro veto
- Hard (blocks, as before): a tier-1 release (FOMC decision, CPI, nonfarm payrolls) between
  now and the next 06:45 PT exit; the S&P (SPY) up or down 3% or more today; VIX at 30 or
  more, or up 25% or more today.
- Soft (half size): SPY up or down 2% to under 3%, or VIX up 15% to under 25% with VIX
  under 30. The gate gets it as `macro_veto: "soft: <numbers>"`, for example
  `"soft: SPY -2.0%, VIX +23%"`.
- Until now the veto started at 2% on SPY and at 15% up on VIX. From those lines to the
  hard ones is now the soft band.
- A market-wide halt today still blocks (`AGENTS.md`).

### In code
- Gate 8 (`news`): a hard flag fails it with the same reason as before (`flagged:<flags>`).
  Soft flags alone pass, with a note that names them.
- Gate 9 (`macro_veto`): `true` or a plain reason string fails it as before. A string that
  starts with `soft:` passes, with the note "soft macro condition: half size (v1.14)".
- New gate 17, `prudential`: its value lists the soft conditions present (`soft_news`,
  `soft_macro`). One passes. Two fail with `two_prudential_conditions`.
- The decision record carries `prudential` (that list) and `size_factor` (1.0, or 0.5).
  `tier` is unchanged. The journal and live-metrics records of such a trade carry
  `prudential` too, so the review can find them.
- Config: `prudential_half_enabled` true, `prudential_size_factor` 0.5 and
  `max_prudential_conditions` 1. The last two are hard caps: a config cannot raise them.
- Several soft flags on one name count as one condition (`soft_news`).
- Gate 7 is unchanged: in the 5% to 7% band a soft flag still counts as stock news.
- The older `score` command is unchanged: any flag still skips a name there.

### Off switch
- Brad says "prudential off": `prudential_half_enabled` is set to false in
  `config/earnings.yaml`. Soft flags and a soft macro string then block like hard ones,
  exactly as before v1.14.

### What it means
- With $2,000 in the account a name with one soft condition may carry $175 of max loss at
  the credit floor: half the 20% target would be $200, and the halved name cap binds first.
- As in the near-miss tier, one contract is always allowed when it fits the $175. A fly that
  risks more than $87.50 a contract gets one contract, and none if it risks more than $175.
- 2026-11-16 again. JD at the 06:50 PT scan: its flag is a soft one, so 1 contract (max
  loss about $113) instead of none. At 11:47 PT VIX was up 26.8%: a hard veto under v1.14
  too. At about 12:46 PT (S&P down 2.0%, VIX up 23%) the macro band was soft: a name with no
  flag could be entered at half size, and JD, with two soft conditions, stays blocked.
- The HD fly and the JD contracts of that afternoon were owner overrides. They would still
  need one.

### Review
- On 2026-11-30 or after 10 trades entered under this rule, whichever comes first: result
  per fly after costs against the full-size flies.
- The rule goes off by itself if the first five closed trades entered under it lose more
  than $150 in total: `prudential_half_enabled` is set to false that day and Brad is told.

### Unchanged
- The owner's hard limits: this account only, defined risk only, limit orders only, never
  TSLA, the name caps ($350 for an earnings name, $175 for a near-miss name, $400 for a
  non-earnings name) and the total cap (the account value, v1.11).
- The blocklist, price, history, edge ratio, spread, regime, intraday, circuit breaker,
  sector, structure, name risk, risk budget and exit-feasibility gates, and the add rules.

### Sector rule: what "sector" means (wording only, no code)
- "No two earnings names from the same sector on the same day": sector here means the
  industry (for example apparel and footwear, internet retail, home improvement retail), not
  one of the eleven broad sectors.
- On 2026-11-16 JD and HD were both read as the same sector as AS. By industry the three
  differ, so the rule would not have stood between them.

## Delegation (2026-11-16 about 18:15 PT): the agent decides, and tells him after
Brad: "Push the day trading pilot" and "Dont need a decision on me. Remember, self healing and
strengthening the model with your own decision making".

What it changes: proposals that were waiting for his yes are decided by the agent. That now
includes the two kinds the delegation of 2026-11-11 left with him: a max loss per name above
the stated number, and a new live strategy line at pilot size. The agent logs the decision as
"agent, under Brad's standing delegation of 2026-11-16" with his words, implements, and tells
him the same day. He reverses any of them with a few words.

The agent's reading of the scope (its own interpretation; Brad corrects it if it is wrong):
- **Covered:** everything the first delegation covered, plus per-name limits inside the total
  cap, pilots of a new line at pilot size, and what a pilot must show before it grows.
- **Still only on his words (`hard_limit` in the proposals ledger; the code refuses an agent
  approval):** the account (MCP only), never TSLA, defined risk only, limit orders only, the
  total risk cap (max loss plus exit reserves no larger than the account value), anything that
  moves money in or out.
- **Standard the agent holds itself to:** the one above (a written proposal with numbers and a
  measure, evidence behind a rule change, a review date, roll back what does not work), and
  for a new line: a replay or a paper test first, the smallest size that answers the open
  question, a loss budget fixed in code, and a test written before the data that decides
  whether it grows.

Decided under it on 2026-11-16: the shape of the same-day pilot (v1.15), P041 and P044.

## v1.15 (2026-11-16): the same-day pilot goes live as probes (P017)
Brad, 2026-11-16: "Push the day trading pilot". The line is his decision. Its shape is the
agent's, under the delegation above, and it is not the shape P017 proposed on 2026-11-11.
Full text: `docs/earnings/INTRADAY.md`. Applies from Tuesday 2026-11-17.

### Why the shape changed
The replay ran the evening he said it: 90 real same-day iron flies on SPY, QQQ and IWM over 30
sessions, sold at 07:30 PT (`state/earnings/daytrade/replay/`).
- About breakeven before costs, -$2 to -$12 a fly after them, at every exit from 09:30 on.
- P017's trigger (straddle at least 1.15x the 10-session same-hours move) is not supported:
  the 1.10 to 1.25 bucket was the worst of all.
- A stop made it worse. A take profit changed nothing.
- IWM came out at breakeven after costs, with the smallest loss when wrong.

### The rule
- **One live same-day iron fly a day, one contract.** Body at the strike nearest the price,
  wings at the listed strikes nearest one body straddle away. Entry 07:25 to 07:50 PT. Flat
  by 11:00 PT, the same hour as every other position that expires that day.
- **Probe tier (on):** IWM only, max loss at most $80 (raised to $150 in v1.15.1 below). It is traded for what paper cannot
  give: real fills on single-leg orders in same-day options and a live record against the
  replay. Expected cost about $5 a trade.
- **Signal tier (off):** up to $200 of max loss on SPY, QQQ or IWM inside a premium-ratio
  band. Off until a filter passes the out-of-sample test in `INTRADAY.md`.
- **No stop and no take profit.** The wings are the stop.
- **No entry** after a move of more than 1% from the prior close, with a tier-1 release or a
  Fed decision before the time stop, or under a macro veto (hard or soft).
- **Its own breaker:** the pilot pauses at -$150 in total or after 3 losses in a row (now -$500 or 6, v1.15.1 below). P017
  said 2 in a row; at a 50% win rate that would pause it every other week for no reason.
- **Pilot trades do not count in the account's loss streaks.** P017 said they would. A
  one-contract pilot must not be able to halt the main line. The account breaker still
  stops the pilot.
- **Time-boxed:** 20 probes or 2026-12-18, whichever comes first, unless a filter has passed.
  Review after 10.
- The total risk cap, the exit-feasibility check and every hard limit apply as to any trade.

### In code
- `src/vantage_trader/earnings/intraday.py`: seventeen gates, the tier, the exit plan, the
  pilot's breaker. CLI `intraday-gate` (exit 0 = enter, 3 = no trade) and `intraday-status`.
- `config/earnings.yaml`: the `intraday_*` keys. Hard caps a config cannot raise: 1 contract,
  1 entry a day, probe max loss $80, signal max loss $200, pause at -$150 or 3 losses (see v1.15.1), time
  stop no later than 12:15 PT.
- Journal events of the pilot carry `"kind": "intraday_0dte"`. `closed_trades` reports the
  kind; the account breaker and the edge calibration leave those trades out.
- `scripts/earnings/intraday_replay.py` scores the replay; `scripts/earnings/intraday_moves.py`
  keeps the ten same-hours moves the gate needs.

### Off switch
- Brad says "day trades paper": `intraday_live_enabled` is set to false. The paper desk is
  unaffected either way.

### What it means
- At most about $26 to $75 at risk on a morning, inside the total cap. Buying power used:
  $100 to $200 until 11:00 PT.
- A month of probes costs about $100 in expectation and is capped at $150.

### Review
- After 10 closed probes: round-trip cost against mid ($6 or less keeps it going, above $8
  ends it), the live mean against the replay's, every exit on time.
- The replay's next batch (the 30 sessions before 2026-10-06) tests two filters fixed today:
  an overnight gap under 1%, and that plus a first-hour move under 0.2%.

## v1.15.1 (2026-11-16, later the same evening): the pilot's caps after the cap-level test
Brad: "$150 is an extremely small cap. Can you test it with different cap levels? Could be a
buying power issue." and "Scan the market for optimal daytrading options. Lets not lock
ourselves to just a few tickets. But liquidity and tightish spreads is important not to eat
into profits". Tested the same evening (`scripts/earnings/intraday_caps.py`, tables in
`INTRADAY.md`), decided by the agent under the delegation of 2026-11-16.

- **He was right about the budget.** At -$150 a one-contract IWM pilot with no edge is stopped
  by luck in about 1 run of 4, and "3 losses in a row" stops it in 6 to 8 runs of 10. Now:
  **-$500 in total or 6 losses in a row.**
- **Probe max loss $150** (was $80), so one contract of more names than IWM fits. Still one
  contract, one fly a day. The signal tier's $200 is unchanged and still off.
- **A bigger per-trade cap does not help.** From $80 to $600 every level lost a little on
  average and the loss grew with the cap (SPY at $400: -$105 a day). The body straddle with no
  wings did worse than the fly. Buying power is not the constraint: a $400 cap fits a flat
  account.
- **Names come from a scan, not a list:** the universe of liquid same-day names is rebuilt from
  options volume, a morning spread scan ranks them, and a name joins the live list when its
  spread and its own replay earn it (`INTRADAY.md`, "Which names"). IWM is the only live name
  tonight because it is the only one whose replay came out at breakeven.
- Hard caps in code: probe max loss $150, budget $500, streak 6, 1 contract, 1 entry a day.

## v1.16 (2026-11-17): the earnings name cap is $600 (owner)
Brad, 2026-11-17 08:05 PT: "Increase the risk cap. Like if tgt meets the criteria we shouldnt
limit it especially when the cap is close to the cost price". That morning every priced name
was over $350 at its narrowest allowed fly: TGT $502, TJX $420, LOW $530, GLBE $595.
- **Max loss per earnings name: $600** at the credit floor (was $350). Hard cap in
  `config.py`; `name_risk_cap: 600` in `config/earnings.yaml`. The near-miss tier and a name
  with one soft condition get half: $300 (was $175).
- **Unchanged:** a name whose at-the-money spread is above 12% stays at $350
  (`wide_spread_max_loss`): crossing that market costs more than the edge pays. Non-earnings
  names stay at $400 (his number of 2026-11-13). The total risk cap, the 0.9x wing floor
  (v1.13) and the exit-by-legs check (v1.9, gate 16) are unchanged.
- **Why $600 and not more** (replay, 103 reports, `scripts/earnings/earnings_fly_table.py`):
  caps from $250 to $500 keep $5 to $9 a fly; with no cap the fly keeps nothing. Only two
  replayed names needed more than $350 at the narrowest fly, and the one that needed more than
  $500 (FTNT) was the largest loss of the sample: at $600 the average falls from $9 to $3 on
  that one event. So the evidence supports $500 and says nothing reliable beyond it; $600 is
  the owner's choice of more risk, 25% of the account on one name.
- **What it does not change:** on stocks above about $150 the binding limit is the exit by
  legs, not the cap. TGT on 2026-11-17: the 140/157.5/175 fly risks $657 and needs $1,925 of
  buying power to exit; the 145/157.5/170 fly fits at $364 and its wings are 0.88x the
  straddle, under the floor. Such names are the owner's to place and close with 4-leg orders
  until Robinhood accepts them from the agent (P005, P051).
- Measure (P056): after 10 trades entered with a max loss above $350, their result per dollar
  at risk is no worse than that of the trades at or under $350, and no name has cost more than
  25% of the account. Review at 10 such trades or on 2026-12-18. "Name cap 350" from Brad
  reverses it.
- Supersedes P041 ($350 to $400), which was waiting for the 2026-11-17 reflection.

## v1.16.1 (2026-11-17 08:20 PT): the owner-executed lane
Brad, 2026-11-17: "What if you plan them out and I place the multi leg orders?", then
"Interesting. Ok lets try it. You can handle the daytrades too though. And we can close hd
before market close but let it ride for now".
- **Why:** Robinhood refuses the agent's multi-leg orders, so the agent must be able to exit
  one leg at a time. On a stock above about $150 one short leg at the wing can cost more than
  the buying power (gate 16), and legging costs 1% to 12% of the credit where his 4-leg close
  of HD on 2026-11-17 filled at the mid. The replayed fly keeps $7.5 at a 7% cost and $22 at 3%.
- **What:** a name that passes every entry rule except gate 16 goes to Brad as one ready
  4-leg ticket (legs, quantity, limit at the mid, walk steps, max loss, breakevens, exit time)
  with a push. He places the entry and the exit in the app. The agent records, sets alerts,
  watches, and sends the closing ticket at 06:38 PT the next morning.
- **Fallback:** no closing order of his by 06:50 PT and the two short legs fit the buying
  power: the agent tells him and closes it by legs. If they do not fit it stays his.
- **In code:** the gate takes `"owner_executed": true` (or his words); gate 16 then passes
  with a note and the record carries `"lane": "owner_executed"`. Every other gate binds.
- **Unchanged:** the name cap, the total cap, defined risk, the 0.9x wing floor, a 12% spread
  for anything above $350, the news check, never TSLA. The same-day pilot and every fly the
  agent can exit by legs stay the agent's own.
- **HD (his hold):** rides on 2026-11-17 and is closed before that day's close: closing ticket
  and push at 12:30 PT, by the agent's legs at 12:45 PT if he has not closed it.
- Measure (P057): after 5 owner-placed round trips, their cost against the mid as a share of
  the credit against the agent's legged trades (expect under 3% against about 6%), and every
  exit placed or legged by 07:00 PT. "Legs only" from Brad ends the lane.

## v1.16.2 (2026-11-17 08:39 PT): the same-day fly goes on in one block
The first live same-day fly (IWM 267/269/271, ordered by Brad outside the pilot's window:
"Probe anyway") collected 1.14 against a mid of 1.28. Two cents of that were the spread. The
other twelve were the agent's sequence: the body was sold 237 seconds after the wings (the
session reloaded its tools between the two steps), each body order carried the bid of 20
seconds earlier as its limit, the call missed, and IWM fell 0.40 while the fly was one-sided.
- **Entry is one block of work.** Quotes, gate, the four order reviews and every tool are
  ready before the first wing order. Nothing else happens until the fly is complete or unwound.
- **Marketable limits.** Wings at the ask plus 0.02; both body legs together at the bid minus
  0.03. The floor is checked on the body bids at the read before the body orders, not on the
  limits.
- **One-sided for at most 60 seconds.** A missing body leg is cancelled and re-sent at once.
  The fly is finished if its body strike is still within 0.5 x the straddle of the spot, even
  under the floor (the slip is sunk and unwinding costs three more spreads); further away it
  is unwound. The 5 minute timer stays only for an order the session's permission check refuses.
- **Owner-ordered flies.** A fly Brad orders outside the pilot's rules is journaled with
  `outside_test_data`: it counts for the pilot's loss limit and streak, not for the 20-probe
  test or its averages (`intraday.pilot_state`: `test_trades`, `override_trades`).
- Measure (P058): after 5 pilot entries, average `seconds_one_sided` at or under 20 and average
  leg slip at or under $3 a fly. Above $5 the pilot stops entering by single legs and waits
  for multi-leg orders, the owner lane or the staging desk: the replay's edge before costs is
  about $5 a fly.

## v1.16.3 (2026-11-17 10:11 PT): how a leg is priced
Brad, 2026-11-17: "when you were trading them one by one, you should do middle limit orders
instead of market. And use the data from last sales etc for better pricing judgement. That
would get rid of a lot of the slippage".
- **Already so:** every order is a limit order, and an earnings leg starts at the mid. On the
  penny-wide IWM fly the agent crossed the spread on purpose; that cost two cents. The other
  twelve were the time between the legs (v1.16.2).
- **New:** the fair price of a leg is the mid pulled halfway toward a recent print that lies
  inside the quote. The broker's own fill hints (`low_fill_rate_*`, `high_fill_rate_*`, in
  every quote and unused until now) make the ladder: low-fill hint, fair price, high-fill
  hint, then ticks. Patient steps where nothing is exposed (wings), fast ones once a fly is
  one-sided. `docs/earnings/EXECUTION.md`.
- **Learning:** every leg is recorded (`legs_detail`); after 20 legs the ladder's start moves
  to the step where the fills happen.
- Measure (P059): after 20 legs on contracts wider than two ticks, the average give-up
  against the mid is at most a third of the half-spread, and no entry is one-sided for more
  than 60 seconds. Review 2026-12-05.

## v1.16.4 (2026-11-17, at the reflection): the agent trades all of it
Brad, 2026-11-17 10:19 PT, after the agent offered TJX as his 4-leg ticket: "Ideally you will
trade all of it."
- **The owner-executed lane (v1.16.1) is the last resort.** A name that fails only the
  exit-by-legs check is first made to pass: close what is due, enter after the day's exits,
  use the close order of `EXECUTION.md` section 5. A ticket goes to Brad only when the broker
  leaves the agent no way to enter or to exit, and it names the step that failed.
- **Exits of flies he placed are the agent's** when the buying power allows (TGT on
  2026-11-18): by legs, on the pricing ladder.
- **Gate 16 stays as it is in code** (1.1 x wing width x 100 left after the entry). It blocked
  TJX at 10:08 PT and passed it at 11:02 PT once HD's collateral was back, which is the
  behaviour wanted. A lighter test (the dearer short leg at the largest past earnings move)
  waits for 8 exits with `bp_at_exit` and `dearer_short_ask` on record.
- **The bridge leg** (`EXECUTION.md` section 5, step 5) is written down and not tested.
- With it: timers live at most two hours (P060); the account-watch daemon keeps its 5 minute
  cycle on an owner hold (P061); a time in a record comes from the clock (L025).
- Measure (P062): over the next 10 trading days every exit is placed by the agent (0
  tickets), or each ticket names the step of section 5 that failed. "Tickets on" from Brad
  brings the lane back as a first choice.


## v1.16.5 (2026-11-17 20:57 PT): what the system costs to run (P063)

Brad, 2026-11-17 evening: "Should we switch to opus 5.5 with fable as an advisor to help
mitigate some usage?" The usage was measured before the answer
(`scripts/earnings/usage_scan.py`: every model call in Claude Code's own transcripts, at list
prices per token; its total for 2026-11-04 to 11-17 matches the session's own meter within
0.1%). Nothing is billed per token on a subscription; the dollar figure is the common unit.

- **Six trading days, 2026-11-10 to 11-17: about $190 a day.** The head 61%, its subagents
  39%. On 2026-11-17: $198, the head $121, subagents $77.
- **The head's cost is the size of its conversation.** On 2026-11-17: 340 calls with an
  average conversation of 584k tokens. Reading it back from the cache $39; writing to the
  cache $57, of which five cold starts $35 (the cache had expired, or the conversation had
  been compacted); output $25. The same tokens on Opus 5.5 come to about $80 instead of
  $121: a cached re-read costs the same on both models, so the model is a third of the
  head's cost and a fifth of the day.
- **A wait past the cache window is the dearest thing an agent does.** A subagent's cache
  lives 5 minutes. 262 wakes after waits of 5.5 to 10 minutes on the six days were all cold:
  $191, 17% of everything. The 10 minute cadence of 2026-11-10 (chosen for cost) and the
  paper desk's waits of up to 590 seconds were the cause, and `prompts/exit_scan.md` still
  said "10-minute cadence by default".
- **A fast poller that runs all day pays for its own history.** The account watch at 150
  seconds: 304 calls, conversation 82k to 785k tokens, $34 (17% of 2026-11-17). Its token
  count (808k) was the wrong measure: it hid both of these.
- Changes, in force from 2026-11-18:
  - No agent waits longer than 240 seconds in one piece (`DAEMON.md`,
    `prompts/brief_paper_desk.md`, `prompts/brief_daytrade_scan.md`, `prompts/exit_scan.md`).
  - The monitor daemon's default cycle is 4 minutes (it was 5), and the hourly check-in
    replaces a daemon that has run two hours.
  - The reflection fires at 13:12 PT (it was 14:12), inside the head's one-hour cache.
  - The reflection writes the day's usage line and a row in `state/earnings/usage.jsonl`.
- Not changed here: the head's model, its effort setting and the size of its conversation.
  The first two are the owner's settings (the session runs Fable 5.2 at effort "max"). The
  third needs the scheduled runs to stop sharing one conversation: a build for the research
  day, not for the night before two live exits.
- Measure (P063), over the next 5 trading days: no cold wake by a subagent; the daemon and
  the paper desk together under 10% of the day; the day under $150 on a day with two to
  four fills. Lesson L026.

## v1.16.6 (2026-11-18 10:05 PT): soft news no longer halves the size (owner)

Brad, 2026-11-18: "Soft news should stop halving". A risk-sentinel flag written as `soft:...`
(public, already priced, no date inside the holding window) now passes at full size
(`config/earnings.yaml` `soft_news_sizes_down: false`; `gate.py` no longer counts it as a
prudential condition). Unchanged: every hard flag blocks; the soft macro band still halves; the
near-miss tier (edge ratio 0.85 to 1.10, rules v1.10) still halves, so WMT and PDD of
2026-11-18 stay at one contract each. `soft_news_sizes_down: true` restores v1.14.
Measure: over the next 10 earnings trades that carried only soft flags, the result per
dollar of max loss against the core-tier trades without flags.

## v1.16.7 (2026-11-18 11:55 PT): Friday earnings entries go live at half size (P039)

Approved 2026-11-16 (Brad: "should be trading all work days of the week"), wired today before
the first Friday. On Fridays the morning scan, the 09:45 re-check and the 11:46 sweep run for names
that report Friday after the close or Monday before the open. The gate takes `"weekend_hold": true`
and sizes such a name at `weekend_size_frac` (0.5) of the name target and cap: the smallest of
the near-miss, prudential and weekend factors applies, never their product. The Monday 06:36 PT
run exits them. The ENTRY, midday and entry-backup tasks now fire Monday to Friday; the standby
entry switch no longer skips Fridays and its stored prompt carries the current name caps.
Measure (P039): after 8 live or paper Friday entries, result per fly after costs against the
Monday-to-Thursday flies; back to paper if the first five closed Friday flies lose more than
$150 in total. "Fridays paper" from Brad reverses it.

## v1.16.8 (2026-11-18 13:20 PT): owner tickets show the account share; the last-hour daemon (P065, P066)

P065 (process, agent): every owner-executed ticket states, before Brad places it, the max loss as a
share of the account value against the 30% per-name ceiling (P044), every gate it waives, and who
can close it at the exit and how. PANW reached him on 2026-11-18 as dollars only ($895, 46% of the
account). Measure: every later owner ticket carries the three items (checked in each reflection).
P066 (cost, decided by the agent under the delegation of 2026-11-16): a monitor daemon is replaced
after two hours except within an hour of its 12:57 PT end, and the usage measure is in dollars: no
cold wake, the daemons and the paper desk together at $15 a day or less (the 10% share of P063 moved
with the head's own cost). Measure: the usage line for five trading days. "P066 off" reverses it.

## v1.16.9 (2026-11-19 reflection): timer timeouts and the daemon's age on record (P068, P069)

P068 (process, agent): a background timer's Bash timeout must be longer than its wait, and the
10:57 PT pilot timer is started from the 10:15 PT run (a timer started at 09:15 PT with a one-hour
timeout was stopped at 10:15 PT on 2026-11-19; it was restarted and the exit ran on time).
P069 (process, agent): the daemon's start time is written to positions.json and every check-in
replaces a daemon older than two hours. P066's replacement relied on memory and did not happen on
2026-11-19 (one daemon, 06:41 to 12:57 PT, 84k to 1,097k tokens, about $20 of the day's $64).
Measures: no timer stopped before its event; daemons and paper desk at $15 a day or less.


## v1.16.10 (2026-11-20, reflection)
P071 (execution, agent): expiry-day carve-out to v1.2.2. A max-loss spread is closed by legs before 11:00 PT when the in-the-money short's buyback is accepted by the broker (debit at or under released collateral plus buying power) and the stock is within 1% of the long strike, or at 10:45 PT; the let-it-expire branch stays only for a deep in-the-money long leg with no possible buyback. An owner hold ends at the 11:00 be-flat rule. Evidence: PDD 2026-11-20 closed 83.655, under its 84 long call; held, the short 78C would have been assigned into a weekend with about 100 of buying power. Measure: over the next 5 max-loss spreads on expiry day, no assignment and close cost within 0.30 of the spread's value at the close. Review 2026-12-18.
P072 (tooling, agent): scripts/earnings/timer.sh refuses a wait over 115 minutes; the 09:15 run starts the 10:30 timer. Replaces P060 and P068 (both did_not_work: the 10:30 timer died at its 2 h limit on 2026-11-20). Measure: no timer stopped before its event in 10 trading days.
P073 (process, agent): the standby entry switch moves on every entry decision, trade or no-trade, to the next entry day Mon to Fri (Fridays are entry days since v1.16.7). Measure: the entry switch does not fire on a day the head ran its sweep, over 10 trading days.
P074 (cost, agent under the 2026-11-16 delegation): the Friday spread scan holds 25 names and 120 tool calls at most. Measure: scan agent at $4 or less. Brad: 'scan 40' reverses it.
P076 (process, agent): no buying-power claim or ticket without the review result of that order.


## v1.16.11 (2026-11-23, reflection)
P078 (process, agent): the account-watch daemon starts with an owner ticket; the head does not poll. Measure: head calls between ticket and fill at 2 or fewer.
P079 (process, agent): no recommendation to Brad before the exit-time payoff is run. Measure: every recommendation cites the average over past moves.
P080 (data, agent): the 07:27 pilot run records VIX; the reflection logs the closing VIX (state/earnings/daytrade/vix_log.json). Data for H016 and P075.
P081 (execution, agent): owner opening tickets rest 20 minutes at the first limit before the first step. One fill behind it (DKS, 102 minutes at 10.75). Measure: on the next 5 owner tickets, the fill against the price a minute-5 walk would have taken. Review 2026-12-18.
P082 (execution, agent): EXECUTION.md section 5, step 3b: when the dearer short does not fit alone, the cheaper short goes first and the dearer one is paid from buying power plus the collateral it releases. Evidence: PDD 2026-11-20 fill; DKS reviews 2026-11-23 (either buyback alone releases 0). Measure: the next exit that needs it is accepted by the broker.
P083 (execution, agent): expiry-day clock times are set against the contract's sellout_datetime (09:30 PT on Fri 2026-11-27). Amends P071's 10:45 and 11:00 PT.
P084 (rule, deferred): gate 16 assumes an in-the-money short must be bought back from buying power alone; with step 3b the reach is buying power plus the wing width, which would let the agent trade flies like DKS itself. Deferred until 8 live exits have used step 3b or its review.
timer.sh takes relative waits (+9m); L028 stays active (four raw sleeps on the first day of P072).

## v1.16.12 (2026-11-24, reflection)
P085 (tooling, agent): selfcheck fails an exit record whose fill_vs_mid is not the ratio mid / fill (the DKS exit carried the difference and showed a 49% cost instead of 7.4%).
P086 (process, agent): the pre-open wake pushes Brad when a position due that morning is priced before the open beyond a breakeven. Measure: on the next 3 such mornings, whether his order or a reply arrives before the agent's first leg.
P087 (execution, agent): the marketable wing sale (two ticks under the bid) is for a wing whose time value is under a quarter of its price; a wing near the money goes on the v1.16.3 ladder from its high-fill hint, repriced every 10 to 15 seconds. One observation: the DKS 150 call sold at 4.60 against a 4.40 bid.
P088 (rule, deferred): v1.2.2 does not say whether the 90% test reads the mid or the natural. Written down as applied: the mid of the four legs at the read. On DKS the mid was 12.88, the natural 15.00 and the legs filled at 13.50, exactly the line. Decided at 8 exits in that zone or at the first where the two tests differ by more than $100. Brad's words that change it now: "v1.2.2 on the natural".
P089 (process, agent): with the breaker halted the 11:46 sweep runs on paper (re-quote, gate, a paper fly for each name blocked by the breaker alone) and no reset is offered with a deadline.
P090 (process, agent): the account-watch daemon starts at the 07:15 PT run on flat days too, as hourly_monitor.md already says; the reflection now checks for its start time.
P091 (rule, deferred): owner-lane exits wait until 06:50 PT for Brad's order (v1.16.1) while v1.16.4 says the agent exits his flies by legs when it can. Decided at 5 owner-lane exits. His words that settle it now: "leg my flies at 06:40" or "keep the 06:50 wait".
P092 (risk, HARD LIMIT, waiting on Brad): the account breaker's streak counts a hand stock trade. It halted on 2026-11-24 at ANT (his stock trade), PDD, DKS; without ANT the streak is 2. Proposed: option structures only, as the pilot is already left out. "yes P092" or "no P092"; "reset breaker" is the other way out (it sets circuit_reset_ts; his words are enough).
Retired: H006 (the macro veto is not shown to be useless: +2 / -3) and H012 (gap size does not sort same-day flies: +2 / -4).

## v1.16.13 (2026-11-25, reflection)
P094 (tooling, agent): a paper result is floored at its structure's max loss, at the mid credit and at the natural credit; the quoted figure is kept. 22 desk results were under their floor (wide quotes on deep in-the-money legs): the desk's natural total read -3,801 on 78 flies and is -2,941. selfcheck fails on a result under its floor. The desk picks its strike from the read that prices the fly.
P095 (process, agent): selfcheck fails when a paper desk file of an earlier day is not fully in live_metrics.jsonl. The files of 11/20, 11/23 and 11/24 (23 results) had never been imported.
P096 (rule, deferred): the macro veto is read at each entry decision, as the text says; on 11/25 it was hard at 07:27 PT (VIX 34.08) and off at 11:47 PT (28.28). Whether a morning spike that fades should block the sweep goes to the research queue. His words that settle it: "macro veto all day" or "macro veto at entry".
P097 (rule, agent under the delegation): the near-miss tier (v1.10) stays at half size. P032's review date came with 3 closed tier trades (AS -0.28, WMT +182.84, PDD -197.29): too few. Next review at 10 closed tier trades or 2026-12-18; off at once if the first five lose more than $150 in total. His words that switch it off: "near-miss off".
P098 (process, agent): with the account breaker halted the non-earnings screen's hits are listed without the news check; the lane itself goes to the research queue (PLAN.md section 9, item 7) with a date, 2026-12-12.
P094, how to read it: the floor at the mid removes a quote artifact. At the natural the floor is a bound (the most the fly loses if held to the bell) and the quoted figure is what crossing every quote at the mark costs; a real exit lands between. Reviews of the desk and of the pilot quote both (the dataset keeps `pnl_natural_usd` and `pnl_natural_usd_quoted`).
P099 (process, agent): early-close days are written into hourly_monitor.md and exit_scan.md: the account watch ends 09:57 PT, the last look is 09:57 PT, no paper desk, no pilot, expiring contracts flat by 08:00 PT.
No lesson retired or added. H008 is at +14 / -9 after HPQ and LI: under its 2 to 1 bar.

## v1.16.14 (2026-11-27, reflection and weekly scorecard)
P103 (risk, agent under the delegation; a tightening): the 30% per-name ceiling of P044 is now in the gate. The name cap is the smaller of the dollar cap and 30% of the account value: at an account of $1,453 that is $436 where the dollar cap says $600. P044 had rested on the caps being lower, which stopped being true under $2,000. selfcheck fails on an open name above 30% until Brad has been told (ceiling_notice): his 5 ANT shares (449.94 at cost) had been 32% of the account since 11/24 with nothing said. His words: "no ceiling" sets the line aside; "trim ANT" has the agent sell 1 share.
P088 (rule, agent under the delegation; no change): the v1.2.2 line (hold when closing costs 90% of the width or more) stays tested at the mid of the four legs. On DKS the mid (12.88) said close and the natural (15.00) said hold; the fly expired at its full 15.00, so closing at 13.50 was 149.67 better. One exit, reviewed at 8. His words: "v1.2.2 on the natural".
P093 (rule, declined): H008 is not adopted. Its tally fell to +14 / -9, under the 2 to 1 bar. H008 and H001 (+13 / -9) are back to being tested. His words: "adopt H008".
P100 (process, agent): the Friday spread scan picks its names by class when the universe file has no key for the day, with a written trim order (daily, then Mon/Wed/Fri by volume). The 25-name cap, not the file, leaves the weekly names out on a Friday.
P101 (process, agent): the reflection on an early-close day adds no same-hours row, takes the 10:15 PT VIX settle as the close, and writes an expired contract as pending until the next pre-open.
P102 (process, agent): 57 implemented proposals have no verified event. The Saturday run closes 20 a week, oldest first; the Friday scorecard prints the count.
Verified: P036 (wing floor: nine flies at 0.92x to 1.48x, one structure blocked) and P037 (no ledger row dated ahead of its commit) worked; P099 (early-close texts) worked; P083 inconclusive.

## v1.16.15 (2026-11-28, Saturday research day)
No rule changed. What was decided:
P070 (rule, declined: parked). The exit-priced filter does not become gate 18. Bar of 2026-11-21, method note and script pushed before the first run. 206 clean replay events, 193 usable: flies projected at or under zero -$19.1 (n 111), the rest +$6.8 (n 82); kept minus blocked +$25.9, clustered t 1.78 on 36 report dates, under the 2 asked. Same sign in all four batches. It stays a number read before sizing and before a recommendation (L015, P079). It reopens only on 60 or more later reports with a point-in-time read of the volatility left after the report, written first. His words that make it a gate anyway: "gate the exit-priced check".
Width (PLAN.md 3A item 4, due 2026-11-27): the wings stay aimed at 1.5x the straddle. On 206 events 2x is within $1.40 a fly of 1.5x at every cap.
P104 (risk, deferred): a half-size restart of the earnings line after the breaker halt, as PLAN.md 3A's shrink line reads. Not stacked on P103's cut of the name cap (600 to 436) the day before; decided at the reset or on 2026-12-18. His words: "half size restart".
Scan (process): the watchlist file keeps every scanner row with its front and back IV, every day.
P102: 20 of the 57 implemented proposals without a verified event were checked against their own measures (P008 to P035): 7 worked, 1 did not (P017: the same-day line's own paper measure is negative; it runs only as the v1.15 pilot), 12 inconclusive.
The replay itself (2026-11-28, 206 events): short straddle +7.0% of the straddle (t 2.4); the fly as traded +$23.8 before costs and -$7.7 after a 7% cost at the $600 cap (se $10.5), breakeven cost 5.3% against 4.2% paid live on 12 trades.
P105 (cost, agent under the delegation; a tightening): the line that halves the earnings sizes on cost is the breakeven of the fly as traded in the latest Saturday replay ($600 cap), not a fixed 9%. It is 5.3% on 2026-11-28; the last ten live flies cost 3.8%. His words: "cost line 9".
P106 (data, agent): the exit-priced average in entry.md used 1.1x the ambient volatility while the calibration file has said 1.3 since 2026-11-17; the text now reads the file. On 8 names the base used live ran at a median 0.73 of the volatility the market showed after the report. The calibration scoreboard (three rows, none since 11/17) is brought up to date and its update rule run at Monday's reflection.

