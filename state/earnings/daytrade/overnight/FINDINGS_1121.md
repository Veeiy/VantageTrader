# Overnight fly test, 2026-11-21 (hypothesis H013; bar fixed in PLAN.md line C on 2026-11-16)

Trade: sell a next-day-expiry iron fly at 12:30 PT on session P (body at the whole strike nearest the
12:30 price, wings at about 1x the body straddle), buy it back on the morning of D. Prices are
30-minute option bars (last trades); a mark counts only when the body passes put-call parity.
Costs: $8 a fly on SPY and QQQ, $5 on IWM (`scripts/earnings/overnight_replay.py`).
Nights: D = 2026-08-19 to 2026-11-20, 67 a name. The 4 oldest (D 08-19 to 08-24) have gap-fill
entry bars (older than about three months) and are left out.

## The bar: buy back at 07:00 PT, after costs, pooled and clustered by night
| | Nights | Flies | Mean a fly | se | t | Worst |
|---|---|---|---|---|---|---|
| SPY | 45 | 45 | +$2.5 | 10.2 | 0.24 | -229 (2026-11-04) |
| QQQ | 44 | 44 | -$30.5 | 16.4 | -1.86 | -239 (2026-09-17) |
| IWM | 48 | 48 | -$1.6 | 6.3 | -0.26 | -107 (2026-11-09) |
| Pooled, one number a night | 60 | 137 | -$12.0 | 8.5 | -1.41 | -172 a night (2026-11-09) |
Bar: mean of at least +$10 and t of 2 or more. **Fails.** The line is dropped (PLAN.md line C).

## Description, not a rule: the same 98 flies at each buy-back time, after costs
| Group | Flies | 07:00 | 07:30 | 08:00 | Worst (07:00) |
|---|---|---|---|---|---|
| All | 98 | -$13.9 | -$19.9 | -$22.1 | -239 |
| Quiet night (move under 0.5%) | 56 | +$20.7 | +$17.7 | +$14.9 | -114 |
| Gap night (0.5% or more) | 42 | -$60.2 | -$70.1 | -$71.5 | -239 |
The 06:30 PT bar is a single print on almost every contract and fails parity on most nights: 22
flies only, not compared. Quiet nights pay and gap nights take it all back, as on 25 nights in the
first read; whether a night will gap is not known at 12:30 PT, so this is not a filter.

## Limits
Last-trade prints, not mids; one quarter (a falling market from late October); 4 nights a name
unpriced; the overnight premium in the literature is measured on monthly S&P options, not
next-day flies with this spread cost.
