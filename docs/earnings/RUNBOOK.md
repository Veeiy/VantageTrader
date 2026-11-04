# Earnings engine RUNBOOK (v1.2)

The exact procedure a fresh, context-free scheduled session follows. You are the
**HEAD agent** (see `AGENTS.md`). You run the engine, you alone touch orders and the
journal, and you dispatch read-only monitor agents for data gathering.

Read order on every run: this file, then `AGENTS.md`, then `CONTRACT.md` (JSON shapes),
then `config/earnings.yaml` (thresholds and caps). `BLUEPRINT.md` is background.

| Scheduled task | When (America/Los_Angeles) | Phases, in order |
|---|---|---|
| SCAN+EXIT | weekdays 06:45 | 0 PREFLIGHT -> 3 EXIT -> 1 SCAN |
| ENTRY | weekdays 12:00 | 0 PREFLIGHT -> 3 EXIT (if any position is open) -> 2 ENTRY |
| CALIBRATE | Saturday | 0 PREFLIGHT (reduced) -> 4 CALIBRATE |

Market hours are 06:30-13:00 PT (both coasts shift for DST together, so these PT times
hold year round). **Session windows apply to SCAN and ENTRY only. EXIT runs whenever
the market is open and a position exists**, in any session, including the 12:00 one
if the morning exit did not complete. On an expiration day, an open short position
found by the 12:00 session is closed first (Phase 3 guards, never above the action's
`hard_ceiling`), before any entry logic. On early-close days every intraday guard is
pulled in to the real close (Phase 3 guard table).

---

## Hard rules (never broken, no exceptions, no "just this once")

1. Trade ONLY the account with `agentic_allowed: true` AND nickname `MCP` (last 4:
   3413), with option level `option_level_3`. Never pass any other account number to
   any tool. If you cannot identify exactly one such account, HALT.
2. **TSLA never** (Brad is a Tesla employee). Not as a candidate, not as a leg, not as a
   hedge. Also never: stock price < $10, ATM bid/ask spread > 12% of mid (engine checks;
   you double check).
3. Limit orders only (`type: "limit"`, `time_in_force: "gfd"`). Never a market order.
4. Max ONE open earnings position, and no new entry while any option order is open.
5. Max loss per trade <= min($700, 0.93 x buying power), and whatever tighter cap
   `config/earnings.yaml` sets, minus the exit slippage reserve
   (`exit_slippage_reserve`, $50 per unit). Checked against `order.max_loss_worst` (the
   loss if filled at `limit_floor`). Defined risk only (iron fly, iron condor, long
   straddle/strangle). No naked shorts ever.
