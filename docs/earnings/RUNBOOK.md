# Earnings engine RUNBOOK (v1)

The exact procedure a fresh, context-free scheduled session follows. You are the
**HEAD agent** (see `AGENTS.md`). You run the engine, you alone touch orders and the
journal, and you dispatch read-only monitor agents for data gathering.

Read order on every run: this file, then `AGENTS.md`, then `CONTRACT.md` (JSON shapes),
then `config/earnings.yaml` (thresholds and caps). `BLUEPRINT.md` is background.

| Scheduled task | When (America/Los_Angeles) | Phases, in order |
|---|---|---|
| SCAN+EXIT | weekdays 06:45 | 0 PREFLIGHT -> 3 EXIT -> 1 SCAN |
| ENTRY | weekdays 12:00 | 0 PREFLIGHT -> (3 EXIT if anything is overdue) -> 2 ENTRY |
| CALIBRATE | Saturday | 0 PREFLIGHT (reduced) -> 4 CALIBRATE |

Market hours are 06:30-13:00 PT (both coasts shift for DST together, so these PT times
hold year round). EXIT runs before SCAN because it is time critical; SCAN output is
not needed until 12:00.

---

## Hard rules (never broken, no exceptions, no "just this once")

1. Trade ONLY the account with `agentic_allowed: true` AND nickname `MCP` (last 4:
   3413). Never pass any other account number to any tool. If you cannot identify
   exactly one such account, HALT.
2. **TSLA never** (Brad is a Tesla employee). Not as a candidate, not as a leg, not as a
   hedge. Also never: stock price < $10, ATM bid/ask spread > 12% of mid (engine checks;
   you double check).
3. Limit orders only (`type: "limit"`, `time_in_force: "gfd"`). Never a market order.
4. Max ONE open earnings position, and no new entry while any option order is open.
5. Max loss per trade <= min($700, 0.93 x buying power), and whatever tighter cap
   `config/earnings.yaml` sets. Defined risk only (iron fly, iron condor, long
   straddle/strangle). No naked shorts ever.
6. Never hold a short leg into the close of its expiration day. Exit the session after
   the report.
7. Engine output + caps are binding. You (and monitors) may veto a trade; nobody may
   force one the engine rejected or resize past its `quantity`.
8. No transfers, deposits, withdrawals, settings changes, or credential handling.
9. Messages to Brad: casual and short, mask account numbers to last 4 (`****3413`),
   **no em dashes** (use commas, periods, or a plain hyphen).
10. Do not place, review, or cancel orders outside the steps below.

---

## Conventions used by every phase

**Times.** Always get time with `TZ=America/Los_Angeles date '+%F %T %Z'`. "Today" means
the PT date. Journal `ts` and snapshot `as_of` are UTC ISO with `Z`.

**Work dir.** `/tmp/earnings-run/` (fresh per container). Repo dir = `$REPO` (the
VantageTrader clone, `git rev-parse --show-toplevel`). Run engine commands from `$REPO`.

**Engine exit codes** (all commands): `0` ok (decision may be no trade), `2` invalid
input (fix the snapshot, retry, max 2 retries, then abort and notify), `3` halted by
circuit breaker (no new entries; exits still run). Any other code or a traceback =
engine bug: no new entries today, exits fall back to the manual rule in 3.H.

**MCP retry.** Any Robinhood tool error that is not a clear business rejection: retry
after 2s, 4s, 8s (3 retries). Then treat as failed and follow the step's heal row.
For waits, if foreground `sleep` is blocked in your shell, use the Monitor tool with a
timed until-loop, or `sleep N` with `run_in_background` and continue when it exits.

**Journal helper.** In PREFLIGHT write this file once, then append with
`python3 /tmp/earnings-run/jlog.py '<json>'` from `$REPO`:

