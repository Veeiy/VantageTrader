# VantageTrader

Auto-managed **horizontal calendar spread** bot for [tastytrade](https://developer.tastytrade.com/).

The bot scans a watchlist for solid calendar-spread setups, opens them via the tastytrade
REST API, and manages them through profit-take, stop-loss, drift, and roll rules.

> **Sandbox-first.** The default config targets `api.cert.tastyworks.com` and starts
> in `dry_run: true` mode — every order is logged but **nothing is submitted** until
> you flip it off. Validate the bot's decisions before risking real capital.

---

## Strategy

A **horizontal calendar spread** is two options with the **same strike** and **different
expirations**:

```
LONG  1x   strike K   expiration T_long    (30-60 DTE)   <- collateral, long vega
SHORT 1x   strike K   expiration T_short   (1-5 DTE)     <- theta engine
```

The short leg decays much faster than the long leg per day, so we collect that
differential decay as profit. The long leg caps loss to the net debit paid.

### Direction selection (call vs put calendar)

Because both legs share a strike, the P/L diagram of a call calendar and a put calendar
at the same strike are economically very close (put-call parity, ignoring dividends &
early exercise). What differs is **assignment risk on the short**: if the short is ITM
at expiration, we may be assigned shares.

The bot picks the side that keeps the **short OTM at entry**:

- spot price `<` strike  →  **call calendar** (short call is OTM)
- spot price `>=` strike →  **put calendar**  (short put is OTM)

### Entry filters

| Filter | Default | Why |
| --- | --- | --- |
| `iv_rank_max` | 50 | Calendars are long vega — prefer low IV so it can expand |
| `skip_if_earnings_within_days` | 7 | Avoid binary events inside the short window |
| `max_debit_per_spread` | $250 | Per-contract risk cap |
| `min_open_interest_short` / `long` | 500 / 100 | Liquidity floor |
| `max_bid_ask_spread_pct` | 15% | Avoid wide markets |
| `short_dte_min` / `max` | 1 / 5 | Weekly short cycle |
| `long_dte_min` / `max` | 30 / 60 | Sweet spot — enough vega, not too expensive |

### Management rules (checked every `manage_every_seconds`)

| Trigger | Action |
| --- | --- |
| P/L >= `profit_target_pct` (25%) | Close spread |
| P/L <= `-stop_loss_pct` (50%) | Close spread |
| Underlying drifted > `underlying_drift_strikes` from K | Close spread |
| Long leg DTE <= `close_long_at_dte` (14) | Close spread |
| Short leg DTE <= `roll_short_at_dte` (1) | Roll short to next eligible expiry, same K |

### Ranking score

Within each underlying, candidate calendars are scored by:

```
score = theta_efficiency * liquidity_factor
```

where `theta_efficiency` proxies decay-per-dollar-at-risk and `liquidity_factor`
penalises wide bid/ask spreads. The top-scoring candidate across the watchlist is
opened first, subject to `risk.max_concurrent_spreads` and `risk.max_total_debit`.

> **Note on greeks.** True theta/delta come from the DXLink streamer's `Greeks`
> event. The current build uses a premium-based proxy via REST snapshots, which is
> sufficient for ranking but not for precise greek-targeting. Streaming greeks
> integration is a planned follow-up.

---

## Quick start

### 1. Install

```bash
git clone <this repo>
cd VantageTrader
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

Edit `.env`:

```bash
TASTY_ENV=sandbox
TASTY_USERNAME=<your sandbox username>
TASTY_PASSWORD=<your sandbox password>
TASTY_ACCOUNT_NUMBER=<your sandbox account number e.g. 5WT00000>
```

Get sandbox credentials from <https://developer.tastytrade.com/sandbox/>. They are
distinct from your real tastytrade login.

Edit `config.yaml` to taste — at minimum review the `underlyings` list and the
entry/management thresholds.

### 3. Smoke test

```bash
python -m vantage_trader accounts
```

Should print the accounts visible to the session.

### 4. Scan once (dry-run, no orders)

```bash
python -m vantage_trader scan-once
```

Logs candidate calendars with their score and rationale. Always dry-run regardless of
config.

### 5. Run the engine

```bash
python -m vantage_trader run
```

With `dry_run: true` in `config.yaml`, this will scan/manage on the configured cadence
and log every order it *would* place. Set `dry_run: false` only after you have validated
the decisions over several sessions.

---

## Project layout

```
src/vantage_trader/
├── __main__.py             # CLI entrypoint (run / scan-once / accounts)
├── config.py               # env + yaml loaders
├── engine.py               # orchestration: scan -> enter -> manage -> roll/close
├── logging_setup.py
├── strategy/
│   └── calendar.py         # CalendarScanner, CalendarManager, order builders
└── tastytrade/
    ├── client.py           # async REST client
    └── models.py           # OptionContract, OrderRequest, OrderLeg, etc.
tests/
├── test_calendar.py        # strategy & manager rules
└── test_models.py          # OCC/streamer symbol formatting & order payloads
```

## Tests

```bash
pytest
```

Covers OCC symbol formatting, order payload construction, and every management rule
(profit target, stop loss, drift, long-DTE close, short-DTE roll, hold).

---

## Safety checklist before going live

- [ ] Run with `dry_run: true` for at least a week in sandbox
- [ ] Verify every `OPEN`, `CLOSE`, and `ROLL` log line matches your expectations
- [ ] Check `state/open_spreads.json` survives bot restarts
- [ ] Set conservative `max_concurrent_spreads` and `max_total_debit` for live
- [ ] Switch `TASTY_ENV=live` and `dry_run: false` *separately*, not in the same edit
- [ ] Monitor the first live trade end-to-end before walking away

---

## Known limitations / roadmap

- Greeks (theta/delta) come from REST snapshots only — DXLink streamer integration is
  pending; current ranking uses a premium-based theta proxy.
- US-market-hours check is weekday-only; full NYSE holiday calendar not yet wired in.
- No support yet for ratio calendars, double calendars, or rolling the long leg.
- Order fills are not reconciled against `state/open_spreads.json` — a rejected
  open is still recorded as if filled in dry-run mode. In live mode the bot
  dry-runs against tastytrade first to catch BP issues.

PRs welcome — the strategy module is intentionally small and self-contained.
