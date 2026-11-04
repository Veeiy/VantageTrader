# Earnings engine: head agent + monitor agents (v1)

This file defines who does what inside one scheduled run. `RUNBOOK.md` defines the
phase procedures and points here for every dispatch. `CONTRACT.md` defines the JSON
the engine reads and writes. If anything here conflicts with a hard cap in
`BLUEPRINT.md` or `config/earnings.yaml`, the cap wins.

## 1. Roles and authority

| Agent | Model | Count per run | May do | Must never do |
|---|---|---|---|---|
| HEAD (the scheduled session itself) | Opus 5.5 (`claude-opus-5-5`) | 1 | Run `score`, `exit`, `calibrate` (and re-run `reconcile`, `history`); call `review_option_order`, `place_option_order`, `cancel_option_order`; write `state/earnings/journal.jsonl`; git commit/push; message Brad | Override a hard cap, force a trade the engine rejected, trade any account other than the agentic "MCP" one |
| calendar-scout | `opus` | 0-1 | Read-only Robinhood market-data tools | Any order tool, any journal/git write |
| vol-analyst | `opus` | 1 per batch of ~5 candidates | Read-only market-data tools; run `history` locally | Any order tool, `score`/`exit`/`calibrate`, journal/git writes |
| risk-sentinel | `opus` | 0-1 | Web search/fetch, read-only quote tools | Any order tool, approving a trade, journal/git writes |
| position-monitor | `opus` | 1 | Read-only account/position/order/P&L tools; run `reconcile` locally | Any order tool, journal/git writes |
| second-opinion (on demand) | `opus` | 0-1 | Same as vol-analyst, for one symbol | Same as vol-analyst |
| replacement (on demand) | `opus` | 0-2 | Same as the role it replaces | Same as the role it replaces |

Rules:
- **Single writer.** Only the head places, reviews, or cancels orders, and only the head
  appends to the journal or pushes to git. No two agents can race on an order.
- **Read-only engine commands are shared.** `history` and `reconcile` only print JSON, so
  monitors may run them. The head re-runs `reconcile` itself before acting; the
  position-monitor's copy is advisory.
- **Binding decision = engine output + hard caps.** Monitors and the head may VETO
  (skip a symbol, or skip all entries for the day). Nobody may override a cap, resize
  past the engine's quantity, or trade a symbol the engine did not return as `order`.
- **Any risk-sentinel flag on a symbol = that symbol is skipped.** The head copies the
  flags into the candidate's `flags` array (the engine skips flagged names) and also
  enforces the skip itself.
- **Cap: max 8 subagents per run**, replacements and second opinions included. If the
  cap is reached, the head does the remaining read-only work itself.

## 2. Dispatch plan per phase

All monitors in a wave are launched in ONE assistant message containing multiple
`Agent` tool calls (they run concurrently). Each call sets `model: "opus"` and pastes
the role brief from section 4 with the `{{placeholders}}` filled in. Subagents share no
context with the head, so the brief is the whole world to them.

| Session | Wave | Agents (one message) | Head does while waiting / after |
|---|---|---|---|
| 06:45 SCAN+EXIT | A | position-monitor, calendar-scout | After A returns: run RECONCILE (RUNBOOK 0.7), then EXIT (RUNBOOK phase 3) |
| 06:45 SCAN+EXIT | B (as soon as calendar-scout returns) | vol-analyst x ceil(N/5) in `full` mode, risk-sentinel (all N symbols + market) | Keep walking any EXIT order between polls; when B returns, merge, validate, run `score` |
| 12:00 ENTRY | A | position-monitor, vol-analyst x ceil(N/5) in `refresh` mode, risk-sentinel | If any position is open, run EXIT first (expiry-day shorts before anything else); load scan artifacts, check duplicate-run guard |
| 12:00 ENTRY | C (only if `status: trade`) | second-opinion on the engine's chosen symbol | Compare (section 5), then review/place |
| Saturday CALIBRATE | A | position-monitor (for realized P&L cross-check) | Run `calibrate` |
| any | heal | replacement for a failed role, scoped to the failed symbols only | See section 6 |