```python
# /tmp/earnings-run/jlog.py
import json, sys, datetime, pathlib
FIELDS = ["ts","event","symbol","structure","order_id","price","quantity",
          "implied_move","edge_ratio","realized_move","pnl","notes"]
EVENTS = {"scan","entry_submitted","entry_filled","entry_cancelled","exit_submitted",
          "exit_filled","halt","heal","calibrate"}
rec = json.loads(sys.argv[1])
assert rec.get("event") in EVENTS, "bad event"
row = {k: rec.get(k) for k in FIELDS}
row["ts"] = row["ts"] or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
p = pathlib.Path("state/earnings/journal.jsonl"); p.parent.mkdir(parents=True, exist_ok=True)
with p.open("a") as f: f.write(json.dumps(row, separators=(",", ":")) + "\n")
print(json.dumps(row))
```

The journal is append-only. Never edit or delete a line; repairs are new `heal` lines.
Extra data goes in `notes` as space-separated `key=value` pairs, for example
`ref_id=9b1c... attempt=2 stage=intent limit=14.50`.

**Commit + push** (after every journal state change, and at the end of the run):

```bash
cd $REPO && git add state/earnings && \
git commit -m "earnings: <phase> <YYYY-MM-DD> <summary>" && \
git push origin HEAD:$BRANCH
```
Format: `<phase>` is one of `preflight|scan|entry|exit|reconcile|calibrate|heal|halt`,
date is the PT trading date, summary <= 60 chars, no account numbers, no em dashes.
Examples: `earnings: entry 2026-11-04 intent ARM iron_fly 1x @14.60`,
`earnings: exit 2026-11-05 filled ARM close @3.20 pnl +114`,
`earnings: scan 2026-11-04 watchlist ARM,AMD,QCOM`. On push rejection see Self-healing.

**Notify Brad.** The session's final message is the report Brad gets. Put `HALT:` or
`HEAL:` lines at the top if any happened. Templates are at the end of this file.

---

## Phase 0: PREFLIGHT (every run)

Inputs: none. Output: `$ACCT` (full number, internal only), account block, `HALTED`
flag, reconciled journal, `PHASE_OK` decision.

1. **Clock and window.** Get PT time. Abort quietly (short note to Brad, no journal) if
   the run is outside its window: SCAN+EXIT later than 11:00, ENTRY later than 12:35,
   CALIBRATE on a weekday.
2. **Market-day check** (skip for CALIBRATE). Not a trading day if weekend or one of:
   2026-11-26, 2026-12-25, 2027-01-01, 2027-01-18, 2027-02-15, 2027-03-26, 2027-05-31,
   2027-06-18, 2027-07-05, 2027-09-06, 2027-11-25, 2027-12-24. Early close (10:00 PT):
   2026-11-27, 2026-12-24, 2027-11-26 (ENTRY does nothing on early-close days; EXIT runs).
   Live confirm: `get_equity_quotes(["SPY"])`; after 06:30 PT its `updated_at` should be
   today and within ~5 min. If the table says open but SPY is stale for 3 re-pulls,
   treat as closed and notify.
3. **Repo.** `cd $REPO`; find the default branch
   (`git remote show origin | sed -n 's/.*HEAD branch: //p'`), check it out, set
   `BRANCH` to it, `git pull --rebase`. If `origin/earnings-state` exists, merge its
   journal lines (see Self-healing, git). Set git identity if missing
   (`git config user.name "VantageTrader agent"`, `user.email` any noreply). Then:
   `python -c "import vantage_trader.earnings"` and if it fails `pip install -e .`
   (also `pip install -r requirements.txt` if imports still fail). Confirm
   `config/earnings.yaml` exists; if not, HALT (no caps = no trading). `mkdir -p
   /tmp/earnings-run/frag` and write `jlog.py`.
4. **Account (wave A).** Dispatch per `AGENTS.md` section 2, wave A for this session (one
   message, multiple Agent calls). From position-monitor take the account block. Verify
   yourself: exactly one account, `agentic_allowed: true`, nickname `MCP`, last4 `3413`.
   Otherwise HALT. Buying power and the approval setting are re-read every run; never
   reuse yesterday's numbers.
5. **Approval setting.** If `human_must_approve_trades` is true: no new entries today
   (tell Brad: "approvals are on, so I'm sitting out entries"). Exits still get placed,
   and Brad is told to approve them in the app right away.
