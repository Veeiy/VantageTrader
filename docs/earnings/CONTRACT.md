# Engine <-> Agent interface contract (v1)

The scheduled Claude session gathers data with Robinhood MCP tools, writes a
**snapshot JSON**, runs the engine CLI, and executes the engine's **decision JSON**
with Robinhood MCP tools. The engine never talks to the broker. All money values USD,
all percentages as fractions (0.095 = 9.5%).

## CLI
```
python -m vantage_trader.earnings score     --snapshot snap.json --config config/earnings.yaml   > decision.json
python -m vantage_trader.earnings exit      --snapshot snap.json --config config/earnings.yaml   > exit.json
python -m vantage_trader.earnings reconcile --snapshot snap.json --journal state/earnings/journal.jsonl > recon.json
python -m vantage_trader.earnings calibrate --journal state/earnings/journal.jsonl --config config/earnings.yaml > calib.json
python -m vantage_trader.earnings history   --bars bars.json --events events.json > moves.json
```
Exit code 0 = success (decision may be "no trade"); 2 = invalid input (agent must heal
the snapshot and retry); 3 = halted by circuit breaker.

## history input
bars.json:   {"SYMBOL": [{"date":"YYYY-MM-DD","close":float,"interpolated":bool}, ...]}
events.json: {"SYMBOL": [{"date":"YYYY-MM-DD","timing":"am"|"pm"}, ...]}   (past reports only)
moves.json:  {"SYMBOL": {"moves":[float signed fraction,...], "dates":[...], "skipped":[{"date","reason"}]}}
Interpolated bars are skipped (treated as missing); if the needed bar is missing, skip that event with a reason.

## snapshot (score)
```json
{
  "as_of": "2026-11-04T19:55:00Z",
  "account": {"account_number":"...", "buying_power":750.0, "total_value":750.0,
              "human_must_approve_trades": false},
  "open_positions": [ {"symbol":"ARM","structure":"iron_fly","opened":"2026-11-04"} ],
  "candidates": [
    {
      "symbol": "ARM", "report_date":"2026-11-04", "timing":"pm", "verified": true,
      "spot": 202.49,
      "expiry": "2026-11-06",
      "historical_moves": [-0.062,-0.134,-0.012,0.057,-0.101,0.074],
      "intraday_move": 0.012,
      "chain": [
        {"strike":202.5, "call":{"id":"uuid","bid":11.45,"ask":11.55,"oi":103},
                         "put": {"id":"uuid","bid":11.15,"ask":11.35,"oi":129}},
        ...  // at least ATM +/- the widest wing in config
      ],
      "flags": []   // e.g. ["pending_litigation_ruling"] -> skip
    }
  ]
}
```

## decision (score output)
```json
{
  "status": "trade" | "no_trade" | "halted",
  "reason": "string",
  "ranked": [ {"symbol","edge_ratio","implied_move","avg_hist_move","action":"sell|buy|skip","skip_reason", "ev_per_dollar_risk"} ],
  "order": null | {
    "symbol":"ARM", "structure":"iron_fly"|"long_straddle",
    "quantity": 1, "direction":"credit"|"debit", "expiry":"2026-11-06",
    "legs":[{"option_id":"uuid","side":"sell","position_effect":"open","strike":202.5,"type":"call"}, ...],
    "limit_start": 14.60, "limit_floor": 13.00,      // credit: floor = worst acceptable
    "limit_step": 0.10, "max_loss": 540.0, "max_profit": 1460.0,
    "breakevens":[187.9, 217.1], "hist_win_rate": 0.67,
    "cancel_by": "12:50 America/Los_Angeles"
  }
}
```
For debit orders `limit_floor` is the worst acceptable (highest) debit.

## exit snapshot -> exit decision
Snapshot adds `positions`: [{"symbol","structure","legs":[{"option_id","side_held":"short|long","quantity","bid","ask"}],
"entry_price","direction","opened"}] and `minutes_since_open`.
Output: {"actions":[{"symbol","close_legs":[{"option_id","side","position_effect":"close"}],
"direction","limit_start","limit_worst","limit_step","reason"}]}.
Rules: exit the session after the report (AMC report -> next morning; BMO -> same day
after open) once minutes_since_open >= 10; always exit before the expiry day 12:00 PT;
if a long straddle is up >= 50% take it immediately at open.

## journal.jsonl (one JSON object per line, append-only)
{"ts","event":"scan|entry_submitted|entry_filled|entry_cancelled|exit_submitted|exit_filled|halt|heal|calibrate",
 "symbol","structure","order_id","price","quantity","implied_move","edge_ratio","realized_move","pnl","notes"}

## reconcile
Input: snapshot with broker `open_positions` + `recent_orders`; journal.
Output: {"consistent":bool,"issues":[{"type":"orphan_position|missing_fill|stale_open_order|qty_mismatch","symbol","fix"}]}
Broker is the source of truth; the journal is repaired to match, never the reverse.

## calibrate
From closed trades in the journal: per-structure win rate, avg pnl, realized/implied
ratio. Shrink thresholds toward observed (bounded: sell_max_ratio in [0.70,0.95],
buy_min_ratio in [1.15,1.60]); require >= 8 closed trades before moving any threshold;
output proposed config diff, never write config directly.