N = number of candidates from calendar-scout (SCAN) or from
`state/earnings/scan/<date>/candidates.json` (ENTRY). If N = 0 in SCAN, skip wave B
(no vol-analyst, no risk-sentinel). If N > 25, keep the top 25 by market cap so the
batch count stays <= 5.

Typical count: SCAN+EXIT 4-6 subagents, ENTRY 3-5. Hard stop at 8.

## 3. Return envelope (all roles)

Every subagent's final message must be exactly one JSON object, no prose, no code
fence:

```json
{
  "role": "calendar-scout | vol-analyst | risk-sentinel | position-monitor | second-opinion",
  "ok": true,
  "as_of": "2026-11-04T14:52:10Z",
  "data": { },
  "errors": [ {"step": "string", "tool": "string", "message": "string", "retryable": true} ],
  "sources": [ "tool or URL used, one per entry" ]
}
```

It must ALSO write the identical object to
`/tmp/earnings-run/frag/<role>-<batch or 0>.json` (the head reads the file if the
inline reply was truncated). `ok` is true only if every requested item is present in
`data`; partial results set `ok: false` and list the gaps in `errors`.

Head acceptance test: parses as JSON, `role` matches, `ok === true`, `as_of` within 15
minutes, and the role-specific checks in section 4. Anything else is a failed monitor
(section 6).

### data schemas

**calendar-scout**
```json
{"amc_date": "2026-11-04", "bmo_date": "2026-11-05",
 "candidates": [{"symbol": "ARM", "report_date": "2026-11-04", "timing": "pm",
                 "verified": true, "spot": 202.49, "chain_symbol": "ARM",
                 "market_cap": 2.1e11}],
 "dropped": [{"symbol": "XYZ", "reason": "price<10 | tsla_blocklist | no_options | timing_unknown | not_high_market_cap"}]}
```

**vol-analyst**
```json
{"mode": "full | refresh",
 "fragments": [ {
    "symbol": "ARM", "report_date": "2026-11-04", "timing": "pm", "verified": true,
    "spot": 202.49, "expiry": "2026-11-06",
    "historical_moves": [-0.062, -0.134, -0.012, 0.057, -0.101, 0.074],
    "intraday_move": 0.012,
    "chain": [ {"strike": 202.5,
                "call": {"id": "uuid", "bid": 11.45, "ask": 11.55, "oi": 103},
                "put":  {"id": "uuid", "bid": 11.15, "ask": 11.35, "oi": 129}} ],
    "flags": [],
    "_meta": {"chain_symbol": "ARM", "prev_close": 200.09,
              "oldest_quote_updated_at": "2026-11-04T14:50:31Z",
              "strike_range": [180.0, 225.0], "missing_strikes": [],
              "moves_skipped": [{"date": "2025-02-05", "reason": "interpolated bar"}]}
 } ],
 "moves": { "ARM": {"moves": [], "dates": [], "skipped": []} },
 "failed": [ {"symbol": "XYZ", "reason": "string"} ]}
```
Each fragment (minus `_meta`) must match the CONTRACT.md candidate shape exactly. The
head strips `_meta` before writing the snapshot.

**risk-sentinel**
```json
{"market_regime": {"summary": "one line", "spy_move": -0.004, "qqq_move": 0.002,
                   "soxx_move": 0.011, "vix": 17.8,
                   "macro_events": [{"name": "FOMC decision", "time_pt": "2026-11-04T11:00", "between_entry_and_exit": false}],
                   "veto_all": false, "veto_reason": null},
 "symbols": {"ARM": {"flags": [], "notes": "nothing material", "sources": ["https://..."]}}}
```
Flag vocabulary (strings that go straight into CONTRACT `flags`):
`pending_litigation_ruling`, `guidance_preannounced`, `trading_halt`,
`earnings_date_unconfirmed`, `earnings_date_moved`, `pending_merger_or_tender`,
`big_intraday_move` (|today's move| >= 5%), `news_shock` (major unscheduled news in the
last 24h), `regulatory_decision_pending`, `other:<short_slug>`.
`veto_all: true` when: a tier-1 macro release (FOMC decision, CPI, nonfarm payrolls)
lands after today's 12:00 PT and before the next 06:45 PT exit; or a market-wide halt or
circuit breaker today; or |SPY move today| >= 2%; or VIX >= 30 or VIX up >= 15% today.

