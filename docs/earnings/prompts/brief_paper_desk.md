Paper-desk brief (P017, paper only). Used by `hourly_monitor.md` at the first run of the day
(07:15 PT). Fill the braces: `{TODAY}` (YYYY-MM-DD), `{YYYYMMDD}` and `{DESK_FOLDER}`
(`state/earnings/daytrade/{TODAY}`). One agent a day, read-only, model opus, in the background.

Brad, 2026-11-11 12:19 PT: "lets add meta, nvdia and some of those other high liquidity stocks to the paper testing"

```text
BRIEF: paper desk for same-day iron flies (read-only), {TODAY}

You are a read-only research agent. Nothing here is a live trade. NEVER call
review_option_order, place_option_order, cancel_option_order or any other order, alert,
watchlist or settings tool. Write only inside /home/user/VantageTrader/{DESK_FOLDER}/ and do
not touch the git repository otherwise. Never guess a price. Never ask questions.

NAMES (never TSLA): SPY, QQQ, IWM, NVDA, META, AAPL, AMZN, MSFT, AMD, IBIT.

TOOLS. Load with ToolSearch:
"select:mcp__Robinhood__get_option_chains,mcp__Robinhood__get_option_instruments,mcp__Robinhood__get_option_quotes,mcp__Robinhood__get_equity_quotes"
Read the schemas first. Send independent calls in parallel (about 8 per message). On a rate
limit or transient error wait 15 s and retry, at most 3 times. Do the arithmetic with python.
Clock: `TZ=America/Los_Angeles date +%H:%M` is the Pacific time used below. To wait, run
python3 -c "import time; time.sleep(N)" with N at most 590 and a 600000 ms timeout, and
check the clock again.

STEP 0, WAIT. If the Pacific time is before 07:15, wait until 07:15 (the desk always opens 45
minutes after the market does; P031). If it is later, start at once and say so in the final
message.

STEP 1, OPEN (at 07:15 Pacific, or at once when started later).
a) get_option_chains(symbol) for each name. Keep the names whose expiration_dates include
   {TODAY}. The others are skipped today (reason "no_same_day_expiry").
b) get_equity_quotes for the kept names: spot = last_trade_price.
c) Body strike K = the listed {TODAY} strike nearest spot. Find it with
   get_option_instruments(chain_id, expiration_dates "{TODAY}", exact strike_price such as
   "172.5000"); a query without a type returns the call and the put. NEVER query an expiry
   without a strike. Probe neighbours until you know the strike step.
d) get_option_quotes for the K call and the K put. straddle_mid = call mid + put mid.
e) Wings: the listed strikes nearest K + straddle_mid (call) and K - straddle_mid (put), at
   least one strike step from K. Look them up and quote them.
f) credit_mid = body mids - wing mids. credit_natural = body bids - wing asks.
   width = the wider of the two wing distances. Skip a name (say why) when a body leg has
   no bid, credit_mid <= 0 or credit_mid >= width.
g) Append one line per name to {DESK_FOLDER}/paper_desk.jsonl (one JSON object per line):
   {"trade_id":"<SYM>-0DTE-{YYYYMMDD}-P1","record":"paper","live":false,"ts":"<UTC now, ISO>",
    "symbol":"<SYM>","kind":"intraday_0dte","structure":"iron_fly",
    "strikes":[put wing, K, call wing],"expiry":"{TODAY}","dte":0,"quantity":1,
    "entry_spot":..., "signal":{"straddle_mid":...,"straddle_pct":...,"atm_spread_pct":...},
    "legs":{"<K>C":{"id":"...","bid":...,"ask":...},"<K>P":{...},"<W>C":{...},"<W>P":{...}},
    "credit_mid":...,"credit_natural":...,"max_loss_usd":(width - credit_mid)*100,
    "max_profit_usd":credit_mid*100,"breakevens":[K - credit_mid, K + credit_mid],
    "paper_plan":{"take_profit_close_cost":0.5*credit_mid,"time_stop":"12:15 PT"}}
   atm_spread_pct = ((call ask - call bid) + (put ask - put bid)) / straddle_mid.

STEP 2, MARK at 10:15 Pacific. get_equity_quotes and get_option_quotes for every leg.
close_cost_mid = body mids - wing mids. close_cost_natural = body asks - wing bids.
Append one line per name: the same trade_id, "record":"paper","live":false,"ts", "symbol",
"kind":"intraday_0dte", and
"mark":{"time_pt":"10:15","spot":...,"legs":{"<label>":[bid, ask], ...},
        "close_cost_mid":...,"close_cost_natural":...,
        "pnl_mid_usd":(credit_mid - close_cost_mid)*100,
        "take_profit_hit": close_cost_mid <= 0.5*credit_mid}.
A name whose take profit is hit gets its RESULT line now (step 3 shape, "exit_rule":
"take profit at 10:15 PT") and is not marked again.

STEP 3, RESULT at 12:15 Pacific for every name without a result. Quote again and append:
the same ids, "result":true, "mark":{... "time_pt":"12:15" ...},
"pnl_mid_usd":(credit_mid - close_cost_mid)*100,
"pnl_natural_usd":(credit_natural - close_cost_natural)*100,
"pnl_pct_of_max_loss": pnl_mid_usd / max_loss_usd, "exit_rule":"12:15 PT mark",
"realized_move_from_entry": spot / entry_spot - 1.

FINAL MESSAGE (at most 15 lines, nothing else): the file path; one line per name with
strikes, credit, max loss, the 10:15 P/L and the result at mid and at natural; the skipped
names with reasons; the day's totals at mid and at natural; errors.
```
