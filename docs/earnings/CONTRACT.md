# Engine <-> Agent interface contract (v1.2)

The scheduled Claude session gathers data with Robinhood MCP tools, writes a
**snapshot JSON**, runs the engine CLI, and executes the engine's **decision JSON**
with Robinhood MCP tools. The engine never talks to the broker. All money values USD,
all percentages as fractions (0.095 = 9.5%). Extra keys in inputs are ignored unless
listed; extra keys in journal lines are preserved.

## CLI
Run from the repo root (all paths repo-root relative).
```
python -m vantage_trader.earnings score     --snapshot snap.json --config config/earnings.yaml --journal state/earnings/journal.jsonl > decision.json
python -m vantage_trader.earnings exit      --snapshot snap.json --config config/earnings.yaml --journal state/earnings/journal.jsonl > exit.json
python -m vantage_trader.earnings reconcile --snapshot snap.json --journal state/earnings/journal.jsonl --config config/earnings.yaml > recon.json
python -m vantage_trader.earnings calibrate --journal state/earnings/journal.jsonl --config config/earnings.yaml > calib.json
python -m vantage_trader.earnings history   --bars bars.json --events events.json > moves.json
```
`--config` defaults to `config/earnings.yaml`; `--journal` on score/exit defaults to
config `journal_path`. Always pass both explicitly.

Exit codes (stdout is always JSON):
- `0` success (decision may be no trade).
- `1` internal engine error, stdout `{"error": "internal: ..."}`. Not an input problem; do not retry blindly.
- `2` invalid input, stdout `{"error": "..."}`. Heal the input and retry.
- `3` halted by circuit breaker (`score` only; `exit` always returns 0 and reports the breaker as context).

## history
bars.json:   {"SYMBOL": [{"date":"YYYY-MM-DD","close":float,"interpolated":bool}, ...]}
events.json: {"SYMBOL": [{"date":"YYYY-MM-DD","timing":"am"|"pm"}, ...]}   (past reports only)
moves.json:  {"SYMBOL": {"moves":[float signed fraction,...], "dates":[...], "skipped":[{"date","reason"}]}}
Interpolated bars are skipped (treated as missing); if the needed bar is missing, skip that
event with a reason. AMC (pm) move = close(report day) -> close(next day); BMO (am) move =
close(prior day) -> close(report day).

## score snapshot
```json
{
  "as_of": "2026-11-04T19:55:00Z",
  "account": {"account_number":"...", "buying_power":750.0, "total_value":750.0,
              "open_risk_usd": 0.0, "human_must_approve_trades": false},
  "open_positions": [ {"symbol":"ARM","structure":"iron_fly","opened":"2026-11-04"} ],
  "candidates": [
    {
      "symbol": "ARM", "chain_symbol": "ARM", "report_date":"2026-11-04", "timing":"pm",
      "verified": true, "spot": 202.49, "expiry": "2026-11-06",
      "historical_moves": [-0.062,-0.134,-0.012,0.057,-0.101,0.074],
      "intraday_move": 0.012,
      "chain": [
        {"strike":202.5, "call":{"id":"uuid","bid":11.45,"ask":11.55,"oi":103},
                         "put": {"id":"uuid","bid":11.15,"ask":11.35,"oi":129}}
      ],
      "flags": []
    }
  ]
}
```
- `chain` covers ATM +/- ceil(max(`wing_widths_pct`) x spot) plus one listed strike beyond each side.
- `intraday_move` is required (null invalid). `flags` and `open_positions` default to [].
  Any flag -> skip, except `big_intraday_move` (the intraday gate covers it).
- Optional candidate fields (P004): `regime_20d` (regime guard applied when present; the
  `gate` command requires it) and `sector_same_direction` (allows a 5-7% intraday move).
- `account.open_risk_usd` = max loss + exit reserves of the open positions; required when
  `open_positions` is not empty. There is no open-position limit (v1.4). `chain_symbol` optional; blocklisted -> `blocklisted`, differing from
  `symbol` -> `symbol_mismatch`.
- `historical_moves` chronological, oldest first (as emitted by `history`).

Entry timing (today = `as_of` date in `market_timezone`): `report_not_imminent` unless
(pm and report_date == today) or (am and report_date == next trading day, skipping
weekends and `market_holidays`).
Expiry rule (`bad_expiry` unless all hold): expiry > today; expiry <= report_date +
`max_expiry_days_after_report` (7) days; pm -> expiry > report_date; am -> expiry >=
report_date; expiry not on a `market_early_closes` day.