**position-monitor**
```json
{"account": {"account_number": "full number, head-only", "last4": "3413", "nickname": "MCP",
             "agentic_allowed": true, "option_level": "option_level_3",
             "buying_power": 750.0, "total_value": 750.0,
             "human_must_approve_trades": false},
 "other_accounts_seen": 2,
 "positions": [ {"symbol": "ARM", "chain_symbol": "ARM", "expiry": "2026-11-06",
                 "quantity": 1, "entry_price": 14.40, "direction": "credit",
                 "opened": "2026-11-04", "opening_order_id": "uuid or null",
                 "legs": [{"option_id": "uuid", "strike": 202.5, "type": "call",
                           "side_held": "short", "quantity": 1, "avg_price": 11.50}],
                 "structure_guess": "iron_fly | iron_condor | long_straddle | long_strangle | unknown"} ],
 "open_orders": [ {"order_id": "uuid", "symbol": "ARM", "state": "queued", "direction": "credit",
                   "position_effect": "open", "price": 14.60, "quantity": 1,
                   "created_at": "...", "ref_id": "uuid or null",
                   "legs": [{"option_id": "uuid", "side": "sell", "position_effect": "open"}]} ],
 "recent_orders": [ "same shape, last 5 trading days, all states" ],
 "realized_pnl": {"period": "string", "total": 0.0, "by_symbol": {}},
 "reconcile": {"consistent": true, "issues": []},
 "reconcile_snapshot_path": "/tmp/earnings-run/recon_snapshot.json"}
```
Head check: exactly one account with `agentic_allowed: true` and nickname `MCP`, last4
`3413`. Anything else = HALT (RUNBOOK 0.4). `option_level` other than `option_level_3`
= HALT entries. Position `quantity` = min leg quantity; `entry_price` = net average
price per unit of the opening order; `opened` = PT date of the opening order's
`created_at` (never a heal or snapshot timestamp); `position_effect` on orders is
top-level, copied from the legs.

**second-opinion**
```json
{"symbol": "ARM", "spot": 202.49, "expiry": "2026-11-06", "atm_strike": 202.5,
 "straddle_mid": 22.75, "implied_move": 0.0955, "avg_hist_move": 0.0733,
 "n_moves": 6, "moves": [-0.062, -0.134, -0.012, 0.057, -0.101, 0.074],
 "edge_ratio": 0.768}
```

## 4. Role briefs (paste verbatim, fill `{{...}}`)

Every brief starts with this common header. Paste it first, then the role section.

```
You are a READ-ONLY monitor agent for an automated earnings-options system. You share no
context with the agent that started you; this message is everything you know.
Repo: {{REPO_DIR}} (Python engine already installed). Work dir: /tmp/earnings-run/.
Current time: {{NOW_PT}} America/Los_Angeles ({{NOW_UTC}}). Market hours 06:30-13:00 PT.
ABSOLUTE RULES:
- NEVER call review_option_order, place_option_order, cancel_option_order, or any other
  order, transfer, watchlist, alert, or settings tool. Read-only tools only.
- Never write to state/earnings/, never run git commit/push, never run the engine's
  score, exit, or calibrate commands.
- Never ask questions; if something fails, retry MCP calls up to 3 times with 2s/4s/8s
  waits, then record it in "errors" and continue with the rest.
- Some tool outputs are huge and get saved to a file: read them with jq or python, never
  paste them whole.
- Your FINAL message must be exactly one JSON object (no prose, no code fence):
  {"role": "...", "ok": bool, "as_of": "<UTC ISO>", "data": {...}, "errors": [...], "sources": [...]}
  Also write that same object to /tmp/earnings-run/frag/{{ROLE}}-{{BATCH}}.json.
  ok=true only if every requested item is in data.
- Finish within {{MINUTES}} minutes. Return partial data with ok=false rather than run over.
```