6. Never hold a short leg into the close of its expiration day. Exit the session after
   the report. Expiry-day exits finish well before each contract's `sellout_datetime`
   (Robinhood force-closes there). Never pay more than an exit action's `hard_ceiling`
   per unit (or a split group's `combined_cap`); only `naked_short` buybacks are uncapped.
7. Engine output + caps are binding. You (and monitors) may veto a trade; nobody may
   force one the engine rejected or resize past its `quantity`.
8. No transfers, deposits, withdrawals, settings changes, or credential handling.
9. Messages to Brad: casual and short, mask account numbers to last 4 (`****3413`),
   **no em dashes** (use commas, periods, or a plain hyphen).
10. Do not place, review, or cancel orders outside the steps below.

---

## Conventions used by every phase

**Repo root.** `REPO=$(git rev-parse --show-toplevel)` and `cd $REPO` before EVERY
engine command. All engine paths are repo-root relative.

**Times.** Always get time with `TZ=America/Los_Angeles date '+%F %T %Z'`. "Today" means
the PT date (`PT_DATE`). Journal `ts` and snapshot `as_of` are UTC ISO with `Z`.

**Work dir.** `/tmp/earnings-run/` (fresh per container).

**Engine calls.** Always pass both `--config config/earnings.yaml` and
`--journal state/earnings/journal.jsonl` to `score`, `exit`, `reconcile`, `calibrate`
(the journal drives the circuit breaker; a missing `--journal` silently resets streaks).
If `exit` answers exit 2 with a usage error naming `--journal` (older engine build),
re-run it once without `--journal` and note it in the report.

**Engine exit codes.** `0` ok (decision may be no trade). `2` invalid input: read the
`error` field from the JSON written to STDOUT (the `> file.json` you redirected), fix the
snapshot, retry, max 2 retries, then abort that phase and notify. `3` halted by circuit
breaker (no new entries; exits still run). `1` = internal engine error (`error` starts
with `internal:`): do not retry blindly; no new entries today; exits fall back to the
manual rule in 3.H. Anything else / traceback: same as `1`.

**Breaker journal check.** Every `score` output has `circuit_breaker.journal_found`. If it
is `false` while `git log --oneline -- state/earnings/journal.jsonl` or
`git log --oneline --grep '^earnings: '` shows prior earnings commits, the journal went
missing: HALT entries, notify, exits still run.

**MCP retry.** Any Robinhood tool error that is not a clear business rejection: retry
after 2s, 4s, 8s (3 retries). Then treat as failed and follow the step's heal row.
For waits, if foreground `sleep` is blocked in your shell, use the Monitor tool with a
timed until-loop, or `sleep N` with `run_in_background` and continue when it exits.

**Journal helper.** In PREFLIGHT write this file once, then append with
`python3 /tmp/earnings-run/jlog.py '<json>'` from `$REPO`. It keeps EVERY key you pass
(the engine reads extension keys such as `max_loss`, `direction`, `expiry`, `heal`).

```python
# /tmp/earnings-run/jlog.py
import json, sys, datetime, pathlib
EVENTS = {"scan","entry_submitted","entry_filled","entry_cancelled","exit_submitted",
          "exit_filled","halt","heal","calibrate"}
rows = json.loads(sys.argv[1])
rows = rows if isinstance(rows, list) else [rows]
p = pathlib.Path("state/earnings/journal.jsonl"); p.parent.mkdir(parents=True, exist_ok=True)
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
with p.open("a") as f:
    for rec in rows:
        assert isinstance(rec, dict) and rec.get("event") in EVENTS, f"bad event: {rec}"
        rec.setdefault("ts", now)            # all other keys pass through untouched
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        print(json.dumps(rec))
```

To append a file of events verbatim (for example reconcile `journal_appends`):
`python3 /tmp/earnings-run/jlog.py "$(jq -c '.journal_appends' /tmp/earnings-run/recon.json)"`.

The journal is append-only. Never edit or delete a line; repairs are new `heal` lines.
Base keys per CONTRACT: `ts, event, symbol, structure, order_id, price, quantity,
implied_move, edge_ratio, realized_move, pnl, notes`. Extension keys used by this
runbook (top level, not inside notes): `ref_id, attempt, stage` (intent|ack),
`session_id, ref_key, sequence, group_id, direction, max_loss, expiry, report_date,
timing, opened, legs, provenance, heal`.

**session_id.** At session start generate `SESSION_ID = uuid4` once
(`python3 -c 'import uuid; print(uuid.uuid4())'`, keep it in `/tmp/earnings-run/session_id`).
Every intent line carries it.

**Required fields per event.**

| event | must carry |
|---|---|
| `entry_submitted` | symbol, structure, direction, price, quantity, session_id, ref_key, ref_id, attempt, stage, expiry, report_date, timing, order_id (ack only) |
| `entry_filled` | symbol, structure, direction, order_id, price (avg fill), quantity, implied_move, edge_ratio, `max_loss` (= `order.max_loss_worst`), expiry, report_date, timing, ref_id, `opened` (= PT date of the broker order `created_at`), legs `[{option_id, strike, type, side_held, quantity}]` |
| `entry_cancelled` | symbol, order_id, ref_id, notes (why) |
| `exit_submitted` | symbol, structure, direction, price, quantity, session_id, ref_key, ref_id, attempt, stage, sequence, group_id, order_id (ack only) |
| split / flatten partial fill | `{"event":"heal","heal":{"type":"partial_exit_fill"},"symbol","order_id","price","quantity","sequence","group_id"}` (no `as_event`) |
| `exit_filled` | symbol, structure, order_id, price, quantity, pnl, realized_move |
| exit re-price cancel | `{"event":"heal","heal":{"type":"order_closed","as_event":"exit_cancelled"},"symbol","order_id","ref_id","notes"}` |

**ref_id (deterministic).**
`ref_key = f"vantage-earnings|{PT_DATE}|{phase}|{SYMBOL}|{sequence or sorted leg ids}"`
(`phase` in `entry|exit`; exits use the action `sequence`; entries use the order's
option ids sorted and joined with `,`), and
`ref_id = uuid5(NAMESPACE_URL, f"{ref_key}|{attempt}")`.
`attempt` = 1 + the highest `attempt` already journaled for that `ref_key` by ANY
session (`jq -s --arg k "$KEY" '[.[]|select(.ref_key==$k)|.attempt]|max // 0' state/earnings/journal.jsonl`).
A re-price is the next attempt. In Python:
`python3 -c 'import uuid,sys; print(uuid.uuid5(uuid.NAMESPACE_URL, sys.argv[1]))' "vantage-earnings|2026-11-04|entry|ARM|id1,id2,id3,id4|1"`.
A retry of the SAME attempt reuses the same `ref_id`, so the broker de-dupes. If
`place_option_order` returns an `order_id` that is already in the journal or is already
terminal (filled/cancelled/rejected), that `ref_id` is spent: bump `attempt` and place
again.

**Commit + push** (after every journal state change, and at the end of the run):

```bash
cd $REPO && git add state/earnings && \
git commit -m "earnings: <phase> <YYYY-MM-DD> <summary>" && \
git push origin HEAD:$BRANCH && \
test -n "$(git ls-files state/earnings/journal.jsonl)"
```
After every push verify `git ls-files state/earnings/journal.jsonl` is non-empty (the
file is tracked). If it is empty, the journal is not being persisted (for example
`.gitignore` regressed): HALT entries, notify Brad, exits still run.

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
flag, reconciled journal, gates for later phases.

1. **Clock and window.** Get PT time. The window limits SCAN (must start before 11:00)
   and ENTRY (no new placement after 12:35, hard stop 12:50). If a window has passed,
   skip that phase only; EXIT still runs if the market is open and a position exists.
   CALIBRATE on a weekday: stop, short note to Brad.
2. **Market-day check** (skip for CALIBRATE). Not a trading day if weekend or today is in
   config `market_holidays`. Early close (10:00 PT) if today is in config
   `market_early_closes`: ENTRY does nothing; EXIT runs with guards pulled in to the
   close (Phase 3 guard table). Read both lists with
   `python3 -c 'import yaml;c=yaml.safe_load(open("config/earnings.yaml"));print(c.get("market_holidays"),c.get("market_early_closes"))'`
   (if a key is absent, the engine defaults apply; see `src/vantage_trader/earnings/config.py`).
   If today is within 60 days of the LAST date in `market_holidays`, add a warning to the
   report: "holiday list runs out on <date>, please extend config market_holidays and
   market_early_closes".
   Live confirm: `get_equity_quotes(["SPY"])`; after 06:30 PT its `updated_at` should be
   today and within ~5 min. If the table says open but SPY is stale for 3 re-pulls,
   treat as closed for entries and notify.
3. **Repo.** `cd $REPO`; find the default branch
   (`git remote show origin | sed -n 's/.*HEAD branch: //p'`), check it out, set
   `BRANCH` to it, `git pull --rebase`. If `origin/earnings-state` exists, merge its
   journal lines (Self-healing, git). Set git identity if missing
   (`git config user.name "VantageTrader agent"`, `user.email` any noreply). Verify
   `git ls-files state/earnings/journal.jsonl` is non-empty; if not, HALT entries.
   Then `python -c "import vantage_trader.earnings"`; if it fails `pip install -e .`
   (and `pip install -r requirements.txt` if imports still fail). Confirm
   `config/earnings.yaml` exists; if not, HALT (no caps = no trading). `mkdir -p
   /tmp/earnings-run/frag`, write `jlog.py`, and generate `SESSION_ID`.
4. **Account (wave A).** Dispatch per `AGENTS.md` section 2, wave A for this session (one
   message, multiple Agent calls). From position-monitor take the account block. Verify
   yourself: exactly one account, `agentic_allowed: true`, nickname `MCP`, last4 `3413`.
   Otherwise HALT everything. Then verify `option_level == "option_level_3"`; otherwise
   HALT entries and notify (exits still run). Buying power and the approval setting are
   re-read every run; never reuse yesterday's numbers.
5. **Approval setting.** If `human_must_approve_trades` is true: no new entries today
   (tell Brad: "approvals are on, so I'm sitting out entries"). Exits still get placed,
   and Brad is told to approve them in the app right away.
6. **Caps sanity.** `cap_loss = min(700, 0.93 * buying_power, config max_loss_abs,
   config max_loss_bp_frac * buying_power)`; `reserve = config exit_slippage_reserve`
   (default 50, dollars per unit). Kept for the order check in 2.6.
7. **RECONCILE (broker is truth).** Snapshot built by position-monitor at
   `/tmp/earnings-run/recon_snapshot.json` (rebuild it yourself from
   `get_option_positions(account_number=$ACCT, nonzero=true)` and `get_option_orders`
   if the monitor failed). Shape:
   ```json
   {"as_of": "...Z",
    "account": {"account_number": "...", "buying_power": 0, "total_value": 0, "human_must_approve_trades": false},
    "open_positions": [{"symbol": "ARM", "structure": "iron_fly", "opened": "2026-11-04",
                        "quantity": 1, "entry_price": 14.40, "expiry": "2026-11-06",
                        "legs": [{"option_id": "...", "strike": 202.5, "type": "call", "side_held": "short", "quantity": 1}]}],
    "recent_orders": [{"order_id": "...", "symbol": "ARM", "state": "filled", "position_effect": "open",
                       "price": 14.40, "quantity": 1, "created_at": "...Z", "direction": "credit",
                       "legs": [{"option_id": "...", "side": "sell", "position_effect": "open"}]}]}
   ```
   `open_positions.quantity` = min leg quantity; `entry_price` = net average price of the
   opening order (credit or debit per unit); `opened` = PT date of the opening order's
   `created_at` (never a heal or snapshot timestamp). `recent_orders.position_effect` is
   top-level, taken from the legs (all legs share it). Then run:
   ```bash
   cd $REPO && python -m vantage_trader.earnings reconcile --snapshot /tmp/earnings-run/recon_snapshot.json --journal state/earnings/journal.jsonl --config config/earnings.yaml > /tmp/earnings-run/recon.json
   ```
   Append `journal_appends` VERBATIM (`jlog.py "$(jq -c '.journal_appends' /tmp/earnings-run/recon.json)"`).
   It already contains the housekeeping heals; do not append `housekeeping` separately,
   and do not rewrite anything. Reconcile heals carry `report_date`, `timing`, `expiry`,
   `opened`, `ref_id`, `legs` when known; EXIT reads them. Then act on
   `issues[].fix.broker_action`:

   | issue type | Broker action / extra handling |
   |---|---|
   | `missing_fill` | None. The appended heal records the fill with broker price. |
   | `orphan_position` | None at the broker. The heal adopts it; when it is fed to EXIT it carries `provenance: "reconstructed"`. If it is NOT ours (no matching order in recent_orders from this system, for example Brad traded manually): do not touch it, block new entries, tell Brad. If any short leg is naked: Self-healing, partial fills. |
   | `stale_open_order` | `cancel_option_order(order_id)`, poll until terminal, THEN append that issue's `fix.journal_event` (it is not in `journal_appends`). If it filled during the cancel, re-run reconcile. |
   | `qty_mismatch` | Broker has legs with unequal quantities, or broker quantity differs: run Self-healing, partial fills, immediately. Broker zero with no fill found: heal already appended (pnl unknown, counted as a loss); tell Brad. |

   Re-run reconcile once; `consistent` should be true. If still false, HALT entries,
   exits still run, tell Brad the remaining issues.
8. **Circuit breaker probe.** Write `/tmp/earnings-run/probe.json` = the score snapshot
   with `candidates: []` and run
   `cd $REPO && python -m vantage_trader.earnings score --snapshot /tmp/earnings-run/probe.json --config config/earnings.yaml --journal state/earnings/journal.jsonl > /tmp/earnings-run/probe_out.json`.
   Exit 3 (or `status: "halted"`) => `HALTED=1`: append one `halt` line per day (skip if
   today already has one), notes = `circuit_breaker.reasons`. No entries; exits still run.
   Apply the breaker journal check (Conventions).
9. Commit + push if anything was journaled: `earnings: reconcile <date> <summary>`.

FAILURE / HEAL

| Failure | Heal |
|---|---|
| `get_accounts` errors | Retry 2/4/8s. Still failing: HALT, no orders at all this run, notify. |
| Zero or multiple MCP agentic accounts, or last4 != 3413 | HALT. Never pick one by guessing. Notify. |
| `option_level` is not `option_level_3` | HALT entries, notify. Exits still run. |
| `git ls-files` shows the journal untracked | HALT entries, notify ("journal not persisted"). Exits still run. |
| `git pull` conflict in journal | Union both sides' lines, de-dupe exact duplicates, sort by `ts`, commit `earnings: heal <date> journal merge`. |
| `pip install -e .` fails | Retry once; check Python >= 3.11. Still failing: no entries; EXIT uses manual rule 3.H; notify. |
| `config/earnings.yaml` missing or unparsable (exit 2 on every command) | HALT entries; EXIT manual rule; notify. |
| position-monitor failed | Spawn one replacement (AGENTS.md 6); if that fails, do 0.4-0.7 yourself. |
| Reconcile exit 2 | Read `error` from recon.json, fix snapshot, retry <= 2, then HALT entries, notify. |
| `journal_found: false` with prior earnings commits | HALT entries, notify, exits still run. |
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
   market-cap order) + one risk-sentinel for all N symbols. Pass
   `MAX_WING_PCT = max(wing_widths_pct)` from `config/earnings.yaml` (currently 0.125)
   and `EARLY_CLOSES` = config `market_early_closes` (analysts skip those expiries);
   each analyst computes per symbol `WING_WIDTH_DOLLARS = ceil(MAX_WING_PCT * spot)` and
   covers ATM +/- that PLUS one more listed strike beyond on each side.
   `START_20M` = today minus 600 days. N = 0: skip wave B, go to step 8.
