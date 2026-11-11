# Replay: scoring past earnings events from option price history

Live trades give two or three observations a day. A replay prices what a short iron fly
held through a past report would have made, from the broker's own option price history.
Proposal P007 (Brad, 2026-11-10: "Yes to p006, 007, 005").

The same method scores the names that were not traded each day (REFLECTION.md, step 2).

## Division of labour
- **Agents collect raw prices.** Read-only Opus agents, one JSON object per event. They do
  no arithmetic beyond one sum (the straddle, to place the wings).
- **Code computes everything else.** `vantage_trader/earnings/replay.py`, run with
  `PYTHONPATH=src python -m vantage_trader.earnings replay ...`. Credit, close cost, P/L,
  implied move, edge ratio and gates never depend on an agent's arithmetic.

## Method per event
1. Entry day E = the report date for an after-close report, the trading day before for a
   before-open report. Exit day X = the next trading day.
2. Expiry = the first Friday on or after X. A name with no options on that Friday is
   `no_weekly`: the engine's expiry rule (7 days after the report at most) would skip it.
3. Stock: 30-minute bars. Entry price = close of E's last bar. Exit prices = close of X's
   first bar (`b1`, 10:00 ET) and second bar (`b2`, 10:30 ET). `b2` is the headline: the
   first bar of the day is usually a single early print.
4. Body strike K = the listed strike nearest the entry price. Body prices from 30-minute
   option bars at the same three times.
5. Wings at about 1x and 2x the entry straddle (`fly1`, `fly2`).
6. History, point in time: only earnings reports before this one count
   (`get_earnings_results` plus daily bars, the engine's own `history` code). Edge ratio =
   average past move / (0.85 x implied move). The regime guard uses the 20 sessions that
   end the day before E.

## What the data really is (learned 2026-11-10)
- Option bars are **last trades**. There is no volume and no usable "interpolated" flag.
  A bar with no trade prints **0.01**. Any print at or below 0.011 is treated as missing.
- At-the-money prints are mostly usable. **Wing prints are sparse and often stale.**
- So the headline result uses **real body prices and model wings**: each wing is priced
  from the body's implied total stdev times a multiplier fitted to the wing prints that
  do exist (`calibrate_wings`; fitted values were 1.01 at 1x and 1.02 to 1.09 at 2x, so
  the wings are priced almost exactly like the body). The all-printed variant (`traded`)
  is kept as a cross-check; on the 32 events where both exist they agree in total within
  about $35.
- Two guards on the body: every leg is floored at intrinsic value, and put-call parity is
  checked (`|(call - put) - (spot - strike)|` within 20% of the straddle). Events that
  fail parity at the entry or at `b2` are flagged and left out of the `clean` statistics.
- The implied move is the at-the-money straddle at the body's implied stdev, not the raw
  straddle: with a coarse strike grid the body can sit off the money and its straddle
  then holds intrinsic value.

## Limits (say them every time results are quoted)
- No bid-ask cost in the prices. `--cost-frac 0.07` takes 7% of the entry credit off each
  result (the first three live entries filled about 3.5% under mid; the exit side is
  assumed equal until it is measured).
- The spread gate and the news gate cannot be replayed.
- One contract per event, filled at the printed prices.
- About two thirds of liquid-option earnings names list monthly expiries only at
  Robinhood, so a sample of the calendar prices far fewer events than it draws.

## Files (one folder per replay under `state/earnings/replay/`)
| File | Content |
|---|---|
| `events.json` | `symbol, report_date, timing, E, X, expiry, E_prev` per event |
| `raw.jsonl` | raw prices as collected (shape below) |
| `reports.jsonl` | past report dates per symbol: `[date, "am"/"pm", has_actual_eps]` |
| `bars.json.gz` | daily closes per symbol (engine `history` format) |
| `derived.jsonl` | one derived record per event (output of `replay`) |
| `summary.json` | `clean`, `all_priced`, `clean_after_cost_7pct_of_credit` |
| `FINDINGS.md` | what it showed, with counts |
| `brief_*.txt` | the exact agent briefs used |

Raw record:
```
{"symbol", "K", "w1c_strike", "w1p_strike", "w2c_strike", "w2p_strike",
 "stock": {"entry", "x_open", "b1", "b2"},
 "legs": {"kc"|"kp"|"w1c"|"w1p"|"w2c"|"w2p": {"entry", "b1", "b2", "interp": []}},
 "quality", "status": "ok"|"no_weekly"|"no_data"}
```
Only `stock`, `K`, `kc` and `kp` are needed for the headline result. Wing strikes without
wing prices are enough for the model variant.

## Run it
```
D=state/earnings/replay/2026-11-10_unbiased
PYTHONPATH=src python -m vantage_trader.earnings replay --events $D/events.json \
  --raw $D/raw.jsonl --bars $D/bars.json.gz --reports $D/reports.jsonl \
  --macro-entry-dates 2026-10-13,2026-11-05 --out $D/derived.jsonl
PYTHONPATH=src python -m vantage_trader.earnings replay-summary --input $D/derived.jsonl [--all] [--cost-frac 0.07]
```
`--macro-entry-dates` = entry days with a tier-1 release before the next 06:45 PT exit
(the day before CPI and before payrolls). Without `--bars`, an event row may carry
`avg_hist_move`, `n_hist`, `prior_close` and `regime20` from the day's scan.

## Cost, and how to keep it down
- 2026-11-10: 9 pricing agents x 12 events plus 2 history agents and the sampling agents
  used about 2.0M tokens and priced 36 of 108 events. An agent cost about 150k tokens
  whether 3 or 6 of its 12 events could be priced.
- Next time (lite method): (1) check each name's expiry list first with one
  `get_option_chains` call and drop names without the Friday expiry; (2) collect only
  the stock bars and the two body options; wings come from the model; (3) pull history
  only for the names that priced. Estimated 15k to 20k tokens per priced event.
- Daily scoring of untraded names uses the lite method: three small calls a name.
- Facts that save calls: an exact-strike query with `state="expired"` returns the call
  and the put; never query a whole expiry without a strike (about 5k tokens per side);
  events with the same E and X can share one stock call (up to 10 symbols); all bars
  calls of one event use the same start (start of E's last bar) and end (end of X's
  second bar). US daylight time ended 2026-11-01: sessions are 13:30-20:00 UTC before,
  14:30-21:00 UTC after.