6. **Caps sanity.** Compute `cap_loss = min(700, 0.93 * buying_power, config cap)`. Keep
   it for the order check in 2.5.
7. **RECONCILE (broker is truth).** Re-run it yourself on the position-monitor's snapshot:
   ```bash
   python -m vantage_trader.earnings reconcile --snapshot /tmp/earnings-run/recon_snapshot.json --journal state/earnings/journal.jsonl > /tmp/earnings-run/recon.json
   ```
   Snapshot = `{"as_of","account":{...},"open_positions":[{"symbol","structure","opened","legs":[...]}],"recent_orders":[...]}`
   (built by position-monitor; rebuild yourself from `get_option_positions(account_number, nonzero=true)`
   and `get_option_orders` if it failed). For each issue in `recon.json`:

   | issue type | Fix (always journal a `heal` line, then commit) |
   |---|---|
   | `missing_fill` | Broker shows the fill the journal lacks: append `entry_filled` / `exit_filled` with broker price and quantity, notes `reconstructed=1`. |
   | `orphan_position` | Broker position not in journal. If it is a defined-risk structure on a symbol in our recent orders: append reconstructed `entry_filled` (notes `reconstructed=1`) so EXIT manages it. If it is not ours (Brad traded manually): do not touch it, block new entries (max one position), tell Brad. If any short leg is naked: Self-healing, partial fills. |
   | `stale_open_order` | An order that should not be working (entry after 12:50 PT, or any order from a prior day): `cancel_option_order`, confirm terminal state, append `entry_cancelled` or `heal`. If it filled during the cancel, treat as `missing_fill`. |
   | `qty_mismatch` | Legs or quantities disagree: follow Self-healing, partial fills, immediately. |

   After fixes, re-run reconcile once; `consistent` should be true. If still false,
   HALT entries, exits still run, tell Brad the remaining issues.
8. **Circuit breaker probe.** Write `/tmp/earnings-run/probe.json` = the score snapshot
   with `candidates: []` and run
   `python -m vantage_trader.earnings score --snapshot /tmp/earnings-run/probe.json --config config/earnings.yaml > /tmp/earnings-run/probe_out.json`.
   Exit 3 (or `status: "halted"`) => `HALTED=1`: append one `halt` line per day (skip if
   today already has one), notes = engine reason. No entries; exits still run.
9. Commit + push if anything was journaled: `earnings: reconcile <date> <summary>`.

FAILURE / HEAL

| Failure | Heal |
|---|---|
| `get_accounts` errors | Retry 2/4/8s. Still failing: HALT, no orders at all this run, notify. |
| Zero or multiple MCP agentic accounts, or last4 != 3413 | HALT. Never pick one by guessing. Notify. |
| `git pull` conflict in journal | Union both sides' lines, de-dupe exact duplicates, sort by `ts`, commit `earnings: heal <date> journal merge`. |
| `pip install -e .` fails | Retry once; check Python >= 3.11. Still failing: no entries; EXIT uses manual rule 3.H; notify. |
| Engine module missing (engine not merged yet) | Same as above. |
| `config/earnings.yaml` missing or unparsable | HALT entries; EXIT manual rule; notify. |
| position-monitor failed | Spawn one replacement (AGENTS.md 6); if that fails, do 0.4-0.7 yourself. |
| Reconcile exit 2 | Fix snapshot (types, missing keys), retry <= 2, then HALT entries, notify. |
| Market-day check ambiguous | Treat as closed for entries. EXIT still tries if any position exists and quotes are live. |

---

## Phase 1: SCAN (weekday 06:45, after EXIT)

Inputs: preflight outputs, `config/earnings.yaml`. Outputs:
`state/earnings/scan/<date>/` with `candidates.json`, `events.json`, `moves.json`,
`snapshot.json`, `decision.json`, `risk.json`; `scan` journal lines; watchlist for Brad.
SCAN never places orders ("dry": the decision is recorded, not executed).

1. **Calendar (wave A).** calendar-scout was dispatched in preflight wave A. Inputs to its
   brief: `TODAY`, `NEXT_TRADING_DAY` (skip weekends and the holiday table), and `DAYS`
   = calendar days from today through next trading day (Mon-Thu: 2, Fri: 4). It returns
   today `pm` + next-trading-day `am` reports, `high_market_cap`, price >= 10,
   optionable, TSLA dropped. Double check TSLA is absent.
