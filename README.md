# VantageTrader

Auto-managed **0DTE calendar spread** bot for [tastytrade](https://developer.tastytrade.com/).

Streams live option greeks via DXLink, picks strikes by short-leg delta target,
ranks candidates by theta-per-dollar, and manages each spread to a profit target,
stop-loss, drift, or end-of-day close.

> **Sandbox-first.** Defaults to `api.cert.tastyworks.com` and `dry_run: true`.
> Every order is logged in dry-run mode; nothing is submitted until you flip the
> flag. Validate decisions before risking real capital.

---

## Strategy

A **horizontal calendar spread** at (or near) ATM, with the short leg expiring
**today** (0DTE):

```
LONG  1x option   strike K   30-60 DTE   <- collateral, long vega, slow theta
SHORT 1x option   strike K    0 DTE      <- theta engine (fastest decay)
```

Same strike on both legs, same option type (both calls or both puts). We harvest
the steep 0DTE theta on the short while the long bleeds slowly and caps loss to
the net debit paid.

### Strike selection (delta-targeted)

For each candidate (side, short_exp, long_exp), the bot scores every listed strike
whose **0DTE short-leg delta** falls inside `[short_delta_min, short_delta_max]`.
The strike whose `|delta|` is closest to the band midpoint wins for that combo.

- `0.40-0.55` (default) → **ATM**. Max theta, max P/L if price pins K.
- `0.20-0.30` → slightly OTM. Lower premium, less pin risk, lower max P/L.
- Set to whatever fits your risk preference.

### Direction (call vs put calendar)

P/L diagrams for call vs put calendars at the same strike are economically very
close (put-call parity). What differs is **assignment risk on the short**.
`entry.direction` controls the choice:

- `auto` (default) — spot `<` K ⇒ calls (short call is OTM); spot `>=` K ⇒ puts.
- `call` / `put` — force one side.
- `both` — evaluate both sides per (long_exp, short_exp); best score wins.

### Entry filters

| Filter | Default | Why |
| --- | --- | --- |
| `short_delta_min` / `max` | 0.40 / 0.55 | Strike selection band (ATM by default) |
| `iv_rank_max` | 60 | Calendars are long vega — prefer low IV so it can expand |
| `skip_if_earnings_within_days` | 2 | 0DTE on earnings day is roulette |
| `max_debit_per_spread` | $250 | Per-contract risk cap |
| `min_open_interest_short` / `long` | 500 / 100 | Liquidity floor |
| `max_bid_ask_spread_pct` | 15% | Avoid wide markets |
| `min_theta_per_dollar` | 0.0005 | Rejects inefficient setups (daily \|θ\| / debit) |

### Ranking score

```
score = theta_per_dollar  *  iv_term_kicker  *  liquidity_factor
```

- `theta_per_dollar` = `|short_theta| / debit_paid` — daily decay per $1 at risk
- `iv_term_kicker`   = `1 + max(0, (long_iv - short_iv) * 2)` — rewards
  contango in IV term structure (good for long-vega calendars)
- `liquidity_factor` = `clamp(1 - bid_ask_spread_pct / max_bid_ask_spread_pct, 0, 1)`

Top scorer per underlying is the candidate; the global ranked list is consumed
until `max_concurrent_spreads` or `max_total_debit` caps fill.

### Management (every `manage_every_seconds`)

| Trigger | Action |
| --- | --- |
| P/L `>=` `profit_target_pct` (25%) | Close spread |
| P/L `<=` `-stop_loss_pct` (50%) | Close spread |
| Underlying drifted `>` `underlying_drift_strikes` from K | Close spread |
| Long leg DTE `<=` `close_long_at_dte` (14) | Close spread |
| 0DTE short + `<=` `close_short_minutes_before_close` mins to bell | Close spread |

> Note: 0DTE shorts can't be rolled within the same session. The engine
> re-evaluates entries on the next trading day during the entry window.

---

## Architecture

```
                       ┌────────────────────┐
                       │  TastytradeClient  │  (REST: auth, chains, orders, metrics)
                       └────────┬───────────┘
                                │
   ┌────────────────────┐       │       ┌────────────────────────┐
   │   DXLinkStreamer   │◄──────┼──────►│    CalendarScanner     │
   │  (wss, Greeks evt) │       │       │ build_candidate(...)   │
   └─────────┬──────────┘       │       └───────────┬────────────┘
             │  latest_greeks    │                  │ ranked candidates
             ▼                   ▼                  ▼
                       ┌────────────────────┐
                       │       Engine       │
                       │  scan→enter→manage │
                       └────────┬───────────┘
                                │
                                ▼
                       ┌────────────────────┐
                       │  state/*.json      │
                       └────────────────────┘
```

---

## Quick start

### 1. Install

```bash
git clone <this repo>
cd VantageTrader
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Authenticate (OAuth Personal Grant)

> Username/password (`/sessions`) auth was discontinued by tastytrade on
> 2025-12-01. Personal bots now use an **OAuth2 refresh-token grant**.
> The bot does the token exchange and refresh for you — you just need to
> generate a long-lived `refresh_token` once.

**Sandbox setup** (do this first):

1. Create a sandbox account at <https://developer.tastytrade.com/sandbox/>.
2. Sign in to <https://cert.tastyworks.com> with that sandbox login.
3. **Manage > API > Open API access** → agree to the terms.
4. **Manage > API > OAuth application** → "Create application".
   - Save the `client_secret` it shows you. You can't view it again.
5. Open the application → **"New Personal OAuth Grant"** → check the scopes
   you need (`read`, `trade`, and `openid` covers this bot) → save.
   - Copy the `refresh_token`. Treat it like a password.

**Live setup**: repeat steps 3–5 on <https://my.tastytrade.com> with your real
account. The `client_secret` and `refresh_token` differ from sandbox.

### 3. Configure

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

Edit `.env`:

```bash
TASTY_ENV=sandbox
TASTY_CLIENT_SECRET=<from your OAuth application>
TASTY_REFRESH_TOKEN=<from your Personal OAuth Grant>
TASTY_ACCOUNT_NUMBER=<your account number, e.g. 5WT00000>
```

How auth works at runtime: on startup the client POSTs to `/oauth/token` with
`grant_type=refresh_token` and your `client_secret` + `refresh_token`, gets
back a ~15-minute `access_token`, and sends `Authorization: Bearer <token>`
on every API call. It auto-refreshes 60 s before expiry, and re-tries once
on any unexpected `401`.

Edit `config.yaml`:
- `underlyings` — stick to liquid 0DTE-listed names (SPY, QQQ, IWM, SPX, large caps)
- `entry.short_delta_min/max` — ATM (0.40-0.55) or OTM (0.20-0.30)
- `entry.direction` — `auto` / `call` / `put` / `both`
- `risk.*` — concurrency and dollar caps

### 4. Smoke test

```bash
python -m vantage_trader accounts
```

If you see your account listed, the OAuth flow worked end-to-end.

### 5. Scan once (dry-run, no orders)

```bash
python -m vantage_trader scan-once
```

Logs every candidate considered, with delta, theta-per-dollar, and score.

### 6. Run the engine

```bash
python -m vantage_trader run
```

With `dry_run: true`, every order is logged but nothing is submitted. Watch the
logs for at least a week before flipping the flag.

---

## Project layout

```
src/vantage_trader/
├── __main__.py              # CLI entrypoint
├── config.py                # env + yaml loaders + validation
├── engine.py                # scan / enter / manage orchestration
├── logging_setup.py
├── strategy/
│   └── calendar.py          # CalendarScanner, CalendarManager, order builders
└── tastytrade/
    ├── client.py            # async REST client (OAuth refresh-token auth)
    ├── streamer.py          # DXLink websocket (Greeks event)
    └── models.py            # OptionContract, OrderRequest, OrderLeg, etc.
tests/
├── test_calendar.py         # management rule coverage
├── test_models.py           # OCC/streamer symbol formatting
├── test_oauth.py            # OAuth refresh, bearer header, 401 retry
├── test_scanner.py          # strike selection / delta filter / direction
└── test_streamer.py         # DXLink message decoding
```

## Tests

```bash
pytest
```

33 tests cover: OAuth refresh-token exchange, preemptive refresh near expiry,
401-triggered refresh-and-retry; OCC and DXLink streamer-symbol formatting;
debit/credit order payloads; every management rule (profit/stop/drift/long-DTE/
0DTE-eod/hold); delta-band strike selection; direction policy; and DXLink
Greeks frame decoding.

---

## Safety checklist before going live

- [ ] Run `dry_run: true` for at least a full week in sandbox
- [ ] Verify every `OPEN`, `CLOSE`, `CAND`, `MANAGE` log matches expectations
- [ ] Confirm `state/open_spreads.json` survives bot restarts
- [ ] Set conservative `max_concurrent_spreads` and `max_total_debit`
- [ ] Switch `TASTY_ENV=live` and `dry_run: false` **separately**, not in one edit
- [ ] Monitor the first live trade end-to-end before walking away
- [ ] 0DTE on broad indices (SPY/QQQ/SPX) only; single-name 0DTE chains can be thin

---

## Known limitations / roadmap

- US-market-hours check is weekday-only; no NYSE holiday calendar yet
- No fill reconciliation — `state/open_spreads.json` assumes orders fill at the
  mid we submitted. In live mode we dry-run against tastytrade first to catch
  BP issues; we do not yet poll order status for partial/no-fill detection.
- No support yet for ratio calendars, double calendars, or rolling the long leg
- DXLink streamer doesn't auto-reconnect on disconnect (single-shot connect)

PRs welcome.
