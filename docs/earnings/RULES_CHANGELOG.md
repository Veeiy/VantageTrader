# Live rule changelog

The scheduled head-agent check-ins trade by these rules. The engine's HARD_CAPS
are still at v1 and get updated in the next engine pass (together with the
early-assignment fix) before the engine trades on its own.

## v1.1 (2026-11-05)

Requested by Brad after two no-trade days: "don't be as strict / slight threshold roll back".

### Loosened (fill quality and coverage)
- ATM bid-ask spread: max 12% -> **25% of mid**. A trade whose spread is between
  12% and 25% is capped at **$350 max loss**. Unchanged: never accept less than
  92% of the mid credit, and keep the $50 exit-slippage reserve.
- Regime guard: trips when the 20-session average absolute daily move is
  **>= 1.25x** the historical average earnings move (was 1.0x).
- Positions: up to **2 open at once**, total max loss <= $650, different sectors.
- Scan breadth: about 60-80 names a day (3-4 vol-analyst agents) instead of about 40.

### Kept, with this week's evidence
- Intraday move <= 5% (5-7% only on a sector move with no stock-specific news):
  ARM was skipped Wed at -5.5%; it fell to about $173 by the Thursday 06:45 exit,
  on the fly's $172.50 lower wing (about -$500 avoided, estimate).
- Edge ratio <= 0.85: QCOM (edge 1.03) moved -9.4% after earnings; APP (no fit)
  moved +31%. Both would have been near max loss.
- Defined risk only, $650 total cap, TSLA blocked, stock-specific bombshell veto,
  price >= $10.

### What v1.1 would have done this week (rough estimates)
- Wed: ALB iron fly (spread 15%, edge 0.66, max loss about $330). ALB rose about
  3.5% after its report: small win, roughly +$50 to +$120.
- Thu: WYNN iron fly 72/79/86 (spread 24.5%, $3.64 mid credit, $336 max loss).
  Result pending its Thursday after-close report.

## Scorecard: week of 2026-11-02 (no live trades)

Prices: Thursday 12:00 PT spot; Thursday close; Friday 06:46 PT. P/L figures are
estimates for one iron fly centered at the strike nearest the entry-time spot.

| Name | Skip rule | Post-report move | Would-be fly result | Rule verdict |
|---|---|---|---|---|
| ARM (Wed) | intraday -5.5% | ~$173 at Thu 06:45 vs 192.5 body | about -$500 (near max loss) | saved |
| QCOM (Wed) | no edge (1.03) | -9.4% | near max loss | saved |
| APP (Wed) | too large for account | +31% | max loss | saved |
| ALB (Wed) | would pass v1.1 | +3.5% | about +$50 to +$120 | missed small win |
| WYNN (Thu) | spread 24.5% | +2.8% (inside 75.36/82.64) | about +$75 at mid, -$65 at natural | neutral |
| VST (Thu, Fri BMO) | regime guard | +7.5% vs 2.11% hist avg | about -$50 to -$150 | saved |
| IREN (Thu) | intraday -13.6% | +22.2% | max loss (~-$340 at 6 contracts) | saved |
| NET (Thu) | intraday -9.4% | +11.9% | near max loss | saved |

Takeaways: the intraday-move rule and the regime guard avoided roughly $1,400 of
would-be losses; the missed upside was small (ALB, possibly WYNN). Long straddles
would not have helped either: IREN and NET roughly matched or undershot their
implied moves from entry time. Account value went from $750 to $650 on 11/05 from
a $100 transfer to checking, not from trading; the risk budget now scales with
buying power: min($650, 0.93 x BP) minus the $50 exit reserve.
