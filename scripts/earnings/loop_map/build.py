"""Builds the Trading Loop Map page from the replay numbers. Charts are drawn to scale here.

    python3 scripts/earnings/loop_map/build.py <output folder>

The page is published as the artifact "Trading Loop Map"
(https://claude.ai/artifact/DmYhPS8UVrQM2uNi2ixCdH): build it into the folder it was last
published from (the session scratchpad, loop_map/) and publish that index.html to the same
link. The text below is the page's content as of 2026-11-16; edit it here when the process
changes. style_base.css holds the page's design tokens and base styles.
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parents[2]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
base_css = (HERE / "style_base.css").read_text()

summ = json.loads((REPO / "state/earnings/daytrade/replay/summary.json").read_text())
times = ["08:00", "08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30"]
vals = [summ["time_exit"][t]["flies"]["mean"] for t in times]
wins = [summ["time_exit"][t]["flies"]["win_rate"] for t in times]

# ---------------- chart A: average result per fly by exit time (all values are at or below zero)
def chart_a():
    x0, pitch, bw, y0, k = 46, 31, 19, 30, 7.6      # k px per dollar; -16 -> y0 + 121.6
    out = ['<svg viewBox="0 0 360 190" role="img" aria-label="Average result per same-day fly after costs by exit time. Every exit is below zero: minus 15 dollars at 8:00, minus 6 at 9:30, minus 13 at 11:00, minus 3 at 12:30.">']
    for g in (0, -5, -10, -15):
        y = y0 - g * k
        out.append(f'<line class="grid{" zero" if g == 0 else ""}" x1="40" x2="352" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="ax" x="35" y="{y + 3.5:.1f}" text-anchor="end">{"$0" if g == 0 else "-$" + str(-g)}</text>')
    for i, (t, v, w) in enumerate(zip(times, vals, wins)):
        x = x0 + i * pitch
        h = max(-v * k, 1.0)
        r = min(4.0, h / 2)
        key = t == "11:00"
        d = (f"M{x},{y0} h{bw} v{h - r:.1f} a{r},{r} 0 0 1 -{r},{r} h-{bw - 2 * r:.1f} a{r},{r} 0 0 1 -{r},-{r} z")
        lab = t.lstrip("0")
        out.append(f'<path class="bar{" key" if key else ""}" d="{d}"><title>Exit {lab} AM PT: {"-" if v < 0 else ""}${abs(v):.0f} a fly on average, {w * 100:.0f}% winners</title></path>'.replace("12:00 AM", "12:00 PM").replace("12:30 AM", "12:30 PM"))
        out.append(f'<text class="ax" x="{x + bw / 2:.1f}" y="176" text-anchor="middle">{lab}</text>')
        if t in ("08:00", "11:00", "12:30"):
            out.append(f'<text class="val" x="{x + bw / 2:.1f}" y="{y0 + h + 12:.1f}" text-anchor="middle">-${abs(v):.0f}</text>')
    xk = x0 + times.index("11:00") * pitch + bw / 2
    out.append(f'<text class="note" x="{xk:.1f}" y="14" text-anchor="middle">pilot exits here</text>')
    out.append(f'<line class="tick" x1="{xk:.1f}" x2="{xk:.1f}" y1="18" y2="{y0 - 2}"/>')
    out.append("</svg>")
    return "\n".join(out)

# ---------------- chart C: how often a stop rule ends a no-edge pilot by luck (IWM, one contract, 20 trades)
ROWS = [("budget", "-$150 in total", 22.6, "old"), ("budget", "-$200", 11.0, ""), ("budget", "-$300", 1.5, ""),
        ("budget", "-$500", 0.1, "now"), ("streak", "3 losses in a row", 60.4, "old"),
        ("streak", "5 in a row", 12.0, ""), ("streak", "6 in a row", 5.1, "now")]

def chart_c():
    xb, k, rh = 132, 2.3, 26                         # k px per percentage point; 70% -> 161 px
    out = ['<svg viewBox="0 0 360 236" role="img" aria-label="Share of 20-trade runs in which a stop rule ends a pilot with no edge by luck alone. A budget of 150 dollars: 23 percent. 200: 11 percent. 300: 2 percent. 500: under 1 percent. Three losses in a row: 60 percent. Five: 12 percent. Six: 5 percent.">']
    y = 8
    last = None
    for grp, label, pct, tag in ROWS:
        if grp != last:
            y += 6 if last else 0
            out.append(f'<text class="grp" x="8" y="{y + 11}">{"Loss budget" if grp == "budget" else "Losing streak"}</text>')
            y += 20
            last = grp
        w = max(pct * k, 1.5)
        r = min(4.0, w / 2)
        d = f"M{xb},{y} h{w - r:.1f} a{r},{r} 0 0 1 {r},{r} v{14 - 2 * r:.1f} a{r},{r} 0 0 1 -{r},{r} h-{w - r:.1f} z"
        shown = "under 1%" if pct < 1 else f"{pct:.0f}%"
        out.append(f'<text class="rl" x="{xb - 8}" y="{y + 11}" text-anchor="end">{label}</text>')
        out.append(f'<path class="bar{" key" if tag == "now" else ""}" d="{d}"><title>{label}: stops the pilot by luck in {shown} of runs</title></path>')
        extra = {"old": '<tspan class="tagold"> was</tspan>', "now": '<tspan class="tagnow"> now</tspan>'}.get(tag, "")
        out.append(f'<text class="val" x="{xb + w + 6:.1f}" y="{y + 11}">{shown}{extra}</text>')
        y += rh
    out.append("</svg>")
    return "\n".join(out)

EXTRA_CSS = """
/* Added 2026-11-16: status strip, two lines, worked example, charts, tables, names */
.strip{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.86rem;color:var(--muted);border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:8px 0}
.strip b{color:var(--fg);font-family:var(--f-mono);font-variant-numeric:tabular-nums;font-weight:700}
.lines{display:grid;grid-template-columns:1fr;gap:10px}
@media (min-width:600px){.lines{grid-template-columns:1fr 1fr}}
.card ul{margin:0;padding-left:18px;color:var(--muted);font-size:.9rem;display:flex;flex-direction:column;gap:2px}
.card ul b{color:var(--fg)}
.new{background:var(--accent-soft);color:var(--accent)}
.steps{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px;counter-reset:s}
.steps>li{counter-increment:s;display:grid;grid-template-columns:28px 1fr;gap:10px;min-width:0}
.steps>li::before{content:counter(s);font-family:var(--f-mono);font-weight:700;font-size:.8rem;color:var(--accent);
  border:1.5px solid var(--accent);border-radius:50%;width:26px;height:26px;display:grid;place-items:center;background:var(--surface)}