3. While wave B runs, keep any EXIT order walking (poll it between steps).
4. **Merge** per `AGENTS.md` section 5: candidates = fragments minus `_meta`; flags =
   fragment flags + risk-sentinel flags (`risk_unchecked` if missing); account and
   `open_positions` from preflight (CONTRACT shape `{"symbol","structure","opened"}`).
5. **Validate** each candidate (AGENTS.md 5.3), including the expiry rule:
   `timing: pm` -> `expiry` = first listed expiration > `report_date`;
   `timing: am` -> first listed expiration >= `report_date`. Heal gaps by re-pull or
   replacement. A symbol that still fails is dropped and listed in the report.
6. **Score (dry).**
   ```bash
   cd $REPO && python -m vantage_trader.earnings score --snapshot state/earnings/scan/<date>/snapshot.json --config config/earnings.yaml --journal state/earnings/journal.jsonl > state/earnings/scan/<date>/decision.json
   ```
   Exit 2: read `error` from decision.json, fix, retry (<= 2). Exit 3: note halted, still
   save. Skips like `report_not_imminent` or `bad_expiry` in `ranked[].skip_reason` are
   expected at 06:45 for some names; `bad_expiry` means re-check step 5 for that symbol.
7. **Persist.** Save `candidates.json` (per symbol: report_date, timing, verified,
   chain_symbol, expiry, chain ids by strike, historical_moves, fragments), `events.json`,
   `moves.json`, `risk.json` (risk-sentinel data). Append one `scan` line per `ranked[]`
   entry: `symbol`, `implied_move`, `edge_ratio`, `report_date`, `timing`, `expiry`, notes
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
| `history` exit 2 | Read `error` from moves.json, fix bars/events JSON (YYYY-MM-DD dates, floats), retry <= 2, else drop symbol. |
| Strike not found at round number | Probe neighbors (0.5, 1, 2.5, 5 grid) with exact strings like `"202.5000"`. |
| Wing strike not listed | Include the next listed strike beyond the wing; engine picks from what exists. |
| Option quote stale (> 2 min during RTH) or zero bid/ask near ATM | Re-pull up to 3x; then keep for watchlist only, flag `stale_quotes` (ENTRY re-pulls anyway). |
| Snapshot exit 2 | Fix and retry <= 2, then abort SCAN scoring, still save raw data, notify. |
| Monitor failure | AGENTS.md section 6. |