2. **Wave B.** One message: vol-analyst x ceil(N/5) in `full` mode (batches of ~5,
   market-cap order) + one risk-sentinel for all N symbols. Fill `WING_WIDTH` with the
   largest wing width in `config/earnings.yaml` (search for keys containing `wing`; if
   none, pass 0 so the analyst covers 12% of spot), `START_20M` = today minus 600 days.
   N = 0: skip wave B, go to step 8 with an empty watchlist.
3. While wave B runs, keep any EXIT order walking (poll it between steps).
4. **Merge** per `AGENTS.md` section 5: candidates = fragments minus `_meta`; flags =
   fragment flags + risk-sentinel flags (`risk_unchecked` if missing); account and
   `open_positions` from preflight. `open_positions` uses the CONTRACT shape
   `{"symbol","structure","opened"}`.
5. **Validate** each candidate (AGENTS.md 5.3). Heal gaps by re-pull or replacement.
   A symbol that still fails validation is dropped from `candidates` and listed in the
   report with the reason.
6. **Score (dry).**
   ```bash
   python -m vantage_trader.earnings score --snapshot state/earnings/scan/<date>/snapshot.json --config config/earnings.yaml > state/earnings/scan/<date>/decision.json
   ```
   Exit 2: read stderr, fix the snapshot, retry (<= 2). Exit 3: note halted, still save.
7. **Persist.** Save `candidates.json` (per symbol: report_date, timing, verified,
   chain_symbol, expiry, chain ids by strike, historical_moves, fragments), `events.json`,
   `moves.json`, `risk.json` (risk-sentinel data). Append one `scan` line per `ranked[]`
   entry: `symbol`, `implied_move`, `edge_ratio`, notes
   `action=<sell|buy|skip> skip_reason=<...> hist=<avg_hist_move> ev=<ev_per_dollar_risk>`.
   Commit + push: `earnings: scan <date> watchlist <SYMS or none>`.
8. **Report** the watchlist to Brad (template below) together with the EXIT result.

FAILURE / HEAL

| Failure | Heal |
|---|---|
| Calendar output huge / file-saved | jq it; never paste it. Inspect one element for field names first. |
| Calendar empty or tool fails twice | Report "no earnings worth a look today"; journal one `scan` line, notes `empty_calendar=1`. ENTRY will do nothing. |
| `get_earnings_results` has no past reports with `eps.actual` | Drop symbol, reason `no_history`. |
| Historicals last bar is a duplicated interpolated placeholder | Mark `interpolated: true`; `history` skips it. |
| `history` exit 2 | Fix bars/events JSON (dates as YYYY-MM-DD, floats), retry <= 2, else drop symbol. |
| Strike not found at round number | Probe neighbors (0.5, 1, 2.5, 5 grid) with exact strings like `"202.5000"`. |
| Wing strike not listed | Cover the nearest listed strikes beyond the wing; engine picks from what exists. |
| Option quote stale (> 2 min during RTH) or zero bid/ask near ATM | Re-pull up to 3x; then keep for watchlist only, flag `stale_quotes` (ENTRY re-pulls anyway). |
| Snapshot exit 2 | Fix and retry <= 2, then abort SCAN scoring, still save raw data, notify. |
| Monitor failure | AGENTS.md section 6. |

---

## Phase 2: ENTRY (weekday 12:00; market closes 13:00; hard stop 12:50)

Inputs: preflight outputs, `state/earnings/scan/<today>/`. Output: at most one filled
defined-risk position, journal lines for every state change.

1. **Gates.** Do nothing (report why) if any: `HALTED=1`; approvals on (0.5); early-close
   day; engine/config unavailable; reconcile not consistent; it is past 12:35 PT.
