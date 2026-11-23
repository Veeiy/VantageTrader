# Pricing a leg (rules v1.16.3, P059)

Brad, 2026-11-17: "when you were trading them one by one, you should do middle limit orders
instead of market. And use the data from last sales etc for better pricing judgement. That
would get rid of a lot of the slippage"

This is the price of every single-leg order of a structure, on entry and on exit, for a
contract whose bid-ask is wider than two ticks. A penny-wide same-day contract follows
`INTRADAY.md` step 6 instead: there the spread costs a cent and the time between the legs
costs more, so it is crossed at once. Every order is a limit order; nothing here changes that.

## 1. The fair price
1. Quote the leg (`get_option_quotes`). Read the bid, the ask, the mid and the broker's four
   fill hints: `low_fill_rate_buy_price`, `high_fill_rate_buy_price`,
   `high_fill_rate_sell_price`, `low_fill_rate_sell_price`. They come from recent executions:
   the high-fill price is where an order usually fills, and it sits inside the quoted spread.
2. Last sale. When the leg's spread is more than 8% of its mid, read its prints
   (`get_option_historicals`, 5-minute bars of today, the last two bars with volume). A print
   inside the current bid-ask moves the fair price halfway from the mid toward it. A print
   outside the current quote is stale and ignored. No print: the mid stands.
3. The fair price F is that number rounded to the tick in our favor (down for a buy, up for a
   sell).

## 2. The ladder
One step at a time. To move a step: cancel, confirm cancelled with zero fills, place a new
order with a new ref_id.

| Step | Buy at | Sell at |
|---|---|---|
| 1 | the lower of F and `low_fill_rate_buy_price` | the higher of F and `low_fill_rate_sell_price` |
| 2 | F | F |
| 3 | `high_fill_rate_buy_price` | `high_fill_rate_sell_price` |
| 4 | one tick at a time toward the ask | one tick at a time toward the bid |

Step 4 runs only while the structure's total stays at or better than its floor (the gate's
`limit_floor` on an entry; the wing width rule on an exit).

How long a step rests depends on what is at risk while it waits:

| Order | Starts at | A step rests |
|---|---|---|
| Wings on an entry (nothing is open yet) | step 1 | 30 seconds |
| The two body legs of an entry, sent together | step 2 | 20 seconds |
| The body leg that is missing once the other has filled | step 3 | 15 seconds, done inside 60 |
| Buybacks of the short legs on an exit, sent together | step 2 | 45 seconds |
| A wing sold after its short leg is flat | step 1 | 30 seconds |

A fly that is one-sided for 60 seconds is finished or unwound as rules v1.16.2 say
(`INTRADAY.md` step 6d). Being one-sided is what cost $13.5 on the IWM fly of 2026-11-17; the
spread itself cost two cents. So the patient steps are spent where nothing is exposed.

## 3. Record, so the ladder learns
The live-metrics execution block carries one row per leg under `legs_detail`:
`{leg, side, bid, ask, mid, last_print, fair, hint_low, hint_high, start, fill, step, seconds}`.
`fill_vs_mid` for a leg is fill / mid for a sell and mid / fill for a buy.

At the reflection after every 20 recorded legs: at which step the fills happened and what
each step gave up against the mid. The start of a ladder moves to the step where at least
half of that kind of order filled.

## 4. Measure (P059)
After 20 legs on contracts wider than two ticks: the average give-up against the mid is at
most a third of the half-spread (crossing gives up all of it), and no entry was one-sided for
more than 60 seconds. Review on 2026-12-05.

## 5. Closing a fly when the buying power is tight (2026-11-17, HD)
Buying a short leg back takes its whole price in buying power, and a fly's collateral comes
back only when the last short leg of its wider side is gone. Work down this list:

1. Read the buying power and the asks of the two short legs.
2. Both fit together: buy both back together (the normal case), then sell the wings.
3. Only the dearer one fits: buy it back first, sell its wing at once (that cash is needed),
   buy back the other short leg (the collateral comes back with it), sell the last wing.
   HD on 2026-11-17: 1,043 of buying power; put 925, its wing +150, call 233, last wing +13.
   The three risk legs took 35 seconds.
3b. The dearer one does not fit alone (P082, 2026-11-23): buy back the CHEAPER short leg first
   (it takes its price in buying power and releases nothing: a review of either buyback on an
   open DKS fly showed collateral 0). The dearer leg is then the last short, and its buyback
   releases the fly's collateral, which counts toward that same order: PDD on 2026-11-20, a 670
   buyback with 94.84 of buying power and 600 of collateral coming back, accepted and filled.
   Review the dearer buyback after the cheaper one is flat and place it only when the review
   shows the collateral credit and no buying-power alert (P076). Then sell both wings, the
   in-the-money side first. It reaches as far as buying power plus the wing width.
4. The dearer one does not fit: free buying power first (close a position that is due, sell
   leftover long wings). Never sell a wing while its short leg is open.
5. Still short: a bridge. Buy back the cheaper short leg. Buy to open the same type one or
   two strikes inside the dearer short leg, between it and its wing: the short leg is then
   covered by a narrower spread and the difference in collateral comes back. Sell the old
   wing, buy back the short leg, sell the bridge. NOT tested at the broker: read the buying
   power after the bridge fills; if it did not rise, sell the bridge back and go to 6.
6. Last resort: the 4-leg closing ticket to Brad, with a push, naming the step that failed.

Record on every exit: `bp_at_exit`, `dearer_short_ask`, and the step of this list that was used.