---

## Phase 2: ENTRY (weekday 12:00; market closes 13:00; hard stop 12:50)

Inputs: preflight outputs, `state/earnings/scan/<today>/`. Output: at most one filled
defined-risk position, journal lines for every state change.

1. **Exits first.** If preflight shows ANY open option position, run Phase 3 now (this
   covers a morning exit that did not complete, and expiry-day shorts). An expiry-day
   short is closed before anything else, inside the Phase 3 guards and ceilings. Then
   skip new entries today (max one position).
2. **Gates.** Do nothing (report why) if any: `HALTED=1`; approvals on (0.5); option level
   not level 3; journal untracked; early-close day; engine/config unavailable; reconcile
   not consistent; it is past 12:35 PT.
3. **Duplicate-run guard.** Do nothing if the journal has an `entry_submitted` with
   today's PT date, OR the broker shows any open option position in the MCP account, OR
   any non-terminal option order. Exception: a stale intent from a crash (see
   Self-healing, crash recovery) is handled there, not by placing a fresh order.
4. **Load scan artifacts.** If `state/earnings/scan/<today>/candidates.json` is missing,
   run SCAN steps 1-5 now (heal), only if it is before 12:15.
5. **Refresh (wave A, one message).** position-monitor, vol-analyst x ceil(N/5) in
   `refresh` mode (pass the scan fragments and `MAX_WING_PCT`), risk-sentinel. Merge and
   validate (AGENTS.md 5). ENTRY requires every quote `updated_at` <= 2 min old at score
   time. Write `/tmp/earnings-run/entry_snapshot.json`, then:
   ```bash
   cd $REPO && python -m vantage_trader.earnings score --snapshot /tmp/earnings-run/entry_snapshot.json --config config/earnings.yaml --journal state/earnings/journal.jsonl > /tmp/earnings-run/decision.json
   ```
   Copy both files into `state/earnings/scan/<today>/entry_snapshot.json` and
   `entry_decision.json`. Apply the breaker journal check.
   - `status: no_trade` -> report reason + top of `ranked[]`, commit, done.
   - `status: halted` / exit 3 -> journal `halt`, report, done.
   - `market_regime.veto_all` -> treat as no_trade (`risk_sentinel_veto_all`).