## decision (score output)
```json
{
  "as_of": "...",
  "status": "trade" | "no_trade" | "halted",
  "reason": "string",
  "risk_cap": 697.5,
  "human_must_approve_trades": false,
  "circuit_breaker": {"halted": false, "reasons": [], "consecutive_losses": 0,
                      "consecutive_max_losses": 0, "closed_trades": 0,
                      "journal_path": "state/earnings/journal.jsonl", "journal_found": true},
  "ranked": [ {"symbol","edge_ratio","implied_move","avg_hist_move","action":"sell|buy|skip",
               "skip_reason","ev_per_dollar_risk"} ],
  "order": null | {
    "symbol":"ARM", "structure":"iron_fly"|"long_straddle",
    "quantity": 1, "direction":"credit"|"debit", "expiry":"2026-11-06",
    "report_date":"2026-11-04", "timing":"pm",
    "legs":[{"option_id":"uuid","side":"sell","position_effect":"open","strike":202.5,"type":"call"}],
    "order_legs":[{"option_id":"uuid","side":"sell","position_effect":"open"}],
    "limit_start": 14.60, "limit_floor": 13.00, "limit_step": 0.10,
    "max_loss": 540.0, "max_loss_worst": 700.0, "risk_cap": 697.5, "max_profit": 1460.0,
    "breakevens":[187.9, 217.1], "hist_win_rate": 0.67, "ev_per_dollar_risk": 0.12,
    "hist_ev": 65.0, "mid": 14.6, "natural": 13.2, "atm_strike": 202.5, "wing_width": 20.0,
    "implied_move": 0.0955, "edge_ratio": 0.768,
    "cancel_by": "12:50 America/Los_Angeles"
  }
}
```
- `order_legs` is what the agent sends to `review_option_order` / `place_option_order`
  (option_id, side, position_effect only). `legs` is for reading.
- `limit_floor` = worst acceptable price (credit: lowest credit; debit: highest debit).
- `max_loss_worst` = loss if filled at `limit_floor`; always <= `risk_cap` -
  `exit_slippage_reserve` x quantity.
- `risk_cap` = min(`max_loss_abs` $1,000, `max_loss_bp_frac` x total_value) - `open_risk_usd`
  (the budget left for this entry; `risk_cap_total` is the cap before open risk). Above a
  12% ATM spread the candidate's `max_loss_worst` is also capped at $350. Long straddles
  are off: `order.structure` is always `iron_fly`.

Skip reasons (`ranked[].skip_reason`, first failing gate wins): `blocklisted`,
`symbol_mismatch`, `unverified_report_date`, `flagged:<flags>`, `price_below_min`,
`report_not_imminent`, `bad_expiry`, `insufficient_history`, `missing_atm_quotes`,
`spread_too_wide`, `intraday_move_too_large`, `regime_guard`, `long_straddle_off`,
`no_edge`, `already_open`, then structure/sizing: `no_valid_wings`, `max_loss_exceeds_cap`,
`no_buying_power`, `no_fillable_limit_range`, `no_structure`, `negative_ev`.

## exit snapshot
```json
{"as_of": "...Z", "minutes_since_open": 15,
 "account": {"total_value": 750.0},
 "positions": [{"symbol":"ARM", "structure":"iron_fly", "direction":"credit",
                "entry_price": 14.40, "opened":"2026-11-04",
                "expiry":"2026-11-06",
                "report_date":"2026-11-04", "timing":"pm",
                "provenance":"reconstructed",
                "legs":[{"option_id":"uuid","side_held":"short|long","quantity":1,
                         "bid":3.10,"ask":3.30,"strike":202.5,"type":"call|put"}]}]}
```
- `expiry` REQUIRED (missing -> exit 2). Leg `strike` and `type` REQUIRED.
- `report_date` + `timing` optional; enable the AMC/BMO rule. `provenance` optional,
  `"reconstructed"` for positions adopted by reconcile. `opened` = PT date of the broker
  opening order. `account` optional (breaker context only).

Exit rules: broken structure (unequal leg quantities, or a short with no same-type wing)
-> flatten now; long straddle up >= 50% -> exit now; today >= expiry -> exit now;
otherwise the session after the report once minutes_since_open >= 10 (pm: today >
report_date; am: today >= report_date). Without report_date/timing: exit when
reconstructed, opened missing, or opened < today.