2. **Duplicate-run guard.** Do nothing if the journal has an `entry_submitted` with today's
   PT date, OR the broker shows any open option position in the MCP account, OR any
   non-terminal option order. (Exception: an `entry_submitted` intent line today with no
   broker order and no later line means a crash before placement; see Self-healing,
   idempotency.) If a position exists that EXIT says is due, run Phase 3 first and
   still skip entries today.
3. **Load scan artifacts.** If `state/earnings/scan/<today>/candidates.json` is missing,
   run SCAN steps 1-5 now (heal), only if it is before 12:15.
4. **Refresh (wave A, one message).** position-monitor, vol-analyst x ceil(N/5) in
   `refresh` mode (pass the scan fragments), risk-sentinel. Merge and validate
   (AGENTS.md 5). ENTRY requires every quote `updated_at` <= 2 min old at score time.
   Write `/tmp/earnings-run/entry_snapshot.json`, then:
   ```bash
   python -m vantage_trader.earnings score --snapshot /tmp/earnings-run/entry_snapshot.json --config config/earnings.yaml > /tmp/earnings-run/decision.json
   ```
   Copy both files into `state/earnings/scan/<today>/entry_*.json`.
   - `status: no_trade` -> report reason + top of `ranked[]`, commit, done.
   - `status: halted` / exit 3 -> journal `halt`, report, done.
   - `market_regime.veto_all` -> treat as no_trade (`risk_sentinel_veto_all`).
5. **Order sanity (defense in depth).** Abort (journal `halt`, notify) if any: symbol is
   TSLA or carries any flag; `max_loss > cap_loss`; `quantity < 1`; structure not in
   {iron_fly, iron_condor, long_straddle, long_strangle}; any short leg without a long
   leg of the same type and quantity further OTM; legs not all the same expiry; credit
   order with `limit_floor > limit_start` or debit order with `limit_floor < limit_start`;
   a position or open order appeared since step 2.
6. **Second opinion (wave C).** Spawn one second-opinion agent (AGENTS.md 4, 5.5). Disagree
   > 15% twice -> veto, journal `heal` `second_opinion_disagree`, report, done.
7. **Review first.**
   `review_option_order(account_number=$ACCT, legs=[{option_id, side, position_effect:"open"}...],
   quantity, direction, price=limit_start, type="limit", time_in_force="gfd",
   chain_symbol, underlying_type="equity")`.
   Surface every `order_checks` item in the report. Blocking items (rejection, not enough
   buying power, account restriction, collateral above `max_loss` + $5) -> no trade.
   Warnings (wide spread, earnings soon) -> note and continue.
8. **Idempotent place.** Generate `ref_id = uuid4`. Journal intent FIRST:
   `{"event":"entry_submitted","symbol","structure","price":<limit>,"quantity","implied_move","edge_ratio","notes":"ref_id=<id> attempt=<n> stage=intent limit_floor=<f>"}`
   and commit + push (`earnings: entry <date> intent <SYM> <structure> <q>x @<limit>`).
   Then `place_option_order` with exactly the reviewed params plus `ref_id`. Journal the
   ack: same event with `order_id`, notes `ref_id=<id> attempt=<n> stage=ack`. Commit.
9. **Poll.** `get_option_orders` every 60-90 s for that `order_id`.
   - `filled`: journal `entry_filled` (avg fill price, quantity, implied_move, edge_ratio),
     verify with `get_option_positions` that all legs exist with matching quantities
     (mismatch -> Self-healing, partial fills), commit, report. Done.
   - `rejected`/`failed`: read the reason. Tick size -> round the price to the next valid
     tick in the conservative direction and retry with a new `ref_id`. Buying power /
     restriction / market closed -> stop, journal `entry_cancelled` with reason, notify.
10. **Walk.** After ~2 polls (2-3 min) unfilled: `cancel_option_order(order_id)`, poll
    until terminal. If it filled during the cancel, go to 9 filled. Else journal
    `entry_cancelled` (notes `ref_id=<id> attempt=<n> reprice=1`). New price = previous
    - `limit_step` (credit) or + `limit_step` (debit), clamped so it never goes past
    `limit_floor`. Re-quote legs (must be fresh); if the underlying moved > 1% from the
    scored spot, re-run step 4 `score` and use the new decision (if it is now no_trade,
    stop). Repeat 7 (review) -> 8 (new `ref_id`) -> 9. At the floor, let the order rest.