### calendar-scout
```
ROLE: calendar-scout.
Goal: list earnings reports that land between today's close and tomorrow's open.
1. Call get_earnings_calendar(start_date="{{TODAY}}", days={{DAYS_TO_NEXT_TRADING_DAY_PLUS_1}},
   filter="high_market_cap"). Output may be saved to a file; inspect one element with
   jq to learn field names first.
2. Keep: report date {{TODAY}} with timing "pm" (after close), and report date
   {{NEXT_TRADING_DAY}} with timing "am" (before open). Drop anything else.
3. Drop TSLA always (reason tsla_blocklist). Drop timing missing/unknown (timing_unknown).
4. get_equity_quotes in batches of <= 20 symbols: drop last price < 10 (price<10).
5. For survivors call get_option_chains(symbol): drop if no chain or no tradable
   expirations (no_options). Record chain_symbol.
6. For each survivor call get_earnings_results(symbol) and find the upcoming report
   (eps.actual is null). Set verified from that record; if its date or timing disagrees
   with the calendar, keep the earnings_results values and set verified=false.
Return data: {"amc_date","bmo_date","candidates":[{"symbol","report_date","timing",
"verified","spot","chain_symbol","market_cap"}],"dropped":[{"symbol","reason"}]}.
Sort candidates by market_cap desc (null last).
```

### vol-analyst (`full` mode, SCAN)
```
ROLE: vol-analyst, mode=full, batch={{BATCH}}.
Symbols (with report_date, timing, verified, chain_symbol): {{CANDIDATES_JSON}}
Widest wing fraction: MAX_WING_PCT={{MAX_WING_PCT}} (max of config wing_widths_pct).
Per symbol WING_WIDTH_DOLLARS = ceil(MAX_WING_PCT * spot); the chain must cover
ATM +/- WING_WIDTH_DOLLARS plus ONE more listed strike beyond on each side.
For EACH symbol:
1. get_earnings_results(symbol): past reports are those with eps.actual not null and
   date < {{TODAY}}. Build events {"SYMBOL":[{"date":"YYYY-MM-DD","timing":"am"|"pm"}]}.
2. get_equity_historicals(symbols<=10, start_time="{{START_20M}}", end_time="{{TODAY}}",
   interval="day"). Build bars {"SYMBOL":[{"date":begins_at[:10],"close":float(close_price),
   "interpolated":bool}]}. interpolated=true if the bar says so, OR it is the last bar
   and duplicates the previous bar's date or close, OR its date is {{TODAY}} (partial day).
3. Write /tmp/earnings-run/b{{BATCH}}/bars.json and events.json, then run from {{REPO_DIR}}:
   python -m vantage_trader.earnings history --bars /tmp/earnings-run/b{{BATCH}}/bars.json --events /tmp/earnings-run/b{{BATCH}}/events.json > /tmp/earnings-run/b{{BATCH}}/moves.json
   Exit code 2 = bad input: read "error" from moves.json (stdout), fix, retry (max 2).
   historical_moves = moves[SYMBOL].moves (all of them, oldest to newest).
4. get_equity_quotes([symbol]): spot = last trade price; prev_close from the quote
   (fallback: last non-interpolated close before today). intraday_move = spot/prev_close - 1.
5. get_option_chains(chain_symbol): expiry rule by timing. pm (AMC): first expiration
   date strictly AFTER report_date. am (BMO): first expiration date ON OR AFTER report_date.
6. Strikes: call get_option_instruments(chain_symbol, expiration_dates=expiry) without
   strike_price first; if it returns the full list, take every strike within
   ATM +/- WING_WIDTH_DOLLARS plus one listed strike beyond each side. If it
   requires strike_price, probe exact strings like "202.5000":
   start at spot rounded to 0.5/1/2.5/5 and walk neighbors both ways; real strikes are
   often not round numbers. Each strike needs BOTH a call id and a put id.
7. get_option_quotes(instrument_ids<=20 per call) for all ids. bid/ask from the quote,
   oi = open_interest (0 if absent, and say so in errors). If any updated_at is older
   than 2 minutes during market hours, or bid and ask are both 0 on a strike within
   5% of spot, re-pull those ids up to 3 times.
8. Fragment = {symbol, report_date, timing, verified, spot, expiry, historical_moves,
   intraday_move, chain:[{strike, call:{id,bid,ask,oi}, put:{id,bid,ask,oi}}] sorted by
   strike, flags:[], _meta:{chain_symbol, prev_close, oldest_quote_updated_at,
   strike_range, missing_strikes, moves_skipped}}.
Return data {"mode":"full","fragments":[...],"moves":{...},"failed":[{"symbol","reason"}]}.
A symbol you could not complete goes in failed, not in fragments.
```

