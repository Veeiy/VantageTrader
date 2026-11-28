# Weekly scorecard, 2026-11-23 to 2026-11-27 (four sessions, Friday a half day)

## Result (after fees)
| Trade | Line | Edge | Move / implied | P/L |
|---|---|---|---|---|
| DKS 120/135/150 (Brad's ticket, four gates waived; legged out by the agent 11/24) | earnings, owner lane | 0.73 | 1.36x | -275.33 |
| ANT: 15 of Brad's 20 shares, sold by him Sunday evening at 91.10 | owner hand | | | +16.64 |
- Week -258.69: earnings flies -275.33 (1 trade, 0 wins), owner hand +16.64; pilot and non-earnings no trade.
- Since the start: 18 closed -91.99, adjustments +187.62, total +95.63. Win rate 56% (10 of 18), edge bias 1.18 (moves ran 18% over what the ratio implied), realized/implied 0.89.
- Cost against mid: 0.058 of the credit over 17 closed trades, 0.042 on 12 earnings flies, 0.038 on the last ten (replay assumes 0.07, breakeven 0.09).
- Account 1,874.15 (11/20 close) to 1,453.19 (11/27, 13:13 PT, ANT at 91.66 after hours): DKS -275, Brad's 200 out on 11/23, the rest ANT against last Friday's mark. Buying power 993.89.
- The agent itself opened nothing. Monday's names were stopped by gates and caps; from Tuesday 06:52 PT the breaker stood over everything (streak 3; 2 without ANT, P092), and only HPQ and LI were stopped by it alone.

## Names we skipped, scored (1x fly, after a 7% cost, option last-trade prints)
| Name | Blocked by | Result | Did the rule help? |
|---|---|---|---|
| ZM | edge 1.13, +6.5% on the day | +135 | no: a winner missed |
| ANF | edge 1.40 | -576 | yes |
| ADI | +7.5% before the open | -812 | yes |
| SMTC | +16.1% before the open | -97 | yes |
| DELL | -11.6% on the day, edge 1.33, over the cap | +194 at the bar close (+498 on a stale print) | no on outcome |
| DLTR | near-miss half cap 175 | -194 | yes |
| BURL | size cap (floor fly 637 against 350) | +52 | no difference |
| ADSK | $600 cap at the narrowest wings (edge 0.60) | -134 (2x: +58) | yes at 1x |
| WDAY | $350 cap, spread 14.6% (edge 0.74) | +306 | no on outcome |
| HPQ x2, LI x6 | breaker only | -92 at the mid, -326 at the natural (quotes 06:38 PT 11/25) | yes |
| AMBA | spread 71% of mid | not priced | n/a |
- Edge and intraday-move gates (ZM, ANF, ADI, SMTC, DELL): -1,156 kept out, two winners missed (+328). Caps (DLTR, BURL, ADSK, WDAY): +30 net. Nine names, -1,126.
- Same-day paper desk, whole record: 78 flies on 11 days, -1,021 at the mid; at the natural -2,941 held to the bell and -3,801 crossing every quote. Two days (11/20, 11/25) carry the whole loss. No desk day since Wednesday.

## Rules: helped or hurt this week
- Breaker (halted Tuesday): the two names it alone blocked both lost. Helped, 2 names. It also stopped the pilot on three sessions with nothing live to compare (the desk's IWM fly: +19.5 at 10:15 PT Tuesday, -52 of 55 Wednesday).
- Edge cutoff and intraday-move gate: helped (above).
- Owner waivers: the week's only live loss. The rules said no trade on DKS (macro veto, name cap, exit feasibility); the ticket stated the waivers and the share of the account before he placed it.
- 30% per-name ceiling (P044): not kept. Brad's ANT shares were 32% of the account from Tuesday with nothing said, and the gate's $600 cap had drifted to 41% of the account. No order broke it; both are closed today (P103).
- v1.2.2 on the mid: right on DKS by 150 against holding to expiry. One exit; the practice stands (P088).
- Macro veto: hard at 07:27 PT Wednesday (VIX 34.08), off by 11:47, no name to enter. Which reading counts is deferred (P096).
- Near-miss tier: no tier trade this week (3 closed, -14.73); stays at half size to 12/18 or 10 trades (P097).
- Wing floor 0.9x (P036): nine flies at 0.92x to 1.48x, one structure blocked. It binds through the caps, not alone.
- Grades this week: A 22, B+ 2, B 4, B- 1, C+ 3, C 11, D 2 (45 decisions). The C's and D's fall in two groups: a claim or a number written before it was checked (the desk totals, "VIX 34", the reset deadline, the pilot cost, the universe note), and a step or a limit not kept because nothing checked it (the daemon, the news check, three desk imports, the ceiling).

## Lessons ledger
- Held: L010 selfcheck (+12 / -1), L014 do it now (+10), L017 executable plans (+9), L027 owner ticket (+5), L028 timers (+5 / -1), L026 cost (+5 / -2).
- Hypotheses: H008 tight-end edge +14 / -9 (under its bar; P093 declined, back to tested); H001 intraday gate +13 / -9 (same); H009 long straddle +15 / -14; H004 wide-spread test +6 / -1; H010 expiry on exit day +4 / -0; H011 same-day no edge +4 / -3; H014 drift +2 / -1; H015 exit-priced +2 / -0 (replay test Saturday); H016 VIX filter +1 / -0; H003 clusters +1 / -2; H007 +0 / -1. None ready to propose, none weak.
- Proposals this week: 26 logged (P078 to P103). Verified: P065, P080, P082, P036, P037, P099 worked; P072, P032, P083 inconclusive. 57 implemented proposals have no verified event yet (P102: 20 a Saturday).
- Decided under the delegation: P097 near-miss tier stays at half ("near-miss off"), P088 the mid test stands ("v1.2.2 on the natural"), P093 H008 not adopted ("adopt H008"), P103 the 30% ceiling in the gate ("no ceiling"). Deferred: P084, P091, P096.
- Open with Brad (hard limits): P092 breaker counts option structures only ("yes P092" or "no P092"; "reset breaker" lifts the halt), P053 data feed, P050 tastytrade.
- Multi-leg: not tried this week. The attempt rides on the agent's first entry of a day (P051) and the agent made none. Last result 11/20: the review step accepts 2 legs, placing refuses.
- Usage at list prices, each before its reflection run: Mon $57, Tue $40, Wed $35, Thu (holiday) $13, Fri $43.