6. **Order sanity (defense in depth).** Abort (journal `halt`, notify) if any: symbol is
   TSLA or carries any flag; `order.max_loss_worst > min(cap_loss, order.risk_cap) -
   reserve * quantity`; `quantity < 1`; `order.order_legs` missing;
   structure not in {iron_fly, iron_condor, long_straddle, long_strangle}; any short leg
   without a long leg of the same type and quantity further OTM; legs not all the same
   expiry, or expiry breaks the rule in 1.5; credit order with
   `limit_floor > limit_start` or debit order with `limit_floor < limit_start`; a
   position or open order appeared since step 3.
7. **Second opinion (wave C).** Spawn one second-opinion agent (AGENTS.md 4, 5.5). Disagree
   > 15% twice -> veto, journal `heal` notes `second_opinion_disagree`, report, done.
8. **Review first.** For the current attempt price `P`:
   `review_option_order(account_number=$ACCT, legs=order.order_legs, quantity, direction,
   price=P, type="limit", time_in_force="gfd", chain_symbol, underlying_type="equity")`.
   Always `order.order_legs` (option_id/side/position_effect only), never `order.legs`.
   Surface every `order_checks` item in the report. Blocking items (rejection, not enough
   buying power, account restriction) -> no trade. Collateral check: the review's
   collateral / buying-power impact must be <= `(W - P) * 100 * qty + 5` for a credit
   order (W = wing width in dollars, the distance from the short strike to the long
   wing) or `P * 100 * qty + 5` for a debit order. Larger -> no trade, notify.
   Warnings (wide spread, earnings soon) -> note and continue.
9. **Intent, race check, place.** `ref_key`, `attempt`, `ref_id` per Conventions.
   a. Append the intent: `{"event":"entry_submitted","stage":"intent","session_id","ref_key",
      "ref_id","attempt","symbol","structure","direction","price":P,"quantity","expiry",
      "report_date","timing","implied_move","edge_ratio","notes":"limit_floor=<f>"}`;
      commit + push (`earnings: entry <date> intent <SYM> <structure> <q>x @<P>`).
   b. `git pull --rebase`. Proceed only if the FIRST `entry_submitted` line dated today
      carries YOUR `session_id` (so your own attempts 2, 3... keep walking). If another
      session's intent is first, stop (journal `heal` notes `lost_entry_race`), report.
   c. Immediately before placing, re-check `get_option_orders` (no non-terminal order)
      and `get_option_positions` (no open position). Anything found -> stop, reconcile.
   d. `place_option_order` with exactly the reviewed params (`legs=order.order_legs`)
      plus `ref_id`. If the returned `order_id` is already journaled or already terminal,
      bump `attempt` and go back to a. Append the ack: same fields with `stage: "ack"` and
      `order_id`. Commit + push.