## exit decision
```json
{"as_of":"...",
 "actions":[{"symbol":"ARM","structure":"iron_fly","quantity":1,
             "sequence":1, "group_id":"ARM-split-1",
             "close_legs":[{"option_id":"uuid","side":"buy","position_effect":"close","strike":202.5,"type":"call"}],
             "order_legs":[{"option_id":"uuid","side":"buy","position_effect":"close"}],
             "direction":"debit", "limit_start":3.20, "limit_worst":3.60, "limit_step":0.10,
             "width_cap":20.0, "hard_ceiling":20.50, "combined_cap":20.50,
             "naked_short": false, "leg_qty_mismatch": false,
             "trigger":"post_report_session: AMC report 2026-11-04, minutes_since_open=15",
             "reason":"post_report_session: ..."}],
 "holds":[{"symbol","leg_qty_mismatch","reason"}],
 "circuit_breaker": {...}}
```
- Work actions strictly by `sequence` (per symbol); do not start N+1 until N fills.
- `order_legs` go to the broker; `close_legs` are for reading.
- `width_cap` (W) = vertical width; `limit_start`/`limit_worst` of a debit close are
  clamped <= W. `hard_ceiling` = W + `exit_slippage_reserve`/100: never pay more per unit.
- Natural debit > W -> split into one action per vertical (put first, then call), same
  `group_id`, `combined_cap` = most the group may total, reason
  `split_verticals_natural_exceeds_width`.
- Broken structure -> `leg_qty_mismatch: true`, reason `partial_fill_flatten`:
  `naked_short: true` buybacks first (`sequence` 1, `width_cap`/`hard_ceiling` null,
  uncapped), then matched verticals (capped), then leftover longs.
- `trigger` = the exit rule that fired (normal and split actions).
- `holds[].reason`: `wait:` / `wait_market_open:` = re-run after the indicated minutes;
  `hold:` = not due.

## journal.jsonl (one JSON object per line, append-only)
Base: {"ts","event":"scan|entry_submitted|entry_filled|entry_cancelled|exit_submitted|exit_filled|halt|heal|calibrate",
"symbol","structure","order_id","price","quantity","implied_move","edge_ratio","realized_move","pnl","notes"}.
Extension keys (preserved, some read by the engine): `max_loss` (on entry_filled =
`order.max_loss_worst`; used by the max-loss streak; unknown = counted as max loss),
`direction`, `expiry`, `report_date`, `timing`, `opened`, `legs`, `provenance`,
`session_id`, `ref_key`, `ref_id`, `attempt`, `stage` (intent|ack), `sequence`, `group_id`,
`heal` ({"type", "as_event"?}). A `heal` with `as_event` in {entry_filled, exit_filled,
entry_cancelled, exit_cancelled, qty_adjust} counts as that event. Closed trades =
entry_filled paired FIFO per symbol with the next exit_filled.

## reconcile
Input snapshot:
```json
{"as_of":"...Z", "account":{...},
 "open_positions":[{"symbol","structure","opened","quantity","entry_price","expiry","direction","legs":[...]}],
 "recent_orders":[{"order_id","symbol","state","position_effect":"open|close","price","quantity","created_at","direction","legs":[...]}]}
```
`open_positions.quantity` = min leg quantity; `recent_orders.position_effect` top-level.
Output:
```json
{"as_of":"...", "consistent": true,
 "issues":[{"type":"orphan_position|missing_fill|stale_open_order|qty_mismatch","symbol",
            "fix":{"description","broker_action":null|{"action":"cancel_order","order_id"},"journal_event":{...}|null}}],
 "housekeeping":[...],
 "journal_appends":[...]}
```
Broker is the source of truth; the journal is repaired by appending `journal_appends`
verbatim (already includes housekeeping), never the reverse. `stale_open_order` events
are appended only after the broker confirms the cancel. Heals carry `report_date`,
`timing`, `expiry`, `opened`, `ref_id`, `legs` when known.

## calibrate
From closed trades in the journal: per-structure win rate, avg pnl, realized/implied
ratio. Shrink thresholds toward observed (bounded: sell_max_ratio in [0.70,0.95],
buy_min_ratio in [1.15,1.60]); require >= 8 closed trades before moving any threshold;
output proposed config diff, never write config directly.

## config keys referenced by the runbook
`wing_widths_pct`, `max_loss_abs`, `max_loss_bp_frac`, `exit_slippage_reserve` ($ per
unit, default 50), `cancel_by`, `market_holidays`, `market_early_closes`,
`max_expiry_days_after_report`, `exit_min_minutes_since_open`, `journal_path`.