### vol-analyst (`refresh` mode, ENTRY)
```
ROLE: vol-analyst, mode=refresh, batch={{BATCH}}.
Input per symbol (from this morning's scan, includes historical_moves, expiry, and
the chain option ids): {{SCAN_FRAGMENTS_JSON}}
For EACH symbol: re-pull get_equity_quotes (spot, prev_close, intraday_move =
spot/prev_close - 1) and get_option_quotes for every id in its chain (<=20 per call).
MAX_WING_PCT={{MAX_WING_PCT}}. If spot moved so far that ATM +/- ceil(MAX_WING_PCT * spot)
plus one listed strike beyond each side is no longer covered, add the missing
strikes via get_option_instruments (same method: no strike_price first, then exact
probes like "202.5000"). Apply the same stale/zero re-pull rule (updated_at older than
2 min, or zero bid and ask within 5% of spot: re-pull up to 3x).
Keep historical_moves, expiry, report_date, timing, verified unchanged.
Return data {"mode":"refresh","fragments":[...same shape as full mode...],"moves":{},
"failed":[...]}.
```

### risk-sentinel
```
ROLE: risk-sentinel. You only raise flags. You cannot approve or recommend a trade.
Symbols with report date/timing: {{CANDIDATES_JSON}}
Entry would be today ~12:00 PT; exit would be the next session after each report.
1. Market: get_equity_quotes(["SPY","QQQ","SOXX"]) for today's move vs previous close;
   VIX via get_index_quotes if available, else note vix=null. Search the web for today's
   and tomorrow-morning macro calendar (FOMC, CPI, PPI, nonfarm payrolls, major Fed
   speakers) and any market-wide halt.
2. Per symbol: search recent news (last 7 days) for: pending court or litigation
   rulings, regulatory decisions (FDA/FTC/DOJ), guidance pre-announcements, earnings date
   changes, trading halts, pending merger/tender, other shocks. Check today's move with
   get_equity_quotes.
3. Use only these flags: pending_litigation_ruling, guidance_preannounced, trading_halt,
   earnings_date_unconfirmed, earnings_date_moved, pending_merger_or_tender,
   big_intraday_move (|today| >= 5%), news_shock, regulatory_decision_pending,
   other:<short_slug>. When unsure whether something is material, flag it and explain
   in notes. Every flag needs a source URL or tool name.
4. veto_all=true if a tier-1 macro release (FOMC decision, CPI, nonfarm payrolls) falls
   after today 12:00 PT and before tomorrow 06:45 PT, or there was a market-wide halt
   today, or |SPY today| >= 2%, or VIX >= 30, or VIX up >= 15% today.
Return data {"market_regime":{"summary","spy_move","qqq_move","soxx_move","vix",
"macro_events":[{"name","time_pt","between_entry_and_exit"}],"veto_all","veto_reason"},
"symbols":{"SYM":{"flags":[],"notes","sources":[]}}}. Every input symbol must appear.
```

