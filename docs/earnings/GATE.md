# Entry gate in code (`gate`, proposals P004 and P011)

`gate` runs ONE earnings candidate through every entry rule of RULES_CHANGELOG v1.1 to
v1.7 and the 2026-11-11 decisions, and prints a decision record. It never places orders
and never reads the market. Run it on every candidate before entry and compare it with
the manual gate: a disagreement blocks the entry until it is explained.

```
PYTHONPATH=src python -m vantage_trader.earnings gate --input candidate.json [--config config/earnings.yaml] [--journal state/earnings/journal.jsonl]
cat candidate.json | PYTHONPATH=src python -m vantage_trader.earnings gate
```

Exit code: `0` may be entered (`action: "sell"`), `3` blocked (`action: "no_trade"`),
`2` bad input (stdout `{"error": ...}`). The journal is read only, for the circuit-breaker
streaks.

## What it checks (each gate reported with its number, value, limit and pass/fail)

| # | Gate | Passes when |
|---|---|---|
| 1 | blocklist | symbol not in the blocklist (TSLA always) |
| 2 | price | spot >= $10 |
| 3 | history | at least 4 past earnings moves |
| 4 | edge_ratio | avg abs past move / (0.85 x ATM-equivalent straddle / spot) <= 0.85; at 1.25 or more the reason is `long_straddle_off` (never a buy) |
| 5 | atm_spread | (ask - bid) / mid <= 25% for the call, the put and the straddle (the worst of the three is used) |
| 6 | regime | 20-session avg abs daily move < 1.25 x avg past earnings move |
| 7 | intraday | abs(spot / prev_close - 1) <= 5%; 5% to 7% only with `sector_same_direction: true` and no stock-news flag; above 7% blocks |
| 8 | news | no stock-specific flag (`big_intraday_move` is a price fact covered by gate 7) |
| 9 | macro_veto | not set |
| 10 | circuit_breaker | not set, account value >= $400, no 2 max losses / 3 losses in a row in the journal |
| 11 | sector | `sector` not in `sectors_entered_today` (checked only when both are given) |
| 12 | structure | wings given on both sides, 0 < mid credit < width, a fillable limit range |
| 13 | add_centered | an add only (`held` given): same body strike as the open tranche, and spot within 0.25 x the body straddle of it. A first entry passes |
| 14 | name_risk | max loss on the name (held + the contracts entered now, at the credit floor) <= $350, and at least one contract may be entered at this check-in |
| 15 | risk_budget | open_risk_usd + max loss at the credit floor + $50 reserve per contract <= min($1,000, 0.93 x account value) |

Band (a label only since P020, 2026-11-11: any passing name may be entered at any check-in
on its entry day): `tight` (edge <= 0.70), `final_sweep` (0.70 to 0.85), `no_edge` (above
0.85), `long_straddle_off` (1.25 or more).

Contracts (rules v1.7 and v1.8, `sizing.plan`): sized by risk. The name's target is a max loss of
20% of account value (12% until v1.8), never above $350; new contracts are (target - max loss held) / max
loss of one contract, rounded to the nearest whole number, and never more than fits $350
per name, the risk budget and 10 contracts. One contract is always allowed on a name with
nothing held. Output: `contracts` (enter this many now), `contracts_planned` (what the name
may still add in all), `contracts_later` (the part that waits for the final window) and
`sizing` (target, limits, the binding limit).

Phase: `early` before 11:30 PT, `final` from 11:30 PT. In the early phase a name carries at
most half its target, rounded down (one contract is still allowed). The CLI takes the phase
from the clock when the candidate has no `phase`; `phase_source` says which.

An add (scale in): give `held` = `{"quantity", "max_loss_usd", "K"}` of what is already open
on the name, and count that tranche in `open_risk_usd`. The gate then checks the add like a
new entry, plus gate 13, and skips the sector rule. Reasons a passing name still gets no
add: `name_target_reached`, `early_tranche_full` (wait for 11:30 PT), `add_off_center`,
`add_different_body`, `name_risk_cap`, `max_loss_exceeds_cap`, `max_quantity`.

