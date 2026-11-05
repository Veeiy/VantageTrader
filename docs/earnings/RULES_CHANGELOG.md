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