10. **Poll.** `get_option_orders` every 60-90 s for that `order_id`.
    - `filled`: verify with `get_option_positions` that all legs exist with matching
      quantities (mismatch -> Self-healing, partial fills). Append `entry_filled` with
      every field in the Conventions table (`max_loss` = `order.max_loss_worst`,
      `opened` = PT date of the order's `created_at`, legs with strike and type). Commit,
      report. Done.
    - `rejected`/`failed`: read the reason. Tick size -> round the price to the next valid
      tick in the conservative direction and retry as the next attempt. Buying power /
      restriction / market closed -> stop, journal `entry_cancelled` with reason, notify.
11. **Walk.** After ~2 polls (2-3 min) unfilled: `cancel_option_order(order_id)`, poll
    until terminal. If it filled during the cancel, go to 10 filled. Else journal
    `entry_cancelled` (`ref_id`, notes `reprice=1`). Next price = previous -
    `limit_step` (credit) or + `limit_step` (debit), clamped so it never goes past
    `limit_floor`. Re-quote legs (must be fresh); if the underlying moved > 1% from the
    scored spot, re-run step 5 `score` and use the new decision (now no_trade -> stop).
    `attempt += 1`, then 8 (review) -> 9 (intent, race check, place) -> 10. At the floor,
    let the order rest.
12. **Hard stop 12:50 PT.** Cancel any working entry order, confirm terminal, journal
    `entry_cancelled` notes `deadline=12:50`, commit, report "no fill today".

FAILURE / HEAL

| Failure | Heal |
|---|---|
| Score exit 2 | Read `error` from decision.json, fix snapshot, retry <= 2, abort entries, notify. |
| Quotes stale at score time | Re-pull (3x). Still stale: drop that symbol (flag `stale_quotes`). |
| `review_option_order` errors (transient) | Retry 2/4/8s. Still failing: no trade. Never place an unreviewed order. |
| `place_option_order` times out / unclear result | Retry with the SAME `ref_id` and identical params (broker de-dupes). Then confirm via `get_option_orders`. |
| Fill state unclear after cancel | Poll `get_option_orders` and `get_option_positions` until consistent; positions win. |
| Legs mismatched after fill | Self-healing, partial fills, immediately. |
| Lost the intent race (another session's intent first) | Stop, journal `heal`, report. Never place a second entry. |
| Past 12:50 with an order working | Cancel now; if cancel fails retry 2/4/8s; if still working at 12:58 tell Brad loudly. |
| Monitor failed | AGENTS.md section 6. risk-sentinel failed twice -> no entry. |

---

## Phase 3: EXIT (06:45 session; also any session while the market is open and a position exists)

Inputs: preflight outputs (positions). Output: every due position closed, journal
`exit_submitted` / `exit_filled` with `pnl` and `realized_move`.

**Price limits (never broken).** For every debit close action, the most you may ever
pay per unit is the action's `hard_ceiling` (= `width_cap` W + `exit_slippage_reserve`/100).
Split verticals sharing a `group_id` may never total more than their `combined_cap`.
Credit closes never go below 0 (a $0.05 floor is fine). The only uncapped case is an
action with `naked_short: true` (buy back a short that has no wing): it is priced up to
the live ask and re-quoted until flat, because a naked short must not stay open. If a
capped action is still unfilled at its ceiling near a deadline, keep the limit working at
the ceiling and notify Brad loudly; never chase past it.

**Guard times.** Compute once per session, all PT:

| guard | meaning | expiry day (any leg expires today) | other days |
|---|---|---|---|
| G1 | allowed to walk past `limit_worst` toward `hard_ceiling` | `sellout - 90 min` | 08:30 |
| G2 | at `hard_ceiling`; leg-out allowed if it improves (step 8) | `sellout - 60 min` | none |
| G3 | must be filled; if not, keep resting at the ceiling and notify Brad loudly | `sellout - 30 min` | close - 30 min (12:30) |

`sellout` = the earliest `sellout_datetime` among the position's legs, read with
`get_option_instruments` for each leg (for example `2026-11-06T20:30:00Z` = 12:30 PT).
Robinhood force-closes risky expiring positions at that time, so expiry-day exits must
be done well before it. If `sellout_datetime` is missing, assume 12:00 PT. On an
early-close day (config `market_early_closes`, close 10:00 PT) each guard is the
EARLIER of the table value and `close - 120 / -90 / -60 min` for G1 / G2 / G3.

1. **Gate.** If no open option positions in the MCP account, skip. Exits run even when
   `HALTED=1` or approvals are on (approvals on: place, then tell Brad to approve).
2. **Exit snapshot.** From `get_option_positions(account_number=$ACCT, nonzero=true)` group
   legs per symbol; `get_option_quotes` on every leg id (fresh, <= 2 min). Per position:
   `expiry` from position-monitor (broker leg expiration, REQUIRED); `report_date` and
   `timing` from the journal `entry_filled` or the reconcile heal that adopted it
   (fallback: scan artifacts for that entry date); `entry_price`, `direction`,
   `structure` from the journal; `opened` = PT date of the broker opening order's
   `created_at` (never a heal or snapshot timestamp). A position adopted by reconcile
   carries `"provenance": "reconstructed"`. Write `/tmp/earnings-run/exit_snapshot.json`:
   ```json
   {"as_of": "...Z", "account": {...}, "minutes_since_open": 15,
    "positions": [{"symbol": "ARM", "structure": "iron_fly", "expiry": "2026-11-06",
                   "report_date": "2026-11-04", "timing": "pm", "opened": "2026-11-04",
                   "entry_price": 14.40, "direction": "credit",
                   "legs": [{"option_id": "...", "strike": 202.5, "type": "call",
                             "side_held": "short", "quantity": 1, "bid": 3.1, "ask": 3.3}]}]}
   ```
   `minutes_since_open` = minutes since 06:30 PT. Add `"provenance": "reconstructed"`
   only for adopted positions.
3. **Run exit.**
   ```bash
   cd $REPO && python -m vantage_trader.earnings exit --snapshot /tmp/earnings-run/exit_snapshot.json --config config/earnings.yaml --journal state/earnings/journal.jsonl > /tmp/earnings-run/exit.json
   ```
   Read `actions` and `holds`:
   - `holds` reason starting `wait:` (or `wait_market_open:`) -> NOT "nothing due". Wait
     the indicated minutes, rebuild the snapshot with fresh quotes, re-run exit.
   - `holds` reason starting `hold:` -> genuinely not due; report and continue.
   - `leg_qty_mismatch: true` (reason `partial_fill_flatten`) -> Self-healing, partial
     fills, now. Those actions put `naked_short` buybacks at `sequence` 1.
   - Reason `split_verticals_natural_exceeds_width` -> two actions with the same
     `group_id` and a `combined_cap`; worked one at a time by `sequence`.
   Exit 2: read `error` from exit.json, fix (missing `expiry`, strike/type), retry <= 2,
   then manual rule 3.H.
4. **Work actions strictly by `sequence`** (per symbol). Do not start action N+1 until
   action N is filled. For each action:
   `review_option_order(account_number=$ACCT, legs=action.order_legs, quantity=action.quantity,
   direction=action.direction, price=action.limit_start, type="limit", time_in_force="gfd",
   chain_symbol, underlying_type="equity")`. Always `order_legs`, never `close_legs`
   (those carry strike/type and are for reading only). Then append intent
   `exit_submitted` (`stage: "intent"`, `session_id`, `ref_key`, `attempt`, `ref_id`,
   `sequence`, `group_id`), commit + push, re-check `get_option_orders` for a working
   close on these legs (manage it instead if found), then `place_option_order` with the
   same params and `ref_id`; append the ack with `order_id`.
5. **Poll and walk.** Poll every 60-90 s; after ~2 polls unfilled, cancel, confirm, append
   the exit re-price cancel heal (Conventions table), re-quote, re-place one `limit_step`
   worse as the next attempt. Price bounds per attempt:
   - before G1: never worse than `limit_worst`;
   - from G1: may walk past `limit_worst`, never above `hard_ceiling` (debit);
     credit closes walk toward the live natural bid, never below $0.05;
   - split vertical with `sequence` 2: bound = min(its `hard_ceiling`,
     `combined_cap` - fill price of sequence 1);
   - `naked_short: true`: walk to the live ask, re-quote each attempt, no cap.
6. **Missing or zero leg quote.** Re-quote that id alone (3x). Still missing: re-check the
   instrument with `get_option_instruments`; price the combo from the other legs and
   assume the worst side for the missing one (far OTM long wing: bid 0). The ceiling
   still applies.
7. **G3 reached, not filled.** Leave the order resting at `hard_ceiling` (or the split
   bound), notify Brad loudly ("HALT: ARM close not filled at the $X cap, sellout at
   12:30, please look"), keep polling and re-placing at the ceiling with fresh quotes
   until filled or the market closes. On a non-expiry day an unfilled close carries to
   the next session's EXIT.
8. **Leg-out (expiry day only, from G2).** Only when it improves on the resting combo and
   stays inside the ceiling: for a vertical (short S, long L), leg out only if
   `ask(S) - bid(L) <= hard_ceiling` (for split verticals, the split bound) AND that is
   better than the combo limit currently working. Cancel the combo, buy back S alone at
   a limit <= its ask, then immediately sell L at a limit >= `S_fill - hard_ceiling`
   (walk down toward its bid, never below that bound). Buy back shorts first, always.
   Journal each leg fill as a `heal` line (notes `leg_out=1`).
9. **Filled.** Split verticals and flatten sequences: journal each action's fill
   immediately as its own `heal` line (`"heal":{"type":"partial_exit_fill"}`, no
   `as_event`; `order_id`, `price`, `quantity`, `sequence`, `group_id`). When the whole
   position is flat, append ONE `exit_filled`: price = net closing price per unit (sum
   of the fills, debit positive for credit structures), quantity, `pnl` (credit trade:
   (entry credit - exit debit) x 100 x qty; debit trade: (exit credit - entry debit) x
   100 x qty, minus fees if shown), `realized_move` = spot now vs the pre-report close
   (signed fraction). Cross-check with `get_option_positions` (flat) and
   `get_realized_pnl`. Commit + push `earnings: exit <date> filled <SYM> @<px> pnl <+/-n>`.

**3.H Manual exit rule (engine unavailable).** Close every position due per CONTRACT
rules (AMC report -> next morning, BMO -> same day after 06:40 PT, long straddle up >=
50% -> immediately, expiry day -> now). Compute W yourself (distance between each short
strike and its same-type wing) and `hard_ceiling = W + exit_slippage_reserve/100`
(reserve from config, default $50/unit). Start at mid, walk $0.05 per 2 min toward
natural but never above `hard_ceiling`; if natural exceeds W, close as two verticals with
a combined cap of `W + reserve/100`, put vertical first. Same guards (G1-G3) and leg-out
rule as above. Journal `heal` notes `manual_exit=1`.

FAILURE / HEAL

| Failure | Heal |
|---|---|
| Positions and journal disagree | Reconcile already ran; positions win. Exit what the broker holds. |
| Exit exit 2 (missing expiry / strike / type) | Fill from position-monitor and `get_option_instruments`; retry <= 2; then 3.H. |
| `holds` says `wait:` | Wait and re-run; do not end the session. |
| Leg quote missing/zero | Step 6. |
| Order rejected (tick) | Round to a valid tick that stays inside the ceiling; next attempt. |
| Not filled by G1 | Walk past `limit_worst` up to `hard_ceiling`, step 5. |
| Not filled at G3 | Rest at the ceiling, notify Brad loudly, keep working (step 7). Never exceed the ceiling. |
| Split vertical half filled | Work the other half with bound `combined_cap - first fill`; never re-open the filled side. |
| `sellout_datetime` missing | Assume 12:00 PT for the guards. |
| Session dies mid-exit | Next run (12:00 session) reconciles, sees the open position, runs EXIT first. |
| `place_option_order` unclear result | Retry with the same `ref_id`; confirm via `get_option_orders`. |
| place returns an `order_id` already journaled or terminal | Bump `attempt` (new `ref_id`) and place again. |

---

## Phase 4: CALIBRATE (Saturday)

1. PREFLIGHT steps 1, 3, 4, 7 (no market check, no breaker probe). Read-only except
   for the journal and git.
2. Run:
   ```bash
   cd $REPO && mkdir -p state/earnings/calibration && python -m vantage_trader.earnings calibrate --journal state/earnings/journal.jsonl --config config/earnings.yaml > state/earnings/calibration/<date>.json
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
6. Switch back to `$BRANCH`, commit the journal + calibration JSON, push, verify
   `git ls-files`, and report the week to Brad.

FAILURE / HEAL

| Failure | Heal |
|---|---|
| Calibrate exit 2 (malformed journal line; `error` names the line) | Do not edit the line. Append a `heal` line describing it, report, notify. Entries next week stay blocked until Brad (or a human-approved PR) fixes it, since `score` will fail the same way. |
| `gh` unavailable | PR-style summary in the report instead. |
| Journal empty | Report "no closed trades on record". |

---

## Self-healing rules (apply in every phase)

**Idempotency.** Every place call has a deterministic `ref_id` (Conventions:
`ref_key` + `attempt`, attempt = 1 + highest journaled for the key across sessions)
written to the journal (intent line) and pushed BEFORE `place_option_order`. A retry of
the same attempt reuses the same `ref_id` and identical params, so the broker cannot
create a duplicate. A re-price is a new attempt: new `ref_id`, new intent line. A
`ref_id` whose order is already journaled or terminal is spent: bump `attempt`.

**Crash recovery (stale intent).** On startup, an intent line with no `ack` and no later
line for that `ref_id`: first look for a matching order in `get_option_orders` (same
symbol and legs, created after the intent `ts`). Found -> append the ack with its
`order_id` and manage it. Not found and still inside the phase window -> re-run `score`
(entry) or `exit` (exit) on a fresh snapshot AND `review_option_order` before
re-placing. Re-place with the SAME `ref_id` only if the new decision has identical
`order_legs` and the intent price is still within `limit_floor` (entry) / the Phase 3
bound for the current guard (exit, never above `hard_ceiling`). If
not, or if the window passed: do not place; append `heal` notes
`ref_id=<id> abandoned=1 reason=<...>`.

**Duplicate-run guard and intent race.** ENTRY does nothing if today already has
`entry_submitted`, or the broker shows an open earnings position or any open option
order (Phase 2.3). After pushing an intent, `git pull` and proceed only if the first
`entry_submitted` today carries your `session_id` (Phase 2.9b), then re-check broker
orders and positions right before placing. EXIT never places a second close for legs that already have a
working close order; it manages the existing one.

**Stale quotes.** During RTH any quote with `updated_at` older than 2 min is stale:
re-pull (3x). Never score an ENTRY or set an exit price from stale quotes.

**Engine exit 2.** Read `error` from the stdout JSON file. Fix the snapshot (types,
missing keys, units: fractions not percents), retry up to 2 times, then abort that phase
and notify. Exit 3: halt entries, keep exits. Exit 1: engine bug, no entries, manual exits.

**MCP transient errors.** Retry with 2/4/8s backoff, 3 times. Business rejections
(buying power, restriction) are not transient: do not retry them.

**Partial fills / mismatched legs** (triggered by reconcile `qty_mismatch`, exit actions
`leg_qty_mismatch` / `partial_fill_flatten`, or what you see in positions). Robinhood fills
multi-leg strategies as a unit, so mismatched legs mean something broke. Work the
engine's flatten actions strictly by `sequence` (naked short buybacks are `sequence` 1,
then capped verticals, then leftover longs); do not start N+1 until N fills. Naked short
(`naked_short: true`): limit at the ask, re-quote and walk up a tick per minute, no cap,
until flat. Capped verticals: never above their `hard_ceiling`. Leftover longs: normal
credit walk. Without engine actions (engine down): same order by hand, shorts first.
Journal a `heal` (`partial_exit_fill`) per filled action, notify Brad right away. Never
"complete" the structure by opening more legs.

**Container loss mid-trade.** State lives in the broker and in the pushed journal. The
next run's PREFLIGHT reconciles (broker wins), and crash recovery adopts or abandons
pending intents. Working orders left behind are handled by `stale_open_order`.

**Git push rejected.** `git pull --rebase`, resolve journal conflicts by union of lines
sorted by `ts` (de-dupe exact duplicates), push again, up to 3 times. If pushing to
`$BRANCH` is refused by policy, push to `earnings-state` (`git push origin
HEAD:earnings-state`) and say so in the report; every PREFLIGHT merges
`origin/earnings-state` journal lines in. If git is completely unavailable: no new
entries (the intent cannot be persisted); exits still run; put this run's journal lines
in the report so they can be restored.

**Monitors.** See `AGENTS.md` section 6.

**Notify on every halt and heal.** Each `halt` and `heal` line is also a line in the
report to Brad (`HALT:` / `HEAL:` prefix, plain words).

---

## State persistence

- `state/earnings/journal.jsonl`: the CONTRACT journal, append-only, tracked in git
  (`.gitignore` ignores `state/*` but un-ignores `state/earnings/`). Committed and pushed
  by the head every run and before every order placement; tracked status verified after
  each push.
- `state/earnings/scan/<date>/`: SCAN and ENTRY artifacts (`candidates.json`,
  `events.json`, `moves.json`, `risk.json`, `snapshot.json`, `decision.json`,
  `entry_snapshot.json`, `entry_decision.json`). Lets ENTRY skip the heavy pulls.
- `state/earnings/calibration/<date>.json`: weekly calibrate output.
- Before committing scan/recon artifacts, mask `account.account_number` to last 4
  (`jq '.account.account_number |= "****"+.[-4:]'`). Never commit full account numbers
  or anything from other accounts.
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
in: ARM iron fly 202.5 +/-20, 1x for $14.40 credit. worst-case loss $560, max gain $1440, breakevens 188.1 / 216.9.
review checks: none blocking. exit tomorrow after the open.
```
No trade: `no trade today. best was AMD at 0.93, not cheap or rich enough. sitting tight.`
Halt: `HALT: breaker tripped (3 losers in a row). no new entries until you say so, exits still run.`
Heal: `HEAL: vol-analyst batch 2 timed out, swapped in a replacement, all good.`
CALIBRATE: week P&L, trade count, win rate per structure, and either the PR link or
"no changes, only 5 closed trades so far".