### position-monitor
```
ROLE: position-monitor.
1. get_accounts. Select the ONE account with agentic_allowed=true AND nickname "MCP".
   If none or more than one, return ok=false with errors explaining; do not guess.
   Record its option_level (expected "option_level_3").
   Use only that account_number in every later call. Count the others as
   other_accounts_seen and ignore them completely.
2. get_portfolio(account): buying_power (prefer option buying power if a separate
   field exists) and total_value. get_trade_approval_setting: human_must_approve_trades.
3. get_option_positions(account_number, nonzero=true). Group legs by chain symbol and
   expiry. structure_guess: 4 legs, short call+put same strike with long wings =
   iron_fly; short call+put different strikes with long wings = iron_condor; long
   call+put same strike = long_straddle; long call+put different strikes =
   long_strangle; anything else = unknown. Per position: quantity = min leg quantity;
   expiry = the legs' expiration date; find the opening order in get_option_orders
   (filled, position_effect open, same legs): entry_price = its net average price per
   unit, direction = its direction, opened = PT date (America/Los_Angeles) of its
   created_at, opening_order_id = its id. If no opening order is found, opened = PT
   date of the earliest leg created_at you can see, and say so in errors.
4. get_option_orders(account_number): open_orders = any non-terminal state
   (queued, confirmed, unconfirmed, partially_filled, pending); recent_orders = all
   orders from the last 5 trading days. Every order row carries top-level
   order_id, symbol, state, direction, position_effect (copied from its legs),
   price (net average fill price if filled, else limit price), quantity, created_at,
   and legs.
5. get_realized_pnl and get_pnl_trade_history for the last 30 days.
6. Write the reconcile snapshot to /tmp/earnings-run/recon_snapshot.json:
   {"as_of", "account":{account_number,buying_power,total_value,human_must_approve_trades},
    "open_positions":[{"symbol","structure","opened","quantity","entry_price","expiry",
                       "legs":[{"option_id","strike","type","side_held","quantity"}]}],
    "recent_orders":[{"order_id","symbol","state","position_effect","price","quantity",
                      "created_at","direction","legs"}]}
   (structure = structure_guess). Then run, after cd {{REPO_DIR}} (repo root):
   python -m vantage_trader.earnings reconcile --snapshot /tmp/earnings-run/recon_snapshot.json --journal state/earnings/journal.jsonl --config config/earnings.yaml > /tmp/earnings-run/recon.json
   Read-only: it only prints JSON. Exit 2 means bad input: read "error" from recon.json,
   fix the snapshot, retry up to 2 times. Do NOT append its journal_appends anywhere;
   the head does that.
Return data per the position-monitor schema: account, other_accounts_seen, positions,
open_orders, recent_orders, realized_pnl, reconcile, reconcile_snapshot_path.
```

### second-opinion (on demand, ENTRY wave C)
```
ROLE: second-opinion. Independently re-derive the earnings edge for ONE symbol. Do not
use any numbers you were not told to fetch yourself.
Symbol {{SYMBOL}}, report {{REPORT_DATE}} timing {{TIMING}}, expiry {{EXPIRY}}.
1. get_equity_quotes: spot.
2. Find the listed strike nearest spot for expiry (get_option_instruments, exact
   strike strings like "202.5000", probe neighbors). get_option_quotes for its call and put.
   straddle_mid = call mid + put mid. implied_move = 0.85 * straddle_mid / spot.
3. get_earnings_results + get_equity_historicals (~20 months, daily). For each past
   report: AMC (pm) move = close(report day) -> close(next trading day); BMO (am) move =
   close(prior trading day) -> close(report day). Skip interpolated or missing bars.
   Use the most recent {{N_REPORTS}} valid moves. avg_hist_move = mean(|move|).
4. edge_ratio = avg_hist_move / implied_move.
Return data {"symbol","spot","expiry","atm_strike","straddle_mid","implied_move",
"avg_hist_move","n_moves","moves","edge_ratio"}.
```