.steps .b{min-width:0;display:flex;flex-direction:column;gap:6px}
.steps .b>p{color:var(--muted)}
.steps .b>p b{color:var(--fg)}
.q{font-style:italic;color:var(--owner);font-weight:600}
.chart{margin:0;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 10px 10px}
.chart h3{font-size:.95rem;padding:0 4px 6px}
.chart svg{display:block;width:100%;max-width:520px;height:auto;margin:0 auto;color:var(--fg)}
.chart .grid{stroke:var(--line);stroke-width:1}
.chart .grid.zero{stroke:var(--muted);stroke-width:1.2}
.chart .ax{font-family:var(--f-mono);font-size:9.5px;fill:var(--muted)}
.chart .val{font-family:var(--f-mono);font-size:10.5px;font-weight:700;fill:currentColor}
.chart .note{font-family:var(--f-body);font-size:10.5px;font-weight:700;fill:var(--accent)}
.chart .tick{stroke:var(--accent);stroke-width:1.2;stroke-dasharray:2 2}
.chart .bar{fill:var(--accent);fill-opacity:.5}
.chart .bar.key{fill-opacity:1}
.chart .bar:hover{fill-opacity:.85}
.chart .grp{font-family:var(--f-body);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;fill:var(--muted)}
.chart .rl{font-family:var(--f-body);font-size:11.5px;fill:currentColor}
.chart .tagold{fill:var(--muted);font-family:var(--f-body);font-weight:600}
.chart .tagnow{fill:var(--accent);font-family:var(--f-body);font-weight:700}
.tblwrap{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;font-size:.86rem;font-variant-numeric:tabular-nums}
th,td{padding:8px 8px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th:last-child,td:last-child{white-space:normal;min-width:84px}
thead th{font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:700}
tbody tr:last-child td{border-bottom:0}
td.m{font-family:var(--f-mono)}
.names{display:flex;flex-direction:column;gap:10px}
.names h3{font-size:.95rem;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.names h3 span{font-family:var(--f-body);font-size:.8rem;font-weight:400;color:var(--muted)}
.chip.hold{color:var(--warn);border-color:var(--warn)}
.chip.livechip{color:var(--good);border-color:var(--good)}
.who ul li{font-weight:600}
.who p{font-size:.84rem;margin-top:8px}
@media (max-width:480px){.who{grid-template-columns:1fr}}
"""

LEARN_SVG = """
    <svg viewBox="0 0 360 704" role="img" aria-label="Learning flow. Data in goes to the evidence ledger, which splits into two tracks: execution lessons applied the next day, and trading or risk changes that need 8 or more observations at 2 to 1 before the agent decides them and tells the owner the same day. Both feed calibration, then verify, and verified results loop back as new data. Outside the loop, the hard limits change on the owner's words only.">
      <defs>
        <marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="ah"/></marker>
        <marker id="ahf" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="ahf"/></marker>
      </defs>
      <rect class="bx" x="44" y="8" width="300" height="72" rx="8"/>
      <text class="num" x="58" y="30">1</text><text class="tt" x="74" y="30">Data in</text>
      <text class="ts" x="58" y="50">Live trades, paper flies, replayed sessions,</text>
      <text class="ts" x="58" y="66">projection misses, your own hand orders</text>
      <line class="ar" x1="194" y1="80" x2="194" y2="110" marker-end="url(#ah)"/>
      <text class="al" x="202" y="99">every observation</text>
      <rect class="bx" x="44" y="112" width="300" height="58" rx="8"/>
      <text class="num" x="58" y="134">2</text><text class="tt" x="74" y="134">Evidence ledger</text>
      <text class="ts" x="58" y="154">Logged <tspan class="tsb">for or against</tspan> one specific claim</text>
      <path class="ar" d="M194 170 V184 H113 V204" marker-end="url(#ah)"/>
      <path class="ar" d="M194 170 V184 H275 V204" marker-end="url(#ah)"/>
      <text class="num" x="58" y="198">3</text><text class="tsb" x="70" y="198" style="font-size:12px">Two tracks</text>
      <rect class="bx-a" x="44" y="206" width="138" height="178" rx="8"/>
      <text class="tt" x="54" y="226" style="font-size:12.5px">A. How the agent</text>
      <text class="tt" x="54" y="242" style="font-size:12.5px">executes</text>
      <text class="tsb" x="54" y="266">Applied next day</text>
      <text class="ts" x="54" y="282">No waiting</text>
      <line x1="54" y1="296" x2="172" y2="296" stroke="var(--line)" stroke-width="1"/>
      <text class="tsb" x="54" y="316">Max 10 active</text>
      <text class="tsb" x="54" y="332">lessons</text>
      <text class="ts" x="54" y="352">Weakest one</text>
      <text class="ts" x="54" y="368">is retired</text>
      <rect class="bx-a" x="206" y="206" width="138" height="178" rx="8"/>
      <text class="tt" x="216" y="226" style="font-size:12px">B. What is traded</text>
      <text class="tt" x="216" y="242" style="font-size:12px">and risk at stake</text>
      <text class="ts" x="216" y="266">Hypothesis until</text>
      <text class="tsb" x="216" y="282">8+ obs at 2 to 1</text>
      <line class="ar" x1="275" y1="290" x2="275" y2="304" marker-end="url(#ah)"/>
      <rect x="216" y="306" width="118" height="24" rx="12" fill="var(--surface)" stroke="var(--accent)" stroke-width="1.5"/>
      <text class="fbt" x="275" y="322" text-anchor="middle">Agent decides</text>
      <text class="ts" x="216" y="352">You hear it that day,</text>
      <text class="tsb" x="216" y="368">a few words undo it</text>
      <path class="ar" d="M113 384 V398 H194 V414" marker-end="url(#ah)"/>
      <path class="ar" d="M275 384 V398 H194"/>
      <rect class="bx" x="44" y="416" width="300" height="104" rx="8"/>
      <text class="num" x="58" y="438">4</text><text class="tt" x="74" y="438">Calibration</text>
      <text class="ts" x="58" y="458">Thresholds move only with</text>
      <text class="tsb" x="58" y="474">8 closed live trades or 50 replayed events</text>
      <text class="ts" x="58" y="494">Projection constants refit from</text>
      <text class="ts" x="58" y="510">each morning's scoring</text>
      <line class="ar" x1="194" y1="520" x2="194" y2="546" marker-end="url(#ah)"/>
      <rect class="bx" x="44" y="548" width="300" height="70" rx="8"/>
      <text class="num" x="58" y="570">5</text><text class="tt" x="74" y="570">Verify</text>
      <text class="ts" x="58" y="590">Every change has a <tspan class="tsb">measure</tspan></text>
      <text class="ts" x="58" y="606">Does not work? <tspan class="tsb">Rolled back</tspan></text>
      <path class="fb" d="M44 583 H20 V44 H42" marker-end="url(#ahf)"/>
      <text class="fbt" x="14" y="320" transform="rotate(-90 14 320)" text-anchor="middle">results feed the next cycle</text>
      <rect class="bx-o" x="44" y="636" width="300" height="60" rx="8"/>
      <text class="og" x="58" y="656" style="font-size:12px">Outside the loop: the hard limits</text>
      <text class="ts" x="58" y="673">The account, never TSLA, defined risk, limit orders,</text>
      <text class="ts" x="58" y="688">the total cap, money in or out</text>
    </svg>"""

def bar(f, a, scale=28):
    return (f'<div class="bar" aria-label="{f} for, {a} against, needs 8"><span class="fo" style="width:{f / scale * 100:.2f}%"></span>'
            f'<span class="ag" style="width:{a / scale * 100:.2f}%"></span><span class="goal" style="left:{8 / scale * 100:.2f}%"></span></div>')

def row(claim, f, a, verdict, cls="v-test"):
    return (f'<div class="row"><div class="claim">{claim}</div>{bar(f, a)}'
            f'<div class="meta"><span class="cnt"><span class="f">{f} for</span> / <span class="x">{a} against</span></span>'
            f'<span class="verdict {cls}">{verdict}</span></div></div>')

BODY = f"""
<div class="wrap">
<header>
  <h1>Trading Loop Map</h1>
  <p class="sub">How the system trades, checks itself and learns. As of <b>Mon Nov 16, 2026</b>, evening.</p>
</header>

<div class="strip" aria-label="Where things stand">
  <span>Account <b>$1,995</b></span>
  <span>Closed trades <b>5</b>, <b>3</b> wins</span>
  <span>Realized <b>-$15</b></span>
  <span>Open <b>3</b> flies into Tuesday's reports</span>
  <span>Same-day pilot <b>starts Tue</b></span>
</div>

<nav aria-label="Sections">
  <a href="#day">Day</a><a href="#lines">Two lines</a><a href="#loops">11 loops</a><a href="#learn">How it learns</a><a href="#heal">Healing loop, one case</a><a href="#caps">Cap test</a><a href="#names">Names</a><a href="#tested">Being tested</a><a href="#who">Who decides</a><a href="#rules">Rules</a>
</nav>

<section id="day">
  <h2><span class="n">01</span>A trading day</h2>
  <p class="hint">Pacific time. Filled dots are the trade moments.</p>
  <ol class="tl">
    <li><span class="t">5:52 AM</span><div class="d"><b>Pre-open wake.</b> <span>Takes the day's trading lock, starts the exit timer, writes the exit tickets.</span></div></li>
    <li class="key"><span class="t">6:36 AM</span><div class="d"><b>Exits.</b> <span>Looks for orders you placed yourself, then closes yesterday's earnings flies, shorts first.</span></div></li>
    <li><span class="t">6:50 AM</span><div class="d"><b>Spread scan.</b> <span>Quotes every liquid name with same-day options. Tue, Wed and Fri this week, then Fridays.</span></div></li>
    <li><span class="t">7:15 AM</span><div class="d"><b>Account watch and paper desk start.</b> <span>A watcher checks for your own orders every 5 minutes until 12:57. Ten names trade on paper.</span></div></li>
    <li><span class="t">7:25 AM</span><div class="d"><b>Watchdogs.</b> <span>The standby session and a phone alert. Silent unless the morning exits were not confirmed.</span></div></li>
    <li class="key"><span class="t">7:27 AM</span><div class="d"><b>Same-day pilot entry.</b> <span>One fly, one contract, only if all 17 gates pass and the morning exits are done.</span></div></li>
    <li><span class="t">7:15 AM to<br>12:15 PM</span><div class="d"><b>Hourly check-ins.</b> <span>Mark every position. Take profit, cut, close leftovers.</span></div></li>
    <li><span class="t">9:45 AM</span><div class="d"><b>Midday scan.</b> <span>A name that already passes can be entered here.</span></div></li>
    <li class="key"><span class="t">10:57 AM</span><div class="d"><b>Pilot exit.</b> <span>Flat by 11:00, like everything that expires that day.</span></div></li>
    <li class="key"><span class="t">11:46 AM</span><div class="d"><b>Entry sweep.</b> <span>Every earnings name that passes, best edge first, sized by risk.</span></div></li>
    <li><span class="t">12:05 PM<br>12:17 PM</span><div class="d"><b>Standby switch and entry backup.</b> <span>Rerun the entry if the main session missed it.</span></div></li>
    <li><span class="t">12:50 PM</span><div class="d"><b>Order cutoff.</b> <span>At 12:57 one last look for hand orders.</span></div></li>
    <li><span class="t">2:12 PM</span><div class="d"><b>Reflection.</b> <span>Score what was skipped, grade decisions, log evidence, health check, decide proposals.</span></div></li>
    <li class="sepli"><span class="sep">Off the daily clock</span></li>
    <li class="off"><span class="t">Evening</span><div class="d"><b>P/L projection</b> <span>with ranges for the next morning's reports. Scored against the real exit.</span></div></li>
    <li class="off"><span class="t">Friday</span><div class="d"><b>Weekly scorecard</b> <span>and one retry of a multi-leg order.</span></div></li>
    <li class="off"><span class="t">Saturday</span><div class="d"><b>Replay batches.</b> <span>Next: Nov 21, the out-of-sample test for the pilot's two filters.</span></div></li>
  </ol>
</section>

<section id="lines">
  <h2><span class="n">02</span>Two lines</h2>
  <div class="lines">
    <div class="card"><div class="top"><h3>Earnings IV crush</h3><span class="pill live">Live since Nov 10</span></div>
      <ul><li>Sell an iron fly the day before the report, buy it back the next morning.</li>
      <li>Gate: <b>edge ratio 0.85 or under</b>. Half size up to 1.10.</li>
      <li>About <b>20% of the account</b> per name. Total risk never above the account.</li></ul></div>
    <div class="card"><div class="top"><h3>Same-day theta</h3><span class="pill new">Pilot from Nov 17</span></div>
      <ul><li>One iron fly in options that expire today. In at 7:30, out by 11:00.</li>
      <li><b>Probes:</b> 1 contract, max loss <b>$150</b> or less. Only IWM is on the live list tonight.</li>
      <li>Pauses at <b>-$500</b> or 6 losses in a row. Ends after 20 trades or Dec 18.</li></ul></div>
  </div>
</section>

<section id="loops">
  <h2><span class="n">03</span>The eleven loops</h2>
  <div class="loops">
    <div class="card"><div class="top"><h3><span class="k">1</span>Trade</h3><span class="pill live">Live</span></div>
      <p>Exits, scans, enters every name that passes the gate in code.</p></div>
    <div class="card"><div class="top"><h3><span class="k">2</span>Monitor</h3><span class="pill live">Live</span></div>
      <p>One read-only agent watches all positions between the hourly check-ins.</p></div>
    <div class="card"><div class="top"><h3><span class="k">3</span>Account watch</h3><span class="pill new">New, live Tue</span></div>
      <p>Finds orders <b>you place by hand</b> within 5 minutes, then redoes risk and alerts.</p></div>
    <div class="card"><div class="top"><h3><span class="k">4</span>Projection</h3><span class="pill live">Live</span></div>
      <p>P/L ranges before each report, scored the next morning. <b>Constants refit by written rules.</b></p>
      <span class="note">First scoring Tue.</span></div>
    <div class="card"><div class="top"><h3><span class="k">5</span>Reflection</h3><span class="pill live">Live</span></div>
      <p>Scores skipped names, grades decisions on process, logs evidence, checks health.</p></div>
    <div class="card"><div class="top"><h3><span class="k">6</span>Proposals</h3><span class="pill live">Live</span></div>
      <p>49 numbered fixes so far, <b>each with a measure</b>. The agent decides and reports.</p></div>
    <div class="card"><div class="top"><h3><span class="k">7</span>Replay</h3><span class="pill batch">2 datasets</span></div>
      <p><b>103 earnings events</b> and <b>90 same-day flies</b>, priced from real option history.</p></div>
    <div class="card"><div class="top"><h3><span class="k">8</span>Paper desk</h3><span class="pill live">Live</span></div>
      <p>Ten names traded on paper every day, plus the morning spread scan across the market.</p></div>
    <div class="card"><div class="top"><h3><span class="k">9</span>Weekly</h3><span class="pill live">Live</span></div>
      <p>Scorecard, calibration, hypothesis tallies.</p></div>
    <div class="card"><div class="top"><h3><span class="k">10</span>Safety</h3><span class="pill live">Live</span></div>
      <p>Self-check before every commit, <b>two breakers</b>, breakeven alerts at the broker, two watchdogs.</p></div>
    <div class="card" style="grid-column:1/-1"><div class="top"><h3><span class="k">11</span>Failover</h3><span class="pill batch">Armed</span></div>
      <p>A <b>standby session</b> takes the lock and runs the same playbook when the main session misses a check-in. The dry run passed. No real takeover yet.</p></div>
  </div>
</section>

<section id="learn">
  <h2><span class="n">04</span>How it learns</h2>
  <figure>{LEARN_SVG}
    <div class="legend"><span><span class="sw a"></span>The agent decides</span><span><span class="sw o"></span>Your words only</span></div>
    <figcaption>Every observation lands in the ledger first. Execution lessons move fast. Anything about <b>what is traded or how much is at risk</b> waits for evidence, then the agent decides and tells you the same day.</figcaption>
  </figure>
</section>

<section id="heal">
  <h2><span class="n">05</span>The healing loop on one real case</h2>
  <p class="hint">The same-day pilot, from your ask to tonight. Each step changed the next one.</p>
  <ol class="steps">
    <li><div class="b"><p><span class="q">"lets do some day trading for the iv crush/theta decay."</span> Nov 11. <b>Paper first:</b> same-day iron flies on SPY and IWM, then ten names.</p></div></li>
    <li><div class="b"><p><b>Paper, 4 sessions, 26 flies:</b> +$450 at mid prices, <b>-$92 at worst-case fills</b>. The gap is wide spreads on single stocks.</p></div></li>
    <li><div class="b"><p><span class="q">"Push the day trading pilot."</span> Nov 16. <b>Replayed the same evening:</b> 90 real flies on SPY, QQQ and IWM, every session from Oct 6 to Nov 16, sold at 7:30 AM.</p>
      <figure class="chart"><h3>Average result per fly after costs, by exit time</h3>
      {chart_a()}
      <figcaption>77 clean flies. <b>No exit time makes money.</b> The first 90 minutes lose the most. Hover a bar for the win rate.</figcaption></figure>
      <p>Stops made it worse. A take profit changed nothing. The 1.15x premium trigger from the first proposal sat in the worst bucket.</p></div></li>
    <li><div class="b"><p><b>Decision:</b> live, as small probes. One contract, IWM (the only name at breakeven after costs). It buys real fills and the first same-day round trip at the broker. The bigger tier stays off until a filter passes a test written before the data.</p></div></li>
    <li><div class="b"><p><span class="q">"$150 is an extremely small cap. Can you test it with different cap levels?"</span> <b>Tested the same evening.</b> You were right about the budget: it would have stopped the pilot by bad luck. Results in the next section. <b>Fixed:</b> -$500 and 6 in a row.</p></div></li>
    <li><div class="b"><p><b>Next:</b> spread scan Tue, Wed, Fri. Review after 10 probes. Sat Nov 21: replay 30 more sessions to test two filters (overnight gap under 1%, quiet first hour) on data they were not found in.</p></div></li>
  </ol>
</section>

<section id="caps">
  <h2><span class="n">06</span>Cap levels tested</h2>
  <figure class="chart"><h3>How often a stop rule ends a no-edge pilot by luck</h3>
    {chart_c()}
    <figcaption>20 one-contract IWM probes, resampled 20,000 times from the replay. The old rules would have ended the pilot before it produced its data. With SPY-size flies in the mix, -$500 stops about 1 run in 20.</figcaption></figure>
  <p class="hint">A bigger cap per trade is a different story. Average result a day when each trade is sized up to the cap:</p>
  <div class="tblwrap"><table>
    <thead><tr><th>Cap per trade</th><th>IWM</th><th>SPY</th><th>QQQ</th><th>Buying power</th></tr></thead>
    <tbody>
      <tr><td>$80</td><td class="m">-$5</td><td class="m">-$42</td><td class="m">too big</td><td class="m">about $300</td></tr>
      <tr><td>$150</td><td class="m">-$11</td><td class="m">-$31</td><td class="m">-$36</td><td class="m">$370 to $700</td></tr>
      <tr><td>$200</td><td class="m">-$14</td><td class="m">-$49</td><td class="m">-$36</td><td class="m">$390 to $860</td></tr>
      <tr><td>$400</td><td class="m">-$28</td><td class="m">-$105</td><td class="m">-$62</td><td class="m">$620 to $1,280</td></tr>
      <tr><td>$600</td><td class="m">-$44</td><td class="m">-$147</td><td class="m">-$98</td><td class="m">$800 to $1,560</td></tr>
    </tbody></table></div>
  <div class="thin"><b>What the table says</b>
    <ul><li>Size scales the result and the swing together. It does not find an edge.</li>
    <li>Buying power is not the constraint: a $400 cap fits when the account is flat.</li>
    <li>The straddle with no wings (the limit of wider wings) did worse than the fly: -$39 a trade against -$13.</li></ul></div>
</section>

<section id="names">
  <h2><span class="n">07</span>Names with same-day options</h2>
  <p class="hint">Scanned tonight: 72 names with heavy options volume. Spreads get measured live at 6:50 AM on scan days.</p>
  <div class="names">
    <div><h3>Every day <span>9 names</span></h3>
      <div class="chips"><span class="chip livechip">IWM, live</span><span class="chip">SPY</span><span class="chip">QQQ</span><span class="chip">IBIT</span><span class="chip">GLD</span><span class="chip">XSP</span><span class="chip">SPX</span><span class="chip">NDX</span><span class="chip">RUT</span></div></div>
    <div><h3>Mon, Wed, Fri <span>20 more</span></h3>
      <div class="chips"><span class="chip hold">NVDA, on hold</span><span class="chip">TLT</span><span class="chip">MU</span><span class="chip">XLF</span><span class="chip">AAPL</span><span class="chip">AMD</span><span class="chip">SLV</span><span class="chip">AMZN</span><span class="chip">GOOGL</span><span class="chip">LQD</span><span class="chip">META</span><span class="chip">SMH</span><span class="chip">MSFT</span><span class="chip">TQQQ</span><span class="chip">AVGO</span><span class="chip">XLE</span><span class="chip">GDX</span><span class="chip">IEF</span><span class="chip">SPCX</span><span class="chip">DRAM</span><span class="chip off">TSLA, never</span></div></div>
    <div><h3>Fridays only <span>40 more</span></h3>
      <div class="chips"><span class="chip">EWZ</span><span class="chip">HYG</span><span class="chip">INTC</span><span class="chip">NFLX</span><span class="chip">MSTR</span><span class="chip">SOXL</span><span class="chip">EEM</span><span class="chip">ORCL</span><span class="chip">PLTR</span><span class="chip">HOOD</span><span class="chip">COIN</span><span class="chip">and 29 others</span></div></div>
    <div class="thin"><b>How a name gets onto the live list</b>
      <ul><li>Median spread of 3% of the straddle or less over five scan mornings.</li>
      <li>Its own replay, 20 sessions or more, no worse than IWM per dollar at risk.</li>
      <li>One contract fits the $150 cap. Then the day's pick is the cheapest name to cross.</li></ul></div>
  </div>
</section>

<section id="tested">
  <h2><span class="n">08</span>Being tested now</h2>
  <p class="hint">Green = for, red = against. Bars share one scale. The dashed line is 8 observations.</p>
  <div class="score">
    {row("Names at edge ratio 0.70 or under win two times in three", 11, 6, "Testing")}
    {row("The intraday-move gate does not help", 11, 7, "Under review", "v-keep")}
    {row("Wide-spread names are worth a one-contract test", 4, 1, "Testing")}
    {row("The crush pays most when the expiry is the exit day", 2, 0, "Testing")}
    {row("The macro veto blocks days that are no worse", 2, 2, "Testing")}
    {row("Losing days come in clusters", 1, 2, "Testing")}
    {row("Long straddles lose", 15, 12, "Adopted Nov 11: off", "v-adopt")}
    <div class="thin"><b>New tonight, no observations yet</b>
      <ul><li>A same-day index fly has no edge without a filter.</li><li>A same-day fly does better after an overnight gap under 1%.</li></ul>
    </div>
  </div>
</section>

<section id="who">
  <h2><span class="n">09</span>Who decides what</h2>
  <div class="who">
    <div class="ag"><h3>The agent</h3><ul><li>Execution</li><li>Process</li><li>Data</li><li>Tooling</li><li>Rules</li><li>Risk</li><li>Cost</li></ul>
      <p>You hear every rule, risk and cost decision the same day. A few words undo it.</p></div>
    <div class="ow"><h3>You, only</h3><ul><li>The account</li><li>Never TSLA</li><li>Defined risk only</li><li>Limit orders only</li><li>The total risk cap</li><li>Money in or out</li></ul>
      <p>The ledger code refuses an agent approval of any of these.</p></div>
  </div>
  <p class="hint"><span class="q">"Dont need a decision on me. Remember, self healing and strengthening the model with your own decision making"</span> Nov 16.</p>
</section>

<section>
  <h2><span class="n">10</span>What self-learning means here</h2>
  <div class="callout">
    <p class="big">An evidence ledger, tests written before the data, and rules that change only on enough observations.</p>
    <p><b>It is not a model that retrains itself.</b> With <b>5 closed live trades</b> so far, anything automatic would fit noise. Tonight's replay is the pattern: 90 real flies checked a plan before the first live dollar.</p>
  </div>
</section>

<footer id="rules">
  <h2>Rules in force</h2>
  <div class="chips">
    <span class="chip">Defined risk only</span>
    <span class="chip">Limit orders only</span>
    <span class="chip off">Never TSLA</span>
    <span class="chip">Total risk no larger than the account</span>
    <span class="chip">No daily limit on number of trades</span>
    <span class="chip">Earnings name: $350 max loss</span>
    <span class="chip">Other name: $400 max loss</span>
    <span class="chip">Sell line at edge ratio 0.85</span>
    <span class="chip">Half size from 0.85 to 1.10</span>
    <span class="chip">One soft condition: half size</span>
    <span class="chip">Wings 1.5x the straddle, never under 0.9x</span>
    <span class="chip">Exit must work by single legs</span>
    <span class="chip test">Same-day pilot: 1 contract, $150, flat by 11:00</span>
    <span class="chip off">Long straddles off</span>
  </div>
</footer>
</div>
"""

head = """<title>Trading Loop Map</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@500;700&family=Space+Grotesk:wght@500;700&display=swap">
"""
html = head + "<style>" + base_css.rstrip() + "\n" + EXTRA_CSS + "</style>\n" + BODY
assert "—" not in html and "–" not in html, "no em or en dashes"
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "index.html").write_text(html)
print("written", len(html), "bytes")