Implied move (P011): the body straddle is converted to its at-the-money equivalent,
`sigma = implied_sigma(spot, K, body_straddle_mid)`, `atm = straddle(spot, spot, sigma)`,
`implied_move = 0.85 x atm / spot`. The raw figure is reported as `implied_move_raw`.

Max loss is checked at the credit floor `max(natural, 0.92 x mid)`, the worst fill the
execution rules accept; `max_loss.mid` and `max_loss.natural` are reported next to it.

## Input

```json
{"symbol": "LUNR", "timing": "am", "spot": 12.17, "prev_close": 11.81, "K": 12,
 "call": {"bid": 0.84, "ask": 0.97}, "put": {"bid": 0.63, "ask": 0.75},
 "wings": {"call_strike": 13.5, "put_strike": 10.5,
           "call": {"bid": 0.32, "ask": 0.36}, "put": {"bid": 0.12, "ask": 0.23}},
 "hist_moves": [0.224211, -0.042857, 0.100462, 0.044174, 0.023543, 0.035988],
 "regime_20d": 0.0615, "flags": [], "sector_same_direction": false,
 "account_value": 1339, "open_risk_usd": 172}
```

Required: `symbol`, `spot`, `prev_close`, `K`, `call`, `put`, `hist_moves` (oldest first),
`regime_20d`, `account_value`, `open_risk_usd` (max loss PLUS exit reserves of every open
position, as positions.json records them). Optional: `timing`, `wings` (without them the
candidate is blocked with `no_wings`), `flags` (list of risk-sentinel flags, or an object
of booleans), `sector_same_direction` (default false), `macro_veto` and `circuit_breaker`
(true or a reason string blocks), `sector` + `sectors_entered_today`, `tick` (default
config `tick`, used only for `limit_start` / `limit_floor`).

## Output (LUNR, 2026-11-11 07:05 PT re-quote; abridged)

```json
{"symbol": "LUNR", "action": "sell", "reason": "enter at the final sweep", "blocked_by": [],
 "band": "final_sweep",
 "metrics": {"avg_hist_move": 0.078539, "implied_move": 0.111779, "edge_ratio": 0.7026,
             "implied": {"implied_move_raw": 0.111401, "body_offset_pct": -0.013969, "...": "..."},
             "spread_pct": {"call": 0.1436, "put": 0.1739, "straddle": 0.1567, "worst": 0.1739},
             "intraday_move": 0.030483, "regime_ratio": 0.7831},
 "gates": [{"n": 1, "gate": "blocklist", "pass": true, "value": "LUNR", "limit": ["TSLA"]}, "..."],
 "fly": {"credit_mid": 1.08, "credit_natural": 0.88, "credit_floor": 0.9936, "width": 1.5,
         "limit_start": 1.1, "limit_floor": 1.0, "breakevens_mid": [10.92, 13.08], "...": "..."},
 "contracts": 1, "contracts_planned": 3, "contracts_later": 2,
 "sizing": {"target": 160.68, "phase": "early", "planned": 3, "now": 1, "later": 2,
            "binding": "name_target_reached", "...": "..."},
 "max_loss": {"mid": 42.0, "natural": 62.0, "floor": 50.64, "per_contract_floor": 50.64,
              "name_total_floor": 50.64},
 "breakevens": [10.92, 13.08],
 "risk": {"risk_cap": 1000.0, "open_risk_usd": 172.0, "budget_before": 828.0,
          "exit_reserve_per_contract": 50.0, "spread_band_cap": 350.0,
          "name_risk_cap": 350.0, "name_target": 160.68,
          "this_trade_usd": 100.64, "budget_left": 727.36}}
```
(Early phase: 1 of the 3 planned contracts now, 2 in the final window. The same candidate
with `"phase": "final"` returns `"contracts": 3`.)

`score` (several candidates from a full chain) applies the same rules where its snapshot
carries the inputs: see the docstring of `scoring.py` and CONTRACT.md.