11. **Hard stop 12:50 PT.** Cancel any working entry order, confirm terminal, journal
    `entry_cancelled` notes `deadline=12:50`, commit, report "no fill today".

FAILURE / HEAL

| Failure | Heal |
|---|---|
| Score exit 2 | Fix snapshot, retry <= 2, abort entries, notify. |
| Quotes stale at score time | Re-pull (3x). Still stale: drop that symbol (flag `stale_quotes`). |
| `review_option_order` errors (transient) | Retry 2/4/8s. Still failing: no trade. Never place an unreviewed order. |
| `place_option_order` times out / unclear result | Retry with the SAME `ref_id` and identical params (broker de-dupes). Then confirm via `get_option_orders`. |
| Fill state unclear after cancel | Poll `get_option_orders` and `get_option_positions` until consistent; positions win. |
| Legs mismatched after fill | Self-healing, partial fills, immediately. |
| Past 12:50 with an order working | Cancel now; if cancel fails retry 2/4/8s; if still working at 12:58 tell Brad loudly. |
| Monitor failed | AGENTS.md section 6. risk-sentinel failed twice -> no entry. |

---

## Phase 3: EXIT (weekday 06:45, i.e. after open + 10 min; ENTRY runs it if overdue)

Inputs: preflight outputs (positions). Output: every due position closed, journal
`exit_submitted` / `exit_filled` with `pnl` and `realized_move`.

1. **Gate.** If no open option positions in the MCP account, skip to SCAN. Exits run even
   when `HALTED=1` or approvals are on (approvals on: place, then tell Brad to approve).
2. **Exit snapshot.** From `get_option_positions(account_number=$ACCT, nonzero=true)` group
   legs per symbol; `get_option_quotes` on every leg id (fresh, <= 2 min). From the journal
   take `entry_price`, `direction`, `opened`, `structure`. Write
   `/tmp/earnings-run/exit_snapshot.json`:
   `{"as_of", "account":{...}, "minutes_since_open": <now - 06:30 PT in minutes>,
     "positions":[{"symbol","structure","legs":[{"option_id","side_held","quantity","bid","ask"}],
                   "entry_price","direction","opened"}]}`
3. **Run exit.**
   ```bash
   python -m vantage_trader.earnings exit --snapshot /tmp/earnings-run/exit_snapshot.json --config config/earnings.yaml > /tmp/earnings-run/exit.json
   ```
   Empty `actions` -> nothing due; report and continue. Exit 2 -> fix and retry <= 2,
   then manual rule 3.H.
4. **Close as ONE multi-leg limit order** per action:
   `review_option_order(account_number=$ACCT, legs=close_legs, quantity=<position qty>,
   direction, price=limit_start, type="limit", time_in_force="gfd", chain_symbol,
   underlying_type="equity")`, then journal intent `exit_submitted` (notes
   `ref_id=<id> attempt=<n> stage=intent`), commit + push, then `place_option_order`
   with the same params and `ref_id`, journal the ack with `order_id`.
5. **Poll and walk.** Poll every 60-90 s; after ~2 polls unfilled, cancel, confirm,
   re-quote, re-place one `limit_step` toward `limit_worst` with a new `ref_id`. Never past
   `limit_worst` before 08:30.
6. **Missing or zero leg quote.** Re-quote that id alone (3x). Still missing: re-check the
   instrument with `get_option_instruments`; price the combo from the other legs and
   assume natural for the missing one (far OTM long wing: bid 0).
7. **08:30 PT fallback.** Still unfilled: price at natural (debit close = sum of asks bought
   - sum of bids sold; credit close = sum of bids sold - sum of asks bought), still a
   limit order, refresh natural every ~2 min until filled. This may go beyond
   `limit_worst`; getting out wins (risk is already defined).
8. **Expiry-day guard.** If any leg expires today and the combo is not filled by 11:00 PT:
   leg out. Buy back each short leg alone at its ask (limit, walk up a tick per minute),
   then sell the longs. All shorts must be flat by 11:30 PT, the absolute last minute is
   12:00 PT (engine rule). Tell Brad immediately if any short is still open at 11:30.
