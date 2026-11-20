Spread scan for same-day option names (rules v1.15.1, docs/earnings/INTRADAY.md "Which names").
Started by the morning run (`exit_scan.md`, part A2) at about 06:50 PT on the scan days: Tue
2026-11-17, Wed 2026-11-18, Fri 2026-11-20, then every Friday. One agent, read-only, model opus,
in the background. Fill the braces: `{TODAY}` (YYYY-MM-DD), `{UNIVERSE_FILE}` (the newest file in
`state/earnings/daytrade/universe/`), `{SCAN_FOLDER}` (`state/earnings/daytrade/{TODAY}`).

Brad, 2026-11-16: "Scan the market for optimal daytrading options. Lets not lock ourselves to
just a few tickets. But liquidity and tightish spreads is important not to eat into profits".

```text
BRIEF: spread scan for same-day option names (read-only), {TODAY}

You are a read-only research agent. Nothing here is a live trade. NEVER call
review_option_order, place_option_order, cancel_option_order or any other order, alert,
watchlist or settings tool. Write only inside /home/user/VantageTrader/{SCAN_FOLDER}/ and in a
scratch folder of your own named scan_{TODAY} under the session scratchpad. No git commands.
Never guess a price. Never ask questions. Be done by 07:22 Pacific
(`TZ=America/Los_Angeles date +%H:%M`): hand back what you have at that time.

GOAL. For every name in /home/user/VantageTrader/{UNIVERSE_FILE} that has an option expiration
TODAY ({TODAY}) and is not marked blocked, measure how tight its same-day at-the-money market
is, and price the same-day iron fly the pilot would sell. Rank the names.

TOOLS. Load with ToolSearch:
"select:mcp__Robinhood__get_option_instruments,mcp__Robinhood__get_option_quotes,mcp__Robinhood__get_equity_quotes,mcp__Robinhood__get_index_quotes"
Read the schemas first. Send independent calls in parallel, 8 per message. On a rate limit or
transient error wait 15 s and retry, at most 3 times. Do the arithmetic with python.

STEP 0. If the Pacific time is before 06:50, wait until 06:50 (python3 -c "import time;
time.sleep(N)" with N at most 240, repeated as needed). Read the universe file with python and list the names whose
expiries["{TODAY}"] is true and blocked is false. Never include TSLA. AT MOST 25 NAMES (P074, 2026-11-20: the 40-name scan cost $9 in 57 calls; target $4 or less, at most 120 tool calls in all): every
name of class "daily" and "mon_wed_fri" first, then "other" and "weekly" names by
avg_options_volume (highest first) until the list holds 25. Say in the output which names were
left out.

STEP 1, SPOT. get_equity_quotes for the stock and fund names (batches of 20): spot =
last_trade_price, prev_close = adjusted_previous_close. Index products (is_index true): use
get_index_quotes if it quotes them; if not, record the name with reason "no_spot" and skip it.

STEP 2, BODY. Body strike K = the listed {TODAY} strike nearest spot. Find it with
get_option_instruments(chain_symbol=<name>, expiration_dates="{TODAY}", strike_price="<K as
123.0000>"); a query without a type returns the call and the put. NEVER query an expiry without
a strike. Strike steps: usually 1 for index funds, 0.5 to 2.5 for stocks under 200, 2.5 or 5
above; probe neighbours until you have the listed strike nearest spot and know the step.
get_option_quotes for the K call and K put: bid, ask, open_interest, volume if given.
straddle_mid = call mid + put mid. straddle_pct = straddle_mid / spot.
spread_pct = ((call ask - call bid) + (put ask - put bid)) / straddle_mid.
EARLY DROP: a body leg with no bid, or spread_pct above 0.08: record the numbers with reason
"spread" and do no more work on the name.

STEP 3, WINGS (names still alive). Wing strikes: the listed strikes nearest K + straddle_mid
and K - straddle_mid, at least one strike step from K. Look up the wing call and the wing put
(exact-strike queries with type) and quote them.
credit_mid = body mids - wing mids. credit_natural = body bids - wing asks.
width = the wider wing distance. max_loss_usd = (width - credit_natural) * 100.
cost_round_trip_usd = 2 * (credit_mid - credit_natural) * 100   (crossing every spread, in and out)
cost_share = cost_round_trip_usd / (credit_mid * 100).

OUTPUT. Write /home/user/VantageTrader/{SCAN_FOLDER}/scan.json:
{"date":"{TODAY}","as_of_pt":"HH:MM","universe_file":"...","n_names":N,
 "names":[{"symbol","spot","prev_close","pre_move": spot/prev_close - 1,"K","strike_step",
   "call":{"id","bid","ask","oi"},"put":{"id","bid","ask","oi"},"straddle_mid","straddle_pct",
   "spread_pct","wings":{"call_strike","put_strike","call":{"id","bid","ask"},"put":{"id","bid","ask"}}|null,
   "credit_mid","credit_natural","width","max_loss_usd","cost_round_trip_usd","cost_share",
   "fits_probe_cap": max_loss_usd <= 150, "reason": null|"spread"|"no_spot"|"no_bid"|"error","notes":""}],
 "ranking_by_cost_share":[symbols, lowest first, only names with wings],
 "errors":[...]}
All percentages as fractions (0.012, not 1.2).

FINAL MESSAGE (at most 25 lines, nothing else): the file path and the time; then one line per
name that got wings, lowest cost_share first: SYMBOL spot straddle% spread% credit mid/natural
width max loss cost round trip cost share; then the names dropped for spread with their spread%;
then the names skipped and why; anything odd in one line.
```