## 5. Merge, validate, decide (head)

1. Accept or reject each envelope (section 3 test). Collect failures.
2. Build the snapshot: `account` and `open_positions` from position-monitor (re-verified
   by the head's own `reconcile`), `candidates` = vol-analyst fragments with `_meta`
   stripped. For each symbol, `flags` = union of fragment flags and risk-sentinel flags.
   A candidate with no risk-sentinel entry gets `["risk_unchecked"]` (so it is skipped).
3. Validate every candidate before `score`:
   - chain covers ATM +/- ceil(max(wing_widths_pct) * spot) plus one listed strike
     beyond each side, every strike has call and put ids;
   - oldest quote `updated_at` <= 2 min old (ENTRY) or <= 10 min (SCAN watchlist only);
   - `historical_moves` non-empty; `spot` > 0;
   - expiry rule: `timing: pm` -> `expiry` is the first listed expiration > `report_date`;
     `timing: am` -> the first listed expiration >= `report_date`.
   Fix by re-pulling the specific item (head may call read-only tools directly for one
   or two items) or by a replacement agent scoped to those symbols.
4. If `market_regime.veto_all` is true: run `score` anyway for the record, then treat the
   result as `no_trade` with reason `risk_sentinel_veto_all`.
5. Second opinion (ENTRY only, when `status: trade`): compare its `implied_move` and
   `avg_hist_move` with the engine inputs for the chosen symbol (engine implied move from
   `ranked[]`, avg hist from `ranked[].avg_hist_move`). If either differs by more than
   15% relative (|a-b|/max(a,b) > 0.15), re-pull that symbol's chain and historicals,
   rebuild, and re-run `score` once. If they still disagree by > 15%, VETO (journal a
   `heal` line with notes `second_opinion_disagree`, no trade). The second opinion can
   only veto; agreement never upgrades a `no_trade`.
6. The head then follows RUNBOOK phase 2 to execute, alone.

## 6. Monitor self-heal

| Symptom | Heal |
|---|---|
| Agent tool error, timeout, or no JSON | Spawn ONE replacement with the same brief (scoped to the missing symbols). If the replacement also fails, the head does that read-only work itself. |
| `ok: false` with partial `data` | Keep the good parts; spawn a replacement only for the gaps (or pull directly if 1-2 items). |
| `as_of` older than 15 min, or quotes stale | Re-pull quotes directly (head) before `score`. |
| position-monitor fails twice | Head runs RUNBOOK 0.4-0.7 itself. Never trade without a fresh account read. |
| risk-sentinel fails twice | No entries today (every candidate gets `risk_unchecked`). EXIT still runs. |
| calendar-scout fails twice | Head runs the calendar steps itself; if that fails, SCAN reports "no watchlist" and ENTRY will do nothing. |
| A monitor called a forbidden tool (visible in its errors/sources, or an unexpected order appears at the broker) | HALT entries for the day, cancel any order the head did not place, journal `halt` with notes `monitor_violation`, tell Brad. |
| Subagent cap (8) reached | Head does the remaining read-only work itself. |

Every replacement spawn is journaled as `heal` (`notes: "replaced <role> batch <n>: <reason>"`)
and listed in the report to Brad.

## 7. Cost note

Expect about 4-7 Opus subagents per run, 2 trading runs per weekday (06:45 and
12:00) plus 1-2 on Saturday: roughly 40-70 subagent runs per week. Each is short
(a few dozen tool calls). To cut cost: skip wave B when calendar-scout returns zero
candidates, cap candidates at 25 (5 vol-analyst batches), and skip the second opinion
when the engine returns `no_trade`.
