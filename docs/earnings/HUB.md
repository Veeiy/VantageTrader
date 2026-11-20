# Trading hub page

Brad, 2026-11-17: "Make an artifact to show the live open p/l for open positions, along with
ytd, monthly, daily and hourly view that tracks by the minute with the trades and how were
performing. Should be like our own trading hub ui to give me more insight on all of our trades
and tracking. Along with what youre doing to improve the model and plans for healing and
detail what you learn as we continue trading and growing the model."

Page: https://claude.ai/artifact/MVp9t1rBTdDwxLtoCxP7ND (private to Brad). It is a dashboard
artifact: the page and its data live in the artifact's own store, not in published files.

## What feeds it

| Dataset | Kind | From |
|---|---|---|
| `book` | file | `scripts/earnings/hub/export.py`: positions.json, journal.jsonl, live_metrics.jsonl (open flies, legs, every closed result, the account snapshot) |
| `model` | file | the same script: rule versions, proposals, lessons, projection scores, replay evidence, the pilot, the paper desk, what is coming up |
| `quotes` | live | Robinhood `get_option_quotes` for the open legs |
| `spots` | live | Robinhood `get_equity_quotes` for the open symbols, SPY and IWM |
| `bars_a`, `bars_b` | live | Robinhood `get_option_historicals`: 5-minute bars for the Day view, 1-minute for the Hour view (ten contracts a call) |

- A live query runs in Brad's browser on his own Robinhood connector while he has the page
  open (every 60 seconds in market hours). The session does not feed quotes.
- No query, file or page text carries the account number. Positions and trades come from our
  ledger, so a hand trade shows on the page once it is recorded.
- P/L is trade based: realized on the exit date (Pacific), after fees; deposits are not P/L;
  open P/L is the credit minus the close cost at the mid. Paper results stay in their own panel.

## Refresh (head session)

After every fill, exit or hand trade is recorded and pushed, and at the daily reflection:

1. `python3 scripts/earnings/hub/export.py --repo /home/user/VantageTrader --out <scratchpad>/hub/out`
   and read `upload` and `live_documents_changed` in its output. Both empty: nothing to do.
2. For each file under `upload`: `Artifact` publish with `url` (the page), `file_path` and
   `asset: true`. Keep the `/_blob/<id>` it returns.
3. `ArtifactData` list `datasets` for the current versions.
4. One `ArtifactData` batch: for each uploaded file an `update` of `datasets/book` or
   `datasets/model` with `{"source": {"url": "/_blob/<id>"}, "updated": {"at": "<UTC now>",
   "by": "Claude, the trading session"}}` and `if_version`; and, when `live_documents_changed`
   is true, the `store_writes` listed in `<out>/live_args.json`, each with `if_version`.
5. Delete the replaced blob (`Artifact` delete with `url` and `path` = the old asset id).
6. When Brad has had the page open: `ArtifactData` list `data/users/me`, read `check` and
   `runs`, and fix what they name.

The out folder holds the hashes of the last upload. If it is gone, the first run uploads both
files again. The standby session does not refresh the hub.

## Changing the page

The sources are `scripts/earnings/hub/page/index.html`, `hub.css` and `hub.js`. They are stored
as the documents `files/index.html`, `files/hub.css` and `files/hub.js` (`{"text": ...}`).
Write a changed file with `ArtifactData` set or str_replace, pinned to the version read, and
keep the copy in the repo the same. The type's own guide (read it from the artifact before a
redesign) rules the page: every figure is marked with the dataset it comes from.

## Reading a chart with a finger (2026-11-17)

Brad: "when I scrub with my finger it should follow the accurate tracking and persist when im
scrubbing with my finger across the graph". Before, a finger that moved more than a few
pixels was taken by the browser as a scroll and the reading vanished (shown on 1 of 16 moves
in the test below). Now (`hub.js`: `frame`, `readable`, `lockScrub`; `hub.css`:
`touch-action: pan-y pinch-zoom` on a chart's drawing):
- the mark under the pointer answers (`elementFromPoint`), so a finger that slides sideways
  is followed from point to point, bar to bar and trade to trade;
- the reading stays after the finger lifts and goes away when something else is touched;
- a swipe that starts up or down on a chart still scrolls the page; a mouse works as before.
Every chart takes its readings through `readable(mark, fn)`: a new chart needs nothing else.
Test with real touch input: build the page into the local stand-in and drive it with
Playwright and CDP `Input.dispatchTouchEvent` (16 moves across each chart: the day curve
showed a reading on 16 of 16 with the crosshair within 6 px of the finger).

## Not checked yet (2026-11-17)

The page was built and checked against a local stand-in of the dashboard. It has not been
seen inside the real one: that needs Brad to open it once and allow the Robinhood connector.
