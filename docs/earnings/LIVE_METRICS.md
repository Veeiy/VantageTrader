# Live metrics dataset

Purpose: calibrate the rules on what live trades actually did (fills, slippage, moves,
P/L), next to the paper results for skipped names.

File: `state/earnings/live_metrics.jsonl`, append-only, one JSON object per line.
The journal (`journal.jsonl`) stays the ledger; this file holds the numbers around it.
Summary: `PYTHONPATH=src python -m vantage_trader.earnings live-metrics`.

## Records
All records carry `trade_id` (`SYMBOL-YYYYMMDD-n`), `record`, `ts` (UTC), `symbol`,
`kind` (`earnings` or `non_earnings`) and `live` (false for paper).

### `entry` (written right after the last leg fills)
- `structure`, `strikes`, `expiry`, `dte`, `quantity`, `entry_spot`, `report`
- `signal`: `edge_ratio`, `implied_move` (0.85 x ATM straddle / spot), `straddle_pct`,
  `hist_avg_move`, `hist_median_move`, `n_hist`, `hist_beyond_be`, `regime_20d`,
  `intraday_pct`, `atm_spread_pct`, `atm_iv`, `sector_exception_used`, `peers_pct`,
  `spy_pct`. Non-earnings: `iv_rank`, `hv10`, `iv_over_hv10`, `driver`.
- `execution`: `credit_mid_at_read`, `credit_natural_at_read`, `fill_credit`,
  `fill_vs_mid` (fill / mid), `seconds_first_order_to_last_fill`, `reprices`, `tick`,
  `fees_usd`, `leg_fills`
- `risk`: `max_loss_usd`, `max_profit_usd`, `breakevens`, `wing_width`

### `adjust` (partial close, roll, trim, scale-in add)
- `tag`, `closed_quantity`, `open_quantity`, `spot`, `close_debit`, `pnl_usd`, `note`
- A scale-in add (rules v1.7) is an `adjust` record with `tag: "add"`, the same `trade_id`
  as the name's entry, `added_quantity`, `open_quantity` (the new total), the tranche's own
  `signal`, `gate` and `execution` blocks (as on an entry), `risk.max_loss_usd` (the NEW
  total for the name), `avg_credit` (quantity-weighted over all tranches), `phase`
  (`early` or `final`) and no `pnl_usd`. One name stays one trade: the exit record carries
  the whole position's result.

### `exit` (written right after the position is flat)
- `exit_spot`, `prior_close`, `realized_move` (signed, entry-day close to exit spot),
  `realized_over_implied`
- `execution`: `close_mid_at_read`, `close_natural_at_read`, `fill_debit`,
  `fill_vs_mid` (mid / fill, 1.0 = filled at mid), `seconds_first_order_to_last_fill`,
  `reprices`, `fees_usd`, `leg_fills`
- `pnl_usd` (after fees), `pnl_pct_of_max_profit`, `hold_hours`
- `verdict`: `edge_call_right` (true/false), `rules_that_helped`, `rules_that_hurt`,
  `exit_reason` (`morning_after`, `take_profit`, `cut`, `plan_date`, `rebalance`)

### `paper` (a passing name that was not traded)
- same `signal` block, `credit_mid`, `credit_natural`, `skip_reason`, and at scoring time
  `pnl_mid_usd`, `pnl_natural_usd`, `realized_move`.

## How it is used
- Friday scorecard: live vs paper win rate and P/L, entry and exit `fill_vs_mid` by
  spread band and tick size, realized move over implied by edge-ratio bucket.
- `calibrate` proposes threshold changes from the journal once 8 trades are closed.
- Trades tagged `rebalance` are left out of edge statistics and kept for execution cost.

## P/L projections (`state/earnings/projections.jsonl`)

Brad, 2026-11-10: "Project the p/l factoring in the earnings iv crush. Then I want you to
cross check from where they open tomorrow so we can hone in on accurate projections."

For every earnings fly, the evening after the report:
1. `projection` record: after-hours spot, the total standard deviation left to expiry
   (two estimates: the forward variance between the front and next expiry, and the
   pilot's median post/pre ratio), a spot x volatility grid of P/L, and the expected exit
   slippage. Model: `vantage_trader/earnings/projection.py`.
2. `actual` records the next morning, one at the open (first quotes after 06:30 PT) and
   one at the exit: spot, the body straddle at mid, the four-leg close cost at mid, and
   the fill. `project-check` splits the error into three parts:
   - **spot**: the stock opened somewhere other than the after-hours price,
   - **volatility**: the IV crush was bigger or smaller than assumed,
   - **skew and quotes**: wings, stale or wide quotes; plus fill versus mid.
3. Three numbers are tracked per name and pooled, and feed the next projection:
   - `sigma_actual_over_projected` (and post/pre, the crush itself),
   - `share_of_after_hours_move_kept` (exit spot move divided by the after-hours move),
   - exit slippage versus mid in dollars.
The daily reflection reports the running median absolute error. The model is revised
when it stays above $25 a contract after 10 scored projections.