9. **Filled.** Journal `exit_filled`: price, quantity, `pnl` (credit trade: (entry credit -
   exit debit) x 100 x qty; debit trade: (exit credit - entry debit) x 100 x qty, minus
   fees if shown), `realized_move` = actual earnings move from quotes (spot now vs the
   pre-report close, signed fraction). Cross-check with `get_option_positions` (flat) and
   `get_realized_pnl`. Commit + push `earnings: exit <date> filled <SYM> @<px> pnl <+/-n>`.

**3.H Manual exit rule (engine unavailable).** Close every position due per CONTRACT
rules (AMC report -> next morning, BMO -> same day after 06:40 PT, long straddle up >=
50% -> immediately) starting at mid, walking $0.05 per 2 min toward natural, natural by
08:30, expiry-day guard as in 8. Journal `heal` notes `manual_exit=1`.

FAILURE / HEAL

| Failure | Heal |
|---|---|
| Positions and journal disagree | Reconcile already ran; positions win. Exit what the broker holds. |
| Leg quote missing/zero | Step 6. |
| Order rejected (tick) | Round to valid tick in the direction that fills more easily; new `ref_id`. |
| Not filled by 08:30 | Natural, step 7. |
| Expiry day, not filled by 11:00 | Leg out, short legs first, step 8. |
| Session dies mid-exit | Next run (12:00 ENTRY preflight) reconciles, sees the open position, runs EXIT first. |
| `place_option_order` unclear result | Retry with the same `ref_id`; confirm via `get_option_orders`. |

---

## Phase 4: CALIBRATE (Saturday)

1. PREFLIGHT steps 1, 3, 4, 7 (no market check, no breaker probe). Read-only except
   for the journal and git.
2. Run:
   ```bash
   python -m vantage_trader.earnings calibrate --journal state/earnings/journal.jsonl --config config/earnings.yaml > state/earnings/calibration/<date>.json
   ```
3. Cross-check closed-trade P&L in the journal against `get_realized_pnl` /
   `get_pnl_trade_history` (from position-monitor). Mismatch > $1 per trade -> journal a
   `heal` line with the broker numbers (broker is truth), note it in the summary.
4. Journal `calibrate` with notes summarizing per-structure win rate, avg pnl,
   realized/implied ratio, and `proposed_changes=<n>`.
5. **Never apply the config change.** If the proposed diff is non-empty: create branch
   `earnings/calibrate-<date>`, apply the diff to `config/earnings.yaml` ON THAT BRANCH
   ONLY, commit `earnings: calibrate <date> proposed <keys>`, push, and open a PR with
   `gh pr create` (title `earnings: calibration proposal <date>`, body = PR-style summary:
   what changed, from -> to, closed-trade count, evidence, risk). Never merge it. If
   `gh` or push to a new branch is not available, put the PR-style summary in the report.
   Fewer than 8 closed trades -> no change proposed (engine enforces), say so.
6. Commit the journal + calibration JSON on `$BRANCH`, push, and report the week to Brad.

FAILURE / HEAL

| Failure | Heal |
|---|---|
| Calibrate exit 2 (malformed journal line) | Do not edit the line. Append a `heal` line describing it, report; engine should skip bad lines, if not, notify and stop. |
| `gh` unavailable | PR-style summary in the report instead. |
| Journal missing | Rebuild nothing; report "no closed trades on record", tell Brad. |

---

## Self-healing rules (apply in every phase)

**Idempotency.** Every place call has a `ref_id` (UUID) written to the journal (intent
line) and pushed BEFORE `place_option_order`. A retry of the same order reuses the same
`ref_id` and identical params, so the broker cannot create a duplicate. A re-price is a
new order: new `ref_id`, new intent line. On startup, an intent line with no `ack` and no
later line for that `ref_id`: look for a matching order in `get_option_orders` (same
symbol, legs, price, created after the intent `ts`). Found -> journal the ack with its
`order_id` and continue managing it. Not found and still inside the phase window ->
place it with the SAME `ref_id`. Window passed -> journal `heal` notes
`ref_id=<id> abandoned=1`.

**Duplicate-run guard.** ENTRY does nothing if today already has `entry_submitted`, or
the broker shows an open earnings position or any open option order (Phase 2.2). EXIT
never places a second close for a position that already has a working close order;
it manages the existing one.

**Stale quotes.** During RTH any quote with `updated_at` older than 2 min is stale:
re-pull (3x). Never score an ENTRY or set an exit price from stale quotes.

**Engine exit 2.** Fix the snapshot from stderr (types, missing keys, units: fractions
not percents), retry up to 2 times, then abort that phase and notify. Exit 3: halt
entries, keep exits.

**MCP transient errors.** Retry with 2/4/8s backoff, 3 times. Business rejections
(buying power, restriction) are not transient: do not retry them.

**Partial fills / mismatched legs.** Robinhood fills multi-leg strategies as a unit, so
mismatched legs mean something broke. If `get_option_positions` shows legs that do not
form a defined-risk structure: (1) buy back every naked short FIRST (a short with no long
of the same type and expiry further OTM in at least the same quantity) with a limit at
the ask, walking up a tick per minute, natural immediately if after 12:30 PT; (2) then
sell any leftover longs with the normal walk. Journal `heal` for each step, notify Brad
right away. Never "complete" the structure by opening more legs.

**Container loss mid-trade.** State lives in the broker and in the pushed journal. The
next run's PREFLIGHT reconciles (broker wins), and idempotency adopts or abandons
pending intents. Working orders left behind are handled by `stale_open_order`.

**Git push rejected.** `git pull --rebase`, resolve journal conflicts by union of lines
sorted by `ts` (de-dupe exact duplicates), push again, up to 3 times. If pushing to
`$BRANCH` is refused by policy, push to `earnings-state` (`git push origin
HEAD:earnings-state`) and say so in the report; every PREFLIGHT merges
`origin/earnings-state` journal lines in. If git is completely unavailable, keep
trading only if the journal intent could be written locally, and put the full journal
lines of this run in the report so they can be restored.

**Monitors.** See `AGENTS.md` section 6.

**Notify on every halt and heal.** Each `halt` and `heal` line is also a line in the
report to Brad (`HALT:` / `HEAL:` prefix, plain words).

---

## State persistence

- `state/earnings/journal.jsonl`: the CONTRACT journal, append-only, committed and
  pushed by the head every run (and before every order placement).
- `state/earnings/scan/<date>/`: SCAN and ENTRY artifacts (`candidates.json`,
  `events.json`, `moves.json`, `risk.json`, `snapshot.json`, `decision.json`,
  `entry_snapshot.json`, `entry_decision.json`). Lets ENTRY skip the heavy pulls.
- `state/earnings/calibration/<date>.json`: weekly calibrate output.
- Never commit account numbers (mask to last 4 in notes) or anything from other accounts.
- Commit message format: `earnings: <phase> <date> <summary>` (see Conventions).

---

## Reports to Brad (templates; casual, no em dashes, account masked)

SCAN+EXIT:
```
morning! acct ****3413, bp $812.
exit: closed ARM fly @3.20 debit, +$114 (moved 4.1%, implied was 9.5%).
watchlist for noon: 1) NVDA sell, edge 0.72, implied 7.1% vs hist 5.1%. 2) QCOM skip, ratio 1.02.
risk: nothing flagged. FOMC not in the window.
```
ENTRY:
```
in: ARM iron fly 202.5 +/-20, 1x for $14.40 credit. max loss $560, max gain $1440, breakevens 188.1 / 216.9.
review checks: none blocking. exit tomorrow after the open.
```
No trade: `no trade today. best was AMD at 0.93, not cheap or rich enough. sitting tight.`
Halt: `HALT: breaker tripped (3 losers in a row). no new entries until you say so, exits still run.`
Heal: `HEAL: vol-analyst batch 2 timed out, swapped in a replacement, all good.`
CALIBRATE: week P&L, trade count, win rate per structure, and either the PR link or
"no changes, only 5 closed trades so far".
