/* Vantage Trading Hub. The words live in index.html; this file works out and draws what the data decides. */
const PT = 'America/Los_Angeles';
const COST_TARGET = 5, COST_BREAKEVEN = 9;   // the plan's cost target and the replay's breakeven, % of the credit
const CAP_OLD = 350, CAP_NOW = 600;          // the earnings name cap before and since 2026-11-17

/* ---------- small helpers ---------- */
const fnum = (v, d) => d3.format(',.' + d + 'f')(Math.abs(v));
const FMT = {
  text: (v) => String(v),
  money: (v) => (v < 0 ? '\u2212$' : '$') + fnum(v, 2),
  money1: (v) => (v < 0 ? '\u2212$' : '$') + fnum(v, 1),
  signed: (v) => (v < 0 ? '\u2212$' : '+$') + fnum(v, 2),
  signed1: (v) => (v < 0 ? '\u2212$' : '+$') + fnum(v, 1),
  signed0: (v) => (v < 0 ? '\u2212$' : '+$') + fnum(v, 0),
  pct0: (v) => d3.format('.0f')(v) + '%',
  pct1: (v) => d3.format('.1f')(v) + '%',
  px: (v) => d3.format(Math.abs(v * 100 - Math.round(v * 100)) > 1e-6 ? ',.3f' : ',.2f')(v),
  day: (v) => d3.utcFormat('%b %-d')(new Date(String(v).slice(0, 10) + 'T00:00:00Z')),
};
const ptDay = (d) => new Intl.DateTimeFormat('en-CA', {timeZone: PT, year: 'numeric', month: '2-digit', day: '2-digit'}).format(d);
const ptClock = (d, sec) => new Intl.DateTimeFormat('en-US', Object.assign({timeZone: PT, hour: 'numeric', minute: '2-digit'}, sec ? {second: '2-digit'} : {})).format(d);
const ptParts = (d) => {
  const p = {};
  for (const x of new Intl.DateTimeFormat('en-US', {timeZone: PT, weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false}).formatToParts(d)) p[x.type] = x.value;
  return {wd: p.weekday, mins: (Number(p.hour) % 24) * 60 + Number(p.minute)};
};
const isWeekend = (wd) => wd === 'Sat' || wd === 'Sun';
const marketOpen = () => { const p = ptParts(new Date()); return !isWeekend(p.wd) && p.mins >= 390 && p.mins < 780; };
const tradingDay = () => {            // the latest session that has started, as a Pacific date
  let d = new Date();
  for (let i = 0; i < 8; i++) {
    const p = ptParts(d);
    if (!isWeekend(p.wd) && (i > 0 || p.mins >= 390)) return ptDay(d);
    d = new Date(d.getTime() - 864e5);
  }
  return ptDay(new Date());
};
const ptWall = (day, mins) => {       // the instant of a Pacific wall-clock time on that date
  for (const h of [8, 7]) {
    const t = new Date(Date.parse(day + 'T00:00:00Z') + (h * 60 + mins) * 60000);
    if (ptParts(t).mins === mins) return t;
  }
  return new Date(Date.parse(day + 'T00:00:00Z') + (480 + mins) * 60000);
};
const hourFrom = () => {              // one hour back from now, or from the close when the market is shut
  const end = Math.min(Date.now(), ptWall(tradingDay(), 780).getTime());
  return new Date(Math.floor((end - 3600e3) / 300e3) * 300e3).toISOString().slice(0, 19) + 'Z';
};
const h = (tag, attrs, ...kids) => {
  const e = document.createElement(tag);
  for (const k of Object.keys(attrs || {})) {
    const v = attrs[k];
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else if (k === 'style') e.style.cssText = v; else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) { if (k != null) e.append(k.nodeType ? k : document.createTextNode(String(k))); }
  return e;
};
const rowsOf = (id) => { const s = dash.data(id); const ok = s.status === 'ok' && Array.isArray(s.data); return {status: s.status, ok, rows: ok ? s.data : []}; };
const tone = (v) => (v == null ? '' : v > 0 ? ' vh-up' : v < 0 ? ' vh-down' : '');
const waitText = (st) => (st === 'loading' ? 'Loading…' : st === 'error' ? 'Failed to load' : '—');

/* ---------- the day and bar size the two history calls use ---------- */
dash.setParams({from: tradingDay(), bar: '5minute'});

/* ---------- how the broker's answers become rows ---------- */
dash.loader('quotes', {
  description: 'One row per option contract: bid, ask and the mid between them.',
  fn: ({answer}) => {
    const a = typeof answer === 'string' ? JSON.parse(answer) : answer;
    const list = (a && a.data && a.data.results) || [];
    return list.filter((r) => r && r.quote).map((r) => {
      const q = r.quote, bid = Number(q.bid_price), ask = Number(q.ask_price), mark = Number(q.mark_price);
      return {instrument_id: q.instrument_id, bid, ask, mid: bid > 0 && ask > 0 ? Math.round((bid + ask) * 5000) / 10000 : mark, mark,
        iv: q.implied_volatility == null ? null : Number(q.implied_volatility), delta: q.delta == null ? null : Number(q.delta), updated_at: q.updated_at};
    });
  },
});
dash.loader('spots', {
  description: 'One row per stock: last trade, the prior close and the change on the day.',
  fn: ({answer}) => {
    const a = typeof answer === 'string' ? JSON.parse(answer) : answer;
    const list = (a && a.data && a.data.results) || [];
    return list.filter((r) => r && r.quote).map((r) => {
      const q = r.quote, last = Number(q.last_trade_price), prev = Number(q.adjusted_previous_close);
      return {symbol: q.symbol, last, prev_close: prev, change_pct: prev ? Math.round((last / prev - 1) * 10000) / 100 : null,
        bid: Number(q.bid_price), ask: Number(q.ask_price), at: q.venue_last_trade_time};
    });
  },
});
dash.loader('bars_a', {
  description: 'One row per contract and bar: when the bar began and its last trade price.',
  fn: ({answer}) => {
    const a = typeof answer === 'string' ? JSON.parse(answer) : answer;
    const out = [];
    for (const r of ((a && a.data && a.data.results) || [])) {
      for (const b of (r.bars || [])) { if (!b.interpolated) out.push({instrument_id: r.instrument_id, t: b.begins_at, close: Number(b.close_price), interval: r.interval}); }
    }
    return out;
  },
});
dash.loader('bars_b', {
  description: 'One row per contract and bar: when the bar began and its last trade price.',
  fn: ({answer}) => {
    const a = typeof answer === 'string' ? JSON.parse(answer) : answer;
    const out = [];
    for (const r of ((a && a.data && a.data.results) || [])) {
      for (const b of (r.bars || [])) { if (!b.interpolated) out.push({instrument_id: r.instrument_id, t: b.begins_at, close: Number(b.close_price), interval: r.interval}); }
    }
    return out;
  },
});

/* The two ledger files load as they are: each is one record of tables (no rows, data or results key at the top). */

/* ---------- tables out of the two ledger files ---------- */
dash.calc('positions', {inputs: ['book'], title: 'Open positions', description: 'The flies open right now, from our ledger.',
  fn: (book) => { const b = (Array.isArray(book) ? book[0] : book) || {}; return b.positions || []; }});
dash.calc('trades', {inputs: ['book'], title: 'Every realized result', description: 'Closed trades, partial closes and adjustments. Result is after fees. Percent columns are in percent.',
  fn: (book) => (((Array.isArray(book) ? book[0] : book) || {}).trades || []).map((t) => ({id: t.id, date: t.date, time_pt: t.time_pt, symbol: t.symbol, strikes: t.strikes, line: t.line,
    who: t.lane_label, lane: t.lane, type: t.row_type, qty: t.qty, credit: t.credit == null ? null : Math.round(t.credit * 100) / 100, close: t.close == null ? null : Math.round(t.close * 100) / 100, pnl: t.pnl, max_loss: t.max_loss,
    pct_of_max_loss: t.pct_max_loss == null || t.row_type === 'Adjustment' ? null : Math.round(t.pct_max_loss * 1000) / 10,
    cost_pct: t.cost_share == null ? null : Math.round(t.cost_share * 1000) / 10, hold_hours: t.hold_hours, exit_ts: t.exit_ts}))});
dash.calc('stats', {inputs: ['book'], title: 'The headline numbers', description: 'Sums and averages over the realized results, and the account snapshot. Today and this month follow the Pacific clock.',
  fn: (book) => {
    const rows = ((Array.isArray(book) ? book[0] : book) || {}).trades || [], acct = (((Array.isArray(book) ? book[0] : book) || {}).account || [])[0];
    if (!acct) return [];
    const r2 = (v) => Math.round(v * 100) / 100, sum = (a) => r2(a.reduce((s, t) => s + t.pnl, 0));
    const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
    const closed = rows.filter((t) => t.row_type === 'Closed'), wins = closed.filter((t) => t.pnl >= 0), losses = closed.filter((t) => t.pnl < 0);
    const worst = closed.reduce((w, t) => (!w || t.pnl < w.pnl ? t : w), null);
    const costs = closed.filter((t) => t.cost_share != null).map((t) => t.cost_share);
    return [{realized_total: sum(rows), realized_today: sum(rows.filter((t) => t.date === today)), realized_month: sum(rows.filter((t) => t.date.slice(0, 7) === today.slice(0, 7))),
      closed: closed.length, wins: wins.length, losses: losses.length, win_rate_pct: closed.length ? Math.round(100 * wins.length / closed.length) : null,
      avg_win: wins.length ? r2(sum(wins) / wins.length) : null, avg_loss: losses.length ? r2(sum(losses) / losses.length) : null,
      per_trade: closed.length ? r2(sum(closed) / closed.length) : null, worst: worst ? worst.pnl : null, worst_name: worst ? worst.symbol : null,
      other_results: sum(rows.filter((t) => t.row_type !== 'Closed')), avg_cost_pct: costs.length ? Math.round(1000 * costs.reduce((s, c) => s + c, 0) / costs.length) / 10 : null,
      risk_used: acct.risk_used, account_value: acct.account_value, risk_pct: acct.account_value ? Math.round(100 * acct.risk_used / acct.account_value) : null,
      buying_power: acct.buying_power, first_trade: acct.first_trade, ledger_as_of: acct.as_of}];
  }});
dash.calc('by_line', {inputs: ['book'], title: 'Results by line', description: 'Earnings flies, other names and same-day flies, each with its count, wins and total.',
  fn: (book) => ['Earnings', 'Other', 'Same-day'].map((line) => {
    const rows = (((Array.isArray(book) ? book[0] : book) || {}).trades || []).filter((t) => t.line === line);
    return {line, results: rows.length, wins: rows.filter((t) => t.pnl >= 0).length, pnl: Math.round(rows.reduce((s, t) => s + t.pnl, 0) * 100) / 100};
  })});
dash.calc('by_lane', {inputs: ['book'], title: 'Results by who decided', description: 'My own picks, trades Brad called and I placed, and orders Brad placed himself.',
  fn: (book) => [['mine', 'My own picks', ['agent']], ['your_call', 'You called it, I placed it', ['agent_override']], ['yours', 'Your own orders', ['brad_hand', 'brad_lane']]].map(([lane, who, keys]) => {
    const rows = (((Array.isArray(book) ? book[0] : book) || {}).trades || []).filter((t) => keys.includes(t.lane));
    return {lane, who, results: rows.length, wins: rows.filter((t) => t.pnl >= 0).length, pnl: Math.round(rows.reduce((s, t) => s + t.pnl, 0) * 100) / 100};
  })});
dash.calc('daily', {inputs: ['book'], title: 'Closed results by day', description: 'One row per Pacific date with a closed result, and the running total.',
  fn: (book) => {
    const by = new Map();
    for (const t of (((Array.isArray(book) ? book[0] : book) || {}).trades || [])) { const d = by.get(t.date) || {date: t.date, pnl: 0, results: 0}; d.pnl += t.pnl; d.results += 1; by.set(t.date, d); }
    let run = 0;
    return [...by.values()].sort((a, b) => (a.date < b.date ? -1 : 1)).map((d) => { run += d.pnl; return {date: d.date, pnl: Math.round(d.pnl * 100) / 100, results: d.results, running: Math.round(run * 100) / 100}; });
  }});
dash.calc('running', {inputs: ['book'], title: 'Running total by result', description: 'Each realized result in time order, and the total after it.',
  fn: (book) => {
    let run = 0;
    return (((Array.isArray(book) ? book[0] : book) || {}).trades || []).slice().sort((a, b) => (a.exit_ts < b.exit_ts ? -1 : 1)).map((t, i) => {
      run += t.pnl;
      return {n: i + 1, exit_ts: t.exit_ts, date: t.date, symbol: t.symbol, type: t.row_type, who: t.lane_label, pnl: t.pnl, running: Math.round(run * 100) / 100};
    });
  }});
dash.calc('events', {inputs: ['book'], title: 'Our trades in time order', description: 'Every entry and exit with its time.',
  fn: (book) => {
    const out = [];
    for (const p of (((Array.isArray(book) ? book[0] : book) || {}).positions || [])) out.push({t: p.opened, what: p.symbol + ' opened', symbol: p.symbol, kind: 'in', pnl: null});
    for (const t of (((Array.isArray(book) ? book[0] : book) || {}).trades || [])) {
      if (t.entry_ts) out.push({t: t.entry_ts, what: t.symbol + ' opened', symbol: t.symbol, kind: 'in', pnl: null});
      out.push({t: t.exit_ts, what: t.symbol + (t.row_type === 'Closed' ? ' closed' : t.row_type === 'Partial close' ? ' partly closed' : ' adjusted'), symbol: t.symbol, kind: 'out', pnl: t.pnl});
    }
    return out.sort((a, b) => (a.t < b.t ? -1 : 1));
  }});

/* ---------- live numbers: ledger joined to quotes ---------- */
dash.calc('open_pl', {inputs: ['book', 'quotes'], title: 'Open P/L by fly', description: 'Credit taken in, minus the cost to buy the fly back: at the mid of each leg, and at the market (pay the ask, sell at the bid).',
  fn: (book, quotes) => {
    const legs = (((Array.isArray(book) ? book[0] : book) || {}).legs || []).filter((l) => l.open), q = new Map((Array.isArray(quotes) ? quotes : []).map((r) => [r.instrument_id, r]));
    return (((Array.isArray(book) ? book[0] : book) || {}).positions || []).map((p) => {
      const mine = legs.filter((l) => l.trade_id === p.trade_id);
      let mid = 0, cross = 0, ok = mine.length > 0, at = null;
      for (const l of mine) {
        const r = q.get(l.instrument_id);
        if (!r || r.mid == null || isNaN(r.mid)) { ok = false; break; }
        mid += l.side === 'short' ? r.mid : -r.mid;
        cross += l.side === 'short' ? (r.ask > 0 ? r.ask : r.mid) : -(r.bid > 0 ? r.bid : 0);
        if (!at || r.updated_at > at) at = r.updated_at;
      }
      const r2 = (v) => Math.round(v * 100) / 100;
      if (!ok) return {trade_id: p.trade_id, symbol: p.symbol, qty: p.qty, credit: p.credit, close_mid: null, pl_mid: null, close_at_market: null, pl_at_market: null, pct_of_max_profit: null, quoted_at: null};
      const plMid = r2((p.credit - mid) * 100 * p.qty);
      return {trade_id: p.trade_id, symbol: p.symbol, qty: p.qty, credit: p.credit, close_mid: Math.round(mid * 1000) / 1000, pl_mid: plMid,
        close_at_market: r2(cross), pl_at_market: r2((p.credit - cross) * 100 * p.qty), pct_of_max_profit: p.max_profit ? Math.round(100 * plMid / p.max_profit) : null, quoted_at: at};
    });
  }});
dash.calc('live', {inputs: ['open_pl', 'stats'], title: 'Open P/L and the totals with it', description: 'The sum over the open flies, and today, this month and the year with that sum added to the closed results.',
  fn: (open, stats) => {
    const rows = Array.isArray(open) ? open : [], s = (Array.isArray(stats) ? stats : [])[0];
    if (!rows.length || !s || rows.some((r) => r.pl_mid == null)) return [];
    const r2 = (v) => Math.round(v * 100) / 100, o = r2(rows.reduce((a, r) => a + r.pl_mid, 0));
    return [{open_pl: o, open_pl_at_market: r2(rows.reduce((a, r) => a + r.pl_at_market, 0)), flies: rows.length,
      today_with_open: r2(s.realized_today + o), month_with_open: r2(s.realized_month + o), total_with_open: r2(s.realized_total + o),
      quoted_at: rows.map((r) => r.quoted_at).filter(Boolean).sort().pop() || null}];
  }});
dash.calc('spot_view', {inputs: ['book', 'spots'], title: 'Stock price against each fly', description: 'Where the stock is now against the breakevens, and how far it can move before the fly loses at expiry.',
  fn: (book, spots) => {
    const s = new Map((Array.isArray(spots) ? spots : []).map((r) => [r.symbol, r]));
    return (((Array.isArray(book) ? book[0] : book) || {}).positions || []).map((p) => {
      const r = s.get(p.symbol), spot = r ? r.last : null;
      return {trade_id: p.trade_id, symbol: p.symbol, spot, change_pct: r ? r.change_pct : null, be_low: p.be_low, be_high: p.be_high,
        room_down_pct: spot ? Math.round((spot - p.be_low) / spot * 1000) / 10 : null, room_up_pct: spot ? Math.round((p.be_high - spot) / spot * 1000) / 10 : null,
        inside: spot == null ? null : spot > p.be_low && spot < p.be_high};
    });
  }});
dash.calc('market', {inputs: ['spots'], title: 'The market today', description: 'Last price and change on the day for each stock the page follows.',
  fn: (spots) => (Array.isArray(spots) ? spots : []).map((r) => ({symbol: r.symbol, last: r.last, change_pct: r.change_pct, at: r.at}))});
dash.calc('curve', {inputs: ['book', 'bars_a', 'bars_b'], title: 'P/L through the session',
  description: 'For each bar: what the open flies were worth against their credit, plus the results already closed that day. Prices are the last trade in each bar, carried forward when a contract did not trade.',
  fn: (book, barsA, barsB) => {
    const legs = ((Array.isArray(book) ? book[0] : book) || {}).legs || [], trades = ((Array.isArray(book) ? book[0] : book) || {}).trades || [];
    const bars = [...(Array.isArray(barsA) ? barsA : []), ...(Array.isArray(barsB) ? barsB : [])];
    if (!legs.length || !bars.length) return [];
    const step = bars[0].interval === 'minute' ? 60000 : 300000, now = Date.now();
    const end = (b) => Math.min(Date.parse(b.t) + step, now);
    const by = new Map();
    for (const b of bars) { if (!by.has(b.instrument_id)) by.set(b.instrument_id, []); by.get(b.instrument_id).push({t: end(b), c: b.close}); }
    for (const a of by.values()) a.sort((p, q) => p.t - q.t);
    const times = [...new Set(bars.map(end))].sort((p, q) => p - q);
    const day = (ms) => new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(ms));
    const price = (id, T) => { const a = by.get(id); if (!a || !a.length) return null; let v = a[0].c; for (const p of a) { if (p.t <= T) v = p.c; else break; } return v; };
    return times.map((T) => {
      let open = 0, missing = 0;
      for (const l of legs) {
        if (Date.parse(l.from_ts) > T || (l.to_ts && Date.parse(l.to_ts) <= T)) continue;
        const p = price(l.instrument_id, T);
        if (p == null) { missing += 1; continue; }
        open += (l.side === 'short' ? l.fill - p : p - l.fill) * 100 * l.qty;
      }
      const d = day(T), closed = trades.filter((t) => t.date === d && Date.parse(t.exit_ts) <= T).reduce((s, t) => s + t.pnl, 0);
      return {t: new Date(T).toISOString(), open_pl: Math.round(open * 100) / 100, closed: Math.round(closed * 100) / 100, total: Math.round((open + closed) * 100) / 100, legs_without_a_price: missing};
    });
  }});

/* ---------- tables out of the model file ---------- */
dash.calc('rules', {inputs: ['model'], title: 'Rule versions', description: 'Each version of the trading rules, with its date.', fn: (model) => ((Array.isArray(model) ? model[0] : model) || {}).rules || []});
dash.calc('proposals', {inputs: ['model'], title: 'Changes to the model', description: 'Every proposed change: the problem, the change, how it is judged and where it stands.', fn: (model) => ((Array.isArray(model) ? model[0] : model) || {}).proposals || []});
dash.calc('prop_counts', {inputs: ['model'], title: 'Changes by state', description: 'How many changes are running, passed, inconclusive or turned down.',
  fn: (model) => {
    const p = ((Array.isArray(model) ? model[0] : model) || {}).proposals || [];
    if (!p.length) return [];
    return [{measuring: p.filter((x) => x.state === 'In force, being measured').length, worked: p.filter((x) => x.verdict === 'worked').length,
      inconclusive: p.filter((x) => x.verdict === 'inconclusive').length, declined: p.filter((x) => x.verdict === 'declined').length,
      did_not_work: p.filter((x) => x.verdict === 'did_not_work').length, waiting_on_you: p.filter((x) => x.state === 'Waiting on you').length}];
  }});
dash.calc('lessons', {inputs: ['model'], title: 'Lessons', description: 'Lessons in force and ideas on trial, with how many observations support or contradict each.', fn: (model) => ((Array.isArray(model) ? model[0] : model) || {}).lessons || []});
dash.calc('scores', {inputs: ['model'], title: 'Projections against results', description: 'What I projected for each earnings trade and what it made. The call says whether the result fell inside the range I gave.',
  fn: (model) => (((Array.isArray(model) ? model[0] : model) || {}).scores || []).map((s) => {
    const inside = (lo, hi) => s.actual != null && lo != null && s.actual >= lo && s.actual <= hi;
    const usd = (v) => (v < 0 ? '\u2212$' : '+$') + Math.abs(v).toFixed(2);
    const verdict = s.actual == null ? 'Still open' : s.lo50 == null ? 'Off by $' + Math.abs(Math.round((s.actual - s.projected) * 100) / 100).toFixed(2) : inside(s.lo50, s.hi50) ? 'Inside the likely range' : inside(s.lo80, s.hi80) ? 'Inside the wide range' : 'Outside';
    return {trade_id: s.trade_id, symbol: s.symbol, made: s.made, projected: s.projected, range: s.lo50 == null ? 'none given' : usd(s.lo50) + ' to ' + usd(s.hi50), actual: s.actual, verdict, method: s.method};
  })});
dash.calc('evidence', {inputs: ['model'], title: 'The replay: earnings fly by name cap', description: 'Average result per fly after costs on past earnings reports, for each cap on the max loss per name.', fn: (model) => ((Array.isArray(model) ? model[0] : model) || {}).evidence || []});
dash.calc('pilot', {inputs: ['model'], title: 'Same-day pilot', description: 'How many probes are closed and what they made.', fn: (model) => ((Array.isArray(model) ? model[0] : model) || {}).pilot || []});
dash.calc('paper', {inputs: ['model'], title: 'Paper desk', description: 'Paper trades by test. Never mixed into live results.', fn: (model) => ((Array.isArray(model) ? model[0] : model) || {}).paper || []});
dash.calc('upcoming', {inputs: ['model'], title: 'Coming up', description: 'Dated exits, reviews and research days.', fn: (model) => ((Array.isArray(model) ? model[0] : model) || {}).upcoming || []});

/* ---------- what shows: flat or live, and which period ---------- */
let flat = true, charted = false, bookSeen = false, tab = 'day';
const setHidden = (sel, hide) => { for (const e of document.querySelectorAll('#dash-root ' + sel)) e.hidden = hide; };
dash.onData(() => {
  const b = dash.data('book');
  const v = b.status === 'ok' ? (Array.isArray(b.data) ? b.data[0] : b.data) : null;
  if (!v || !v.account) return;
  bookSeen = true;
  flat = !((v.positions || []).length);
  charted = (((v.chart || [])[0] || {}).bars_a || 0) > 0;
  setHidden('.vh-live', flat);
  setHidden('.vh-flat', !flat);
  setHidden('#vh-intraday-wrap', !charted);
  setHidden('#vh-intraday-empty', charted);
  const closed = (v.trades || []).filter((t) => t.row_type === 'Closed').length;
  setHidden('#vh-small-n', closed >= 30);
});
const panes = {hour: 'vh-pane-intraday', day: 'vh-pane-intraday', month: 'vh-pane-month', ytd: 'vh-pane-ytd'};
const showTab = (name) => {
  tab = name;
  for (const b of document.querySelectorAll('#dash-root .vh-tab')) b.setAttribute('aria-selected', String(b.dataset.tab === name));
  for (const id of new Set(Object.values(panes))) setHidden('#' + id, id !== panes[name]);
  setHidden('#vh-cap-hour', name !== 'hour');
  setHidden('#vh-cap-day', name !== 'day');
  if (name === 'hour') dash.setParams({bar: 'minute', from: hourFrom()});
  if (name === 'day') dash.setParams({bar: '5minute', from: tradingDay()});
};
for (const b of document.querySelectorAll('#dash-root .vh-tab')) b.addEventListener('click', () => showTab(b.dataset.tab));
const refreshLive = () => {
  dash.refresh('spots');
  if (!bookSeen) return;
  if (!flat) dash.refresh('quotes');
  const pane = document.getElementById('vh-pane-intraday');
  if (charted && pane && !pane.hidden) {
    if (tab === 'hour') { const f = hourFrom(); if (dash.params().from !== f) { dash.setParams({from: f}); return; } }
    dash.refresh('bars_a');
    dash.refresh('bars_b');
  }
};
for (const b of document.querySelectorAll('#dash-root #vh-refresh')) b.addEventListener('click', () => { refreshLive(); dash.refresh('book'); dash.refresh('model'); });

/* ---------- drawings ---------- */
// One drawing for every single value: the element says which source, field, row and format.
dash.draw('val', (el) => {
  const s = dash.data(el.dataset.source), key = el.dataset.field, w = el.dataset.where;
  let row = null;
  if (s.status === 'ok' && Array.isArray(s.data)) {
    if (w) { const i = w.indexOf('='), k = w.slice(0, i), v = decodeURIComponent(w.slice(i + 1)); row = s.data.find((r) => String(r[k]) === v) || null; }
    else row = s.data[Number(el.dataset.row || 0)] || null;
  }
  const v = row ? row[key] : null;
  el.classList.toggle('dash-skeleton', s.status === 'loading');
  el.textContent = v == null ? '—' : (FMT[el.dataset.fmt || 'text'] || FMT.text)(v);
  if (el.dataset.tone != null) { el.classList.toggle('vh-up', v != null && v > 0); el.classList.toggle('vh-down', v != null && v < 0); }
});

dash.draw('fresh', {
  mount: () => ({timer: setInterval(() => {
    const auto = document.getElementById('vh-auto');
    if (auto && auto.checked && document.visibilityState === 'visible' && marketOpen()) refreshLive();
  }, 60000)}),
  update: (el) => {
    const m = rowsOf('market');
    const at = m.rows.map((r) => r.at).filter(Boolean).sort().pop();
    el.textContent = !m.ok ? waitText(m.status) : at ? 'Quotes from ' + ptClock(new Date(at), true) + ' PT' + (marketOpen() ? '' : ', market closed') : '—';
  },
  unmount: (el, made) => { if (made && made.timer) clearInterval(made.timer); },
});

dash.draw('market', (el) => {
  const m = rowsOf('market');
  el.replaceChildren(...m.rows.filter((r) => r.symbol === 'SPY' || r.symbol === 'IWM').map((r) => h('span', {class: 'vh-mkt'},
    h('b', {text: r.symbol}), h('span', {'data-source': 'market', 'data-field': 'last', 'data-where': 'symbol=' + r.symbol, text: FMT.px(r.last)}),
    h('span', {class: tone(r.change_pct).trim(), 'data-source': 'market', 'data-field': 'change_pct', 'data-where': 'symbol=' + r.symbol, text: (r.change_pct > 0 ? '+' : '') + d3.format('.2f')(r.change_pct) + '%'}))));
});

dash.draw('risk-bar', (el) => {
  const s = rowsOf('stats'), v = s.rows[0] ? s.rows[0].risk_pct : null;
  el.replaceChildren(h('div', {class: 'vh-meter-fill' + (v != null && v > 85 ? ' vh-hot' : ''), style: 'width:' + Math.max(0, Math.min(100, v || 0)) + '%'}));
  el.setAttribute('aria-label', v == null ? 'Risk in use' : v + ' percent of the account is at risk');
});

const drawRange = (host, p, sv) => {
  const w = Math.max(220, host.clientWidth), H = 84, pad = 16, y = 44;
  const spot = sv && sv.spot != null ? sv.spot : null, span = p.wing_high - p.wing_low;
  const lo = Math.min(p.wing_low - span * 0.12, spot == null ? Infinity : spot - span * 0.04), hi = Math.max(p.wing_high + span * 0.12, spot == null ? -Infinity : spot + span * 0.04);
  const x = d3.scaleLinear().domain([lo, hi]).range([pad, w - pad]);
  const svg = d3.create('svg').attr('viewBox', '0 0 ' + w + ' ' + H).attr('width', '100%').attr('role', 'img')
    .attr('aria-label', p.symbol + (spot == null ? '' : ' at ' + FMT.px(spot)) + ', breakevens ' + p.be_low + ' and ' + p.be_high);
  svg.append('rect').attr('x', pad).attr('y', y - 5).attr('width', w - 2 * pad).attr('height', 10).attr('rx', 5).style('fill', 'var(--color-bad)').style('opacity', 0.25);
  svg.append('rect').attr('x', x(p.be_low)).attr('y', y - 5).attr('width', Math.max(2, x(p.be_high) - x(p.be_low))).attr('height', 10).style('fill', 'var(--color-ok)').style('opacity', 0.6);
  const clampX = (v) => Math.max(pad + 14, Math.min(w - pad - 14, x(v)));
  for (const v of [p.wing_low, p.body, p.wing_high]) {
    svg.append('line').attr('x1', x(v)).attr('x2', x(v)).attr('y1', y + 6).attr('y2', y + 12).style('stroke', 'var(--cds-chart-axis)');
    svg.append('text').attr('x', clampX(v)).attr('y', y + 25).attr('text-anchor', 'middle').text(d3.format('~g')(v));
  }
  for (const v of [p.be_low, p.be_high]) {
    svg.append('line').attr('x1', x(v)).attr('x2', x(v)).attr('y1', y - 12).attr('y2', y + 6).style('stroke', 'var(--color-fg-muted)');
    svg.append('text').attr('x', clampX(v)).attr('y', y - 16).attr('text-anchor', 'middle').text(d3.format(',.2f')(v));
  }
  svg.append('text').attr('x', pad).attr('y', H - 2).attr('text-anchor', 'start').text('wing');
  svg.append('text').attr('x', w - pad).attr('y', H - 2).attr('text-anchor', 'end').text('wing');
  if (spot != null) {
    svg.append('line').attr('x1', x(spot)).attr('x2', x(spot)).attr('y1', y - 9).attr('y2', y + 9).style('stroke', 'var(--color-fg)').style('stroke-width', 2);
    svg.append('circle').attr('cx', x(spot)).attr('cy', y).attr('r', 5).style('fill', 'var(--color-fg)').style('stroke', 'var(--color-panel)').style('stroke-width', 2);
    svg.append('text').attr('class', 'vh-lab').attr('x', clampX(spot)).attr('y', 10).attr('text-anchor', 'middle').text('now ' + FMT.px(spot));
  }
  host.replaceChildren(svg.node());
};

dash.draw('cards', (el) => {
  const P = rowsOf('positions'), O = rowsOf('open_pl'), S = rowsOf('spot_view');
  if (!P.ok) { el.replaceChildren(h('p', {class: 'vh-empty', text: waitText(P.status)})); return; }
  const o = new Map(O.rows.map((r) => [r.trade_id, r])), sv = new Map(S.rows.map((r) => [r.trade_id, r]));
  const hosts = [];
  el.replaceChildren(...P.rows.map((p) => {
    const q = o.get(p.trade_id) || {}, s = sv.get(p.trade_id) || {}, where = 'trade_id=' + p.trade_id;
    const host = h('div', {class: 'vh-range vh-chart', 'data-source': 'spot_view'});
    hosts.push([host, p, s]);
    const pl = q.pl_mid;
    return h('article', {class: 'vh-pos', id: 'pos-' + p.trade_id},
      h('div', {class: 'vh-pos-top'},
        h('div', null, h('span', {class: 'vh-pos-name', text: p.symbol}), h('span', {class: 'vh-pos-strikes', text: [p.wing_low, p.body, p.wing_high].map(d3.format('~g')).join(' / ') + '  x' + p.qty})),
        h('div', {class: 'vh-chips'}, h('span', {class: 'vh-chip', text: p.line}), h('span', {class: 'vh-chip' + (p.lane === 'agent' ? '' : ' vh-chip-you'), text: p.lane_label}))),
      h('div', null,
        h('div', {class: 'vh-pos-pl' + tone(pl) + (O.status === 'loading' ? ' dash-skeleton' : ''), 'data-source': 'open_pl', 'data-field': 'pl_mid', 'data-where': where, text: pl == null ? '—' : FMT.signed(pl)}),
        h('div', {class: 'vh-pos-plsub'}, pl == null ? (O.status === 'connect' ? 'Waiting for the Robinhood connection' : 'No live quote yet') : [
          h('span', {'data-source': 'open_pl', 'data-field': 'pct_of_max_profit', 'data-where': where, text: FMT.pct0(q.pct_of_max_profit)}), ' of the most it can make. ',
          h('span', {'data-source': 'open_pl', 'data-field': 'pl_at_market', 'data-where': where, text: FMT.signed(q.pl_at_market)}), ' if closed at market.'])),
      host,
      h('dl', {class: 'vh-kv'},
        h('dt', {text: 'Credit taken in'}), h('dd', {'data-source': 'positions', 'data-field': 'credit', 'data-where': where, text: FMT.px(p.credit)}),
        h('dt', {text: 'Cost to close now'}), h('dd', {'data-source': 'open_pl', 'data-field': 'close_mid', 'data-where': where, text: q.close_mid == null ? '—' : d3.format(',.3f')(q.close_mid)}),
        h('dt', {text: 'Most it can lose'}), h('dd', {'data-source': 'positions', 'data-field': 'max_loss', 'data-where': where, text: FMT.money(p.max_loss)}),
        h('dt', {text: 'Most it can make'}), h('dd', {'data-source': 'positions', 'data-field': 'max_profit', 'data-where': where, text: p.max_profit == null ? '—' : FMT.money(p.max_profit)}),
        h('dt', {text: 'Room to the breakevens'}), h('dd', {text: s.room_down_pct == null ? '—' : d3.format('.1f')(s.room_down_pct) + '% down, ' + d3.format('.1f')(s.room_up_pct) + '% up'}),
        h('dt', {text: 'Opened'}), h('dd', {text: p.opened_pt + ' PT'}),
        h('dt', {text: 'Expires'}), h('dd', {text: FMT.day(p.expiry)})),
      h('div', {class: 'vh-plan'}, h('b', {text: 'Plan: '}), p.plan || '—', p.report ? h('div', {class: 'vh-item-body', text: 'Report: ' + p.report}) : null));
  }));
  for (const [host, p, s] of hosts) drawRange(host, p, s);
});

/* a tooltip that stays inside its chart */
const makeTip = (el) => {
  const t = h('div', {class: 'vh-tip'});
  t.hidden = true;
  el.append(t);
  return {
    show: (lines, px, py) => {
      t.replaceChildren(...lines.map((l, i) => h('div', {class: i === 0 ? 'vh-tip-h' : null, text: l})));
      t.hidden = false;
      const w = t.offsetWidth, hh = t.offsetHeight, W = el.clientWidth;
      t.style.left = Math.max(0, Math.min(W - w, px + 12)) + 'px';
      t.style.top = Math.max(0, py - hh - 10) + 'px';
    },
    hide: () => { t.hidden = true; },
  };
};
/* Reading a chart with a mouse or a finger. The mark under the pointer answers, so a finger
   that slides across a chart is followed from mark to mark. When it lifts, the reading stays
   until something else is touched. A mouse that leaves puts it away. */
const reads = new WeakMap();
const readable = (sel, fn) => { reads.set(sel.node(), fn); return sel; };
const clearReading = (host) => {
  for (const t of host.querySelectorAll('.vh-tip')) t.hidden = true;
  for (const l of host.querySelectorAll('.vh-cross')) l.style.display = 'none';
};
document.addEventListener('pointerdown', (event) => {
  for (const c of document.querySelectorAll('#dash-root .vh-chart')) if (!c.contains(event.target)) clearReading(c);
}, true);
/* a finger that starts sideways is reading the chart: the page stays put under it */
const lockScrub = (node) => {
  let x0 = 0, y0 = 0, mode = null;
  node.addEventListener('touchstart', (e) => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; mode = null; }, {passive: true});
  node.addEventListener('touchmove', (e) => {
    if (mode === null) {
      const dx = Math.abs(e.touches[0].clientX - x0), dy = Math.abs(e.touches[0].clientY - y0);
      if (dx + dy < 6) return;
      mode = dx >= dy ? 'scrub' : 'scroll';
    }
    if (mode === 'scrub' && e.cancelable) e.preventDefault();
  }, {passive: false});
};
const frame = (el, w, H, label) => {
  const svg = d3.create('svg').attr('viewBox', '0 0 ' + w + ' ' + H).attr('width', '100%').attr('role', 'img').attr('aria-label', label);
  const read = (event) => {
    const hit = svg.node().getRootNode().elementFromPoint(event.clientX, event.clientY), fn = hit && reads.get(hit);
    if (fn) fn(event);
    else if (event.pointerType === 'mouse') clearReading(el);
  };
  svg.on('pointerdown', read).on('pointermove', read).on('pointerleave', (event) => { if (event.pointerType === 'mouse') clearReading(el); });
  lockScrub(svg.node());
  return svg;
};
const yAxis = (svg, y, m, w, fmt) => {
  const g = svg.append('g');
  for (const v of y.ticks(5)) {
    g.append('line').attr('x1', m.l).attr('x2', w - m.r).attr('y1', y(v)).attr('y2', y(v)).style('stroke', v === 0 ? 'var(--cds-chart-reference)' : 'var(--cds-chart-grid)').style('stroke-width', v === 0 ? 1.25 : 1);
    g.append('text').attr('x', m.l - 8).attr('y', y(v) + 4).attr('text-anchor', 'end').text(fmt(v));
  }
};
const usd0 = (v) => (v < 0 ? '\u2212$' : '$') + d3.format(',.0f')(Math.abs(v));

dash.draw('intraday', (el) => {
  const C = rowsOf('curve'), E = rowsOf('events');
  if (!C.ok || !C.rows.length) { el.replaceChildren(h('p', {class: 'vh-empty', text: !C.ok ? waitText(C.status) : 'No bars for this window yet.'})); return; }
  const rows = C.rows.map((r) => Object.assign({T: new Date(r.t)}, r));
  const w = Math.max(280, el.clientWidth), H = 300, m = {t: 16, r: 78, b: 28, l: 54};
  const x = d3.scaleTime().domain(d3.extent(rows, (r) => r.T)).range([m.l, w - m.r]);
  const vals = rows.flatMap((r) => [r.total, r.closed]);
  const y = d3.scaleLinear().domain([Math.min(0, d3.min(vals)), Math.max(0, d3.max(vals))]).nice().range([H - m.b, m.t]);
  const svg = frame(el, w, H, 'Profit and loss through the session: closed results plus the open flies');
  yAxis(svg, y, m, w, usd0);
  for (const t of x.ticks(Math.max(2, Math.floor((w - m.l - m.r) / 90)))) svg.append('text').attr('x', x(t)).attr('y', H - 8).attr('text-anchor', 'middle').text(ptClock(t));
  const c0 = dash.colors[0];
  svg.append('path').attr('d', d3.line().x((r) => x(r.T)).y((r) => y(r.closed)).curve(d3.curveStepAfter)(rows)).style('fill', 'none').style('stroke', 'var(--cds-chart-muted)').style('stroke-width', 1.5).style('stroke-dasharray', '4 3');
  svg.append('path').attr('d', d3.line().x((r) => x(r.T)).y((r) => y(r.total))(rows)).style('fill', 'none').style('stroke', c0).style('stroke-width', 2);
  const last = rows[rows.length - 1];
  let yT = y(last.total), yC = y(last.closed);
  if (Math.abs(yT - yC) < 14) { if (yT <= yC) { yT -= 7; yC += 7; } else { yT += 7; yC -= 7; } }
  svg.append('circle').attr('cx', x(last.T)).attr('cy', y(last.total)).attr('r', 4).style('fill', c0);
  svg.append('text').attr('class', last.total < 0 ? 'vh-lab-down' : 'vh-lab-up').attr('x', x(last.T) + 8).attr('y', yT + 4).text(FMT.signed0(last.total));
  svg.append('text').attr('x', x(last.T) + 8).attr('y', yC + 4).text('closed ' + FMT.signed0(last.closed));
  const [t0, t1] = x.domain();
  const near = (T) => rows.reduce((b, r) => (Math.abs(r.T - T) < Math.abs(b.T - T) ? r : b), rows[0]);
  const ev = E.rows.map((e) => Object.assign({T: new Date(e.t)}, e)).filter((e) => e.T >= t0 && e.T <= t1);
  const dots = svg.append('g');
  for (const e of ev) {
    const r = near(e.T);
    dots.append('circle').attr('cx', x(e.T)).attr('cy', y(r.total)).attr('r', 5).style('fill', e.kind === 'in' ? 'var(--color-panel)' : c0).style('stroke', c0).style('stroke-width', 2);
  }
  const cross = svg.append('line').attr('class', 'vh-cross').attr('y1', m.t).attr('y2', H - m.b).style('stroke', 'var(--cds-chart-axis)').style('display', 'none');
  const legend = h('div', {class: 'vh-legend'},
    h('span', {class: 'vh-key'}, h('span', {class: 'vh-swatch', style: 'border-top-color:' + c0}), 'Closed today plus open flies'),
    h('span', {class: 'vh-key'}, h('span', {class: 'vh-swatch vh-swatch-dash', style: 'border-top-color:var(--cds-chart-muted)'}), 'Closed today only'),
    h('span', {class: 'vh-key'}, h('span', {class: 'vh-swatch vh-swatch-dot', style: 'background:' + c0}), 'A trade'));
  el.replaceChildren(legend, svg.node());
  const tip = makeTip(el);
  readable(svg.append('rect').attr('x', 0).attr('y', 0).attr('width', w).attr('height', H).style('fill', 'transparent'), (event) => {
      const px = Math.max(m.l, Math.min(w - m.r, d3.pointer(event, svg.node())[0])), r = near(x.invert(px));
      cross.attr('x1', x(r.T)).attr('x2', x(r.T)).style('display', null);
      const hit = ev.filter((e) => Math.abs(x(e.T) - x(r.T)) < 8).map((e) => e.what + (e.pnl == null ? '' : ' ' + FMT.signed(e.pnl)));
      tip.show([ptClock(r.T) + ' PT', 'Total ' + FMT.signed(r.total), 'Open flies ' + FMT.signed(r.open_pl), 'Closed today ' + FMT.signed(r.closed), ...hit], x(r.T) * el.clientWidth / w, legend.offsetHeight + y(r.total));
    });
});

dash.draw('events', (el) => {
  const E = rowsOf('events'), C = rowsOf('curve');
  if (!E.ok || !C.rows.length) { el.replaceChildren(); return; }
  const t0 = C.rows[0].t, t1 = C.rows[C.rows.length - 1].t;
  el.replaceChildren(...E.rows.filter((e) => e.t >= t0 && e.t <= t1).map((e) => h('li', null, ptClock(new Date(e.t)) + ' ', h('b', {text: e.what}), e.pnl == null ? '' : ' ' + FMT.signed(e.pnl))));
});

dash.draw('month', (el) => {
  const D = rowsOf('daily');
  const month = ptDay(new Date()).slice(0, 7), rows = D.rows.filter((r) => r.date.slice(0, 7) === month);
  if (!D.ok || !rows.length) { el.replaceChildren(h('p', {class: 'vh-empty', text: !D.ok ? waitText(D.status) : 'No closed results this month yet.'})); return; }
  const w = Math.max(280, el.clientWidth), H = 260, m = {t: 22, r: 12, b: 28, l: 54};
  const x = d3.scaleBand().domain(rows.map((r) => r.date)).range([m.l, w - m.r]).padding(0.35);
  const y = d3.scaleLinear().domain([Math.min(0, d3.min(rows, (r) => r.pnl)), Math.max(0, d3.max(rows, (r) => r.pnl))]).nice().range([H - m.b, m.t]);
  const svg = frame(el, w, H, 'Closed results by day this month');
  yAxis(svg, y, m, w, usd0);
  const bw = Math.min(46, x.bandwidth());
  el.replaceChildren(svg.node());
  const tip = makeTip(el);
  for (const r of rows) {
    const cx = x(r.date) + x.bandwidth() / 2, top = Math.min(y(0), y(r.pnl)), hgt = Math.max(1, Math.abs(y(r.pnl) - y(0)));
    svg.append('rect').attr('x', cx - bw / 2).attr('y', top).attr('width', bw).attr('height', hgt).attr('rx', Math.min(4, hgt / 2)).style('fill', r.pnl >= 0 ? 'var(--color-ok)' : 'var(--color-bad)');
    svg.append('text').attr('class', r.pnl >= 0 ? 'vh-lab-up' : 'vh-lab-down').attr('x', cx).attr('y', r.pnl >= 0 ? top - 5 : top + hgt + 14).attr('text-anchor', 'middle').text(FMT.signed0(r.pnl));
    svg.append('text').attr('x', cx).attr('y', H - 8).attr('text-anchor', 'middle').text(FMT.day(r.date));
  }
  /* one full-height column a day: a finger anywhere over the day reads it */
  for (const r of rows) {
    const cx = x(r.date) + x.bandwidth() / 2, top = Math.min(y(0), y(r.pnl));
    readable(svg.append('rect').attr('x', cx - x.step() / 2).attr('y', 0).attr('width', x.step()).attr('height', H).style('fill', 'transparent'),
      () => tip.show([FMT.day(r.date), FMT.signed(r.pnl), r.results + (r.results === 1 ? ' result' : ' results'), 'Running total ' + FMT.signed(r.running)], cx * el.clientWidth / w, top));
  }
});

dash.draw('ytd', (el) => {
  const R = rowsOf('running');
  if (!R.ok || !R.rows.length) { el.replaceChildren(h('p', {class: 'vh-empty', text: !R.ok ? waitText(R.status) : 'No closed results yet.'})); return; }
  const rows = R.rows.map((r) => Object.assign({T: new Date(r.exit_ts)}, r));
  const w = Math.max(280, el.clientWidth), H = 280, m = {t: 18, r: 70, b: 28, l: 54};
  const start = new Date(rows[0].T.getTime() - 6 * 3600e3);
  const x = d3.scaleTime().domain([start, rows[rows.length - 1].T]).range([m.l, w - m.r]);
  const y = d3.scaleLinear().domain([Math.min(0, d3.min(rows, (r) => r.running)), Math.max(0, d3.max(rows, (r) => r.running))]).nice().range([H - m.b, m.t]);
  const svg = frame(el, w, H, 'Running total of closed results since the first trade');
  yAxis(svg, y, m, w, usd0);
  for (const t of x.ticks(Math.max(2, Math.floor((w - m.l - m.r) / 90)))) svg.append('text').attr('x', x(t)).attr('y', H - 8).attr('text-anchor', 'middle').text(new Intl.DateTimeFormat('en-US', {timeZone: PT, month: 'short', day: 'numeric'}).format(t));
  const c0 = dash.colors[0], pts = [{T: start, running: 0}, ...rows];
  svg.append('path').attr('d', d3.line().x((r) => x(r.T)).y((r) => y(r.running)).curve(d3.curveStepAfter)(pts)).style('fill', 'none').style('stroke', c0).style('stroke-width', 2);
  el.replaceChildren(svg.node());
  const tip = makeTip(el);
  const cross = svg.append('line').attr('class', 'vh-cross').attr('y1', m.t).attr('y2', H - m.b).style('stroke', 'var(--cds-chart-axis)').style('display', 'none');
  for (const r of rows) {
    svg.append('circle').attr('cx', x(r.T)).attr('cy', y(r.running)).attr('r', 5).style('fill', r.pnl >= 0 ? 'var(--color-ok)' : 'var(--color-bad)').style('stroke', 'var(--color-panel)').style('stroke-width', 2);
  }
  const last = rows[rows.length - 1];
  svg.append('text').attr('class', last.running < 0 ? 'vh-lab-down' : 'vh-lab-up').attr('x', x(last.T) + 9).attr('y', y(last.running) + 4).text(FMT.signed0(last.running));
  /* the nearest result answers: a finger sliding along the line steps from trade to trade */
  readable(svg.append('rect').attr('x', 0).attr('y', 0).attr('width', w).attr('height', H).style('fill', 'transparent'), (event) => {
    const px = d3.pointer(event, svg.node())[0];
    const r = rows.reduce((b, q) => (Math.abs(x(q.T) - px) < Math.abs(x(b.T) - px) ? q : b), rows[0]);
    const same = rows.filter((q) => Math.abs(x(q.T) - x(r.T)) < 4), end = same[same.length - 1];
    cross.attr('x1', x(r.T)).attr('x2', x(r.T)).style('display', null);
    tip.show([FMT.day(r.date), ...same.map((q) => q.symbol + ' ' + q.type.toLowerCase() + ' ' + FMT.signed(q.pnl) + ', ' + q.who), 'Running total ' + FMT.signed(end.running)], x(r.T) * el.clientWidth / w, y(end.running));
  });
});

dash.draw('costs', (el) => {
  const T = rowsOf('trades'), rows = T.rows.filter((t) => t.cost_pct != null);
  if (!T.ok || !rows.length) { el.replaceChildren(h('p', {class: 'vh-empty', text: !T.ok ? waitText(T.status) : 'No closed trades with a cost reading yet.'})); return; }
  const w = Math.max(260, el.clientWidth), rh = 24, m = {t: 30, r: 44, b: 8, l: 50}, H = m.t + m.b + rows.length * rh;
  const x = d3.scaleLinear().domain([Math.min(0, d3.min(rows, (r) => r.cost_pct)), Math.max(COST_BREAKEVEN + 1, d3.max(rows, (r) => r.cost_pct))]).nice().range([m.l, w - m.r]);
  const svg = frame(el, w, H, 'Round-trip cost of each closed trade as a share of its credit, against the 5 percent target and the 9 percent breakeven');
  for (const [v, lab] of [[COST_TARGET, 'target ' + COST_TARGET + '%'], [COST_BREAKEVEN, 'breakeven ' + COST_BREAKEVEN + '%']]) {
    svg.append('line').attr('x1', x(v)).attr('x2', x(v)).attr('y1', m.t - 6).attr('y2', H - m.b).style('stroke', v === COST_BREAKEVEN ? 'var(--cds-chart-status-critical)' : 'var(--cds-chart-reference)').style('stroke-dasharray', '4 3');
    svg.append('text').attr('x', x(v)).attr('y', v === COST_TARGET ? 10 : 22).attr('text-anchor', v === COST_TARGET ? 'end' : 'start').attr('dx', v === COST_TARGET ? -3 : 3).text(lab);
  }
  svg.append('line').attr('x1', x(0)).attr('x2', x(0)).attr('y1', m.t - 6).attr('y2', H - m.b).style('stroke', 'var(--cds-chart-axis)');
  el.replaceChildren(svg.node());
  const tip = makeTip(el);
  rows.forEach((r, i) => {
    const yy = m.t + i * rh, x0 = x(0), x1 = x(r.cost_pct);
    svg.append('text').attr('x', m.l - 8).attr('y', yy + 15).attr('text-anchor', 'end').text(r.symbol);
    svg.append('rect').attr('x', Math.min(x0, x1)).attr('y', yy + 4).attr('width', Math.max(1, Math.abs(x1 - x0))).attr('height', rh - 9).attr('rx', 3)
      .style('fill', r.cost_pct > COST_BREAKEVEN ? 'var(--cds-chart-status-critical)' : dash.colors[0]);
    svg.append('text').attr('class', 'vh-lab').attr('x', r.cost_pct >= 0 ? x1 + 5 : x0 + 5).attr('y', yy + 15).text(FMT.pct1(r.cost_pct));
    readable(svg.append('rect').attr('x', 0).attr('y', yy).attr('width', w).attr('height', rh).style('fill', 'transparent'),
      () => tip.show([r.symbol + ', closed ' + FMT.day(r.date), 'Cost ' + FMT.pct1(r.cost_pct) + ' of the credit', 'Result ' + FMT.signed(r.pnl)], x1 * el.clientWidth / w, yy));
  });
});

dash.draw('evidence', (el) => {
  const E = rowsOf('evidence');
  if (!E.ok || !E.rows.length) { el.replaceChildren(h('p', {class: 'vh-empty', text: !E.ok ? waitText(E.status) : 'No replay table yet.'})); return; }
  const rows = E.rows, w = Math.max(260, el.clientWidth), H = 250, m = {t: 26, r: 10, b: 30, l: 44};
  const x = d3.scalePoint().domain(rows.map((r) => r.cap)).range([m.l + 14, w - m.r - 14]).padding(0.3);
  const y = d3.scaleLinear().domain([d3.min(rows, (r) => r.mean - r.se), d3.max(rows, (r) => r.mean + r.se)]).nice().range([H - m.b, m.t]);
  const svg = frame(el, w, H, 'Average replay result per earnings fly after costs, by name cap, with one standard error either way');
  yAxis(svg, y, m, w, usd0);
  el.replaceChildren(svg.node());
  const tip = makeTip(el);
  for (const r of rows) {
    const cx = x(r.cap), now = r.cap_usd === CAP_NOW, old = r.cap_usd === CAP_OLD, col = now ? dash.colors[0] : 'var(--cds-chart-muted)';
    svg.append('line').attr('x1', cx).attr('x2', cx).attr('y1', y(r.mean - r.se)).attr('y2', y(r.mean + r.se)).style('stroke', col).style('stroke-width', now ? 3 : 2);
    svg.append('circle').attr('cx', cx).attr('cy', y(r.mean)).attr('r', now ? 6 : 4.5).style('fill', col).style('stroke', 'var(--color-panel)').style('stroke-width', 1.5);
    svg.append('text').attr('x', cx).attr('y', H - 10).attr('text-anchor', 'middle').text(r.cap);
    if (now || old) svg.append('text').attr('class', 'vh-lab').attr('x', cx).attr('y', y(r.mean + r.se) - 7).attr('text-anchor', 'middle').text((now ? 'now ' : 'was ') + FMT.signed1(r.mean));
    const half = Math.max(14, x.step() / 2);
    readable(svg.append('rect').attr('x', cx - half).attr('y', 0).attr('width', 2 * half).attr('height', H).style('fill', 'transparent'),
      () => tip.show(['Cap ' + r.cap + ', ' + r.n + ' reports', 'Average ' + FMT.signed1(r.mean) + ' a fly', 'Give or take ' + FMT.money1(r.se), 'Worst report ' + FMT.signed0(r.worst)], cx * el.clientWidth / w, y(r.mean + r.se)));
  }
});

/* ---------- tables and lists ---------- */
const td = (text, cls) => h('td', {class: cls || null, text: text == null ? '—' : text});
const tdNum = (v, f, toned) => h('td', {class: 'vh-num' + (toned ? tone(v) : ''), text: v == null ? '—' : f(v)});
dash.draw('trades-body', (el) => {
  const T = rowsOf('trades');
  el.replaceChildren(...T.rows.slice().reverse().map((t) => h('tr', {'data-key': t.id},
    td(FMT.day(t.date) + ', ' + t.time_pt, 'vh-nw'), td(t.symbol), tdNum(t.pnl, FMT.signed, true), td(t.who, 'vh-nw'), td(t.line, 'vh-nw'), td(t.type, 'vh-nw'), td(t.strikes, 'vh-nw'),
    tdNum(t.qty, String), tdNum(t.credit, FMT.px), tdNum(t.close, FMT.px), tdNum(t.pct_of_max_loss, FMT.pct1), tdNum(t.cost_pct, FMT.pct1))));
});
dash.draw('by-line', (el) => {
  el.replaceChildren(...rowsOf('by_line').rows.map((r) => h('tr', {'data-key': r.line}, td(r.line), tdNum(r.results, String), tdNum(r.wins, String), tdNum(r.pnl, FMT.signed, true))));
});
dash.draw('by-lane', (el) => {
  el.replaceChildren(...rowsOf('by_lane').rows.map((r) => h('tr', {'data-key': r.lane}, td(r.who), tdNum(r.results, String), tdNum(r.wins, String), tdNum(r.pnl, FMT.signed, true))));
});
dash.draw('scores-body', (el) => {
  el.replaceChildren(...rowsOf('scores').rows.map((s) => h('tr', {'data-key': s.trade_id},
    td(s.symbol + ', ' + FMT.day(s.made), 'vh-nw'), tdNum(s.projected, FMT.signed, false), td(s.range, 'vh-nw'), tdNum(s.actual, FMT.signed, true), td(s.verdict))));
});
dash.draw('paper-body', (el) => {
  el.replaceChildren(...rowsOf('paper').rows.map((p) => h('tr', {'data-key': p.test}, td(p.test), tdNum(p.n, String), tdNum(p.scored, String), tdNum(p.scored ? p.pnl_mid : null, FMT.signed), tdNum(p.scored ? p.pnl_after_spreads : null, FMT.signed, true))));
});
const item = (id, title, lines, extra) => h('div', {class: 'vh-item', 'data-key': id},
  h('div', {class: 'vh-item-head'}, h('span', {class: 'vh-item-id', text: id}), h('span', {text: title}), extra || null),
  ...lines.filter((l) => l && l[1]).map((l) => h('div', {class: 'vh-item-body'}, h('b', {text: l[0]}), ' ' + l[1])));
dash.draw('latest-fix', (el) => {
  const P = rowsOf('proposals'), p = P.rows.filter((x) => x.heal).slice(-1)[0];
  if (!p) { el.replaceChildren(document.createTextNode(P.ok ? 'No fixes on record yet.' : waitText(P.status))); return; }
  el.replaceChildren(h('h3', {class: 'vh-h3', text: 'Latest fix, ' + FMT.day(p.date) + ': ' + p.title}),
    h('div', {class: 'vh-item-body'}, h('b', {text: 'What went wrong.'}), ' ' + p.problem),
    h('div', {class: 'vh-item-body'}, h('b', {text: 'What changed.'}), ' ' + p.change),
    h('div', {class: 'vh-item-body'}, h('b', {text: 'How it is judged.'}), ' ' + (p.measure || '—')));
});
dash.draw('props-wait', (el) => {
  const P = rowsOf('proposals'), rows = P.rows.filter((x) => x.state === 'Waiting on you');
  if (!rows.length) { el.replaceChildren(document.createTextNode(P.ok ? 'Nothing is waiting on you.' : waitText(P.status))); return; }
  el.replaceChildren(...rows.map((p) => item(p.id, p.title, [['Why:', p.problem], ['What it takes:', p.change]])));
});
const liveRow = (p) => h('tr', {'data-key': p.id}, td(p.id, 'vh-nw'), td(FMT.day(p.date), 'vh-nw'), td(p.title + (p.state === 'Approved, not built yet' ? ' (approved, not built yet)' : ''), 'vh-wrap'), td(p.measure, 'vh-wrap'), td(p.review_date ? FMT.day(p.review_date) : '—', 'vh-nw'));
const liveRows = () => rowsOf('proposals').rows.filter((x) => x.state === 'In force, being measured' || x.state === 'Approved, not built yet').slice().reverse();
dash.draw('props-live', (el) => { el.replaceChildren(...liveRows().slice(0, 6).map(liveRow)); });
dash.draw('props-live-more', (el) => { el.replaceChildren(...liveRows().slice(6).map(liveRow)); });
dash.draw('props-closed', (el) => {
  const rows = rowsOf('proposals').rows.filter((x) => x.state === 'Closed').slice().reverse();
  const word = {worked: 'Worked', inconclusive: 'Inconclusive', declined: 'Turned down', did_not_work: 'Did not work'};
  el.replaceChildren(...rows.map((p) => item(p.id, p.title, [['Verdict:', p.verdict_note]], h('span', {class: 'vh-chip' + (p.verdict === 'worked' ? ' vh-chip-core' : ''), text: word[p.verdict] || p.verdict}))));
});
dash.draw('rules', (el) => {
  el.replaceChildren(...rowsOf('rules').rows.slice().reverse().map((r) => h('li', {'data-key': r.version}, h('span', {class: 'vh-ver', text: r.version}), h('span', {class: 'vh-when', text: FMT.day(r.date)}), h('span', {text: r.title.charAt(0).toUpperCase() + r.title.slice(1)}))));
});
const tally = (l) => h('span', {class: 'vh-tally'}, h('span', {class: 'vh-up', text: l.supports + ' for'}), ', ', h('span', {class: 'vh-down', text: l.contradicts + ' against'}), l.neutral ? ', ' + l.neutral + ' unclear' : '');
const lessonItem = (l) => h('div', {class: 'vh-item', 'data-key': l.id},
  h('div', {class: 'vh-item-head'}, h('span', {class: 'vh-item-id', text: l.id + ', ' + l.kind}), tally(l), l.group === 'Waiting on you' ? h('span', {class: 'vh-chip vh-chip-you', text: 'Ready, waiting on you'}) : null),
  h('div', {class: 'vh-item-body', text: l.statement}));
const lessonList = (name, keep, from, to, none) => dash.draw(name, (el) => {
  const L = rowsOf('lessons'), rows = L.rows.filter(keep).slice().reverse().slice(from, to);
  if (!rows.length) { el.replaceChildren(document.createTextNode(L.ok ? none : waitText(L.status))); return; }
  el.replaceChildren(...rows.map(lessonItem));
});
lessonList('lessons-on', (l) => l.group === 'In force', 0, 4, 'None yet.');
lessonList('lessons-on-more', (l) => l.group === 'In force', 4, undefined, 'No others.');
lessonList('lessons-test', (l) => l.group !== 'In force', 0, 4, 'None right now.');
lessonList('lessons-test-more', (l) => l.group !== 'In force', 4, undefined, 'No others.');
const healList = (name, from, to, none) => dash.draw(name, (el) => {
  const P = rowsOf('proposals'), rows = P.rows.filter((x) => x.heal).slice().reverse().slice(from, to);
  if (!rows.length) { el.replaceChildren(document.createTextNode(P.ok ? none : waitText(P.status))); return; }
  el.replaceChildren(...rows.map((p) => item(p.id + ', ' + FMT.day(p.date), p.title, [['Broke:', p.problem], ['Changed:', p.change]])));
});
healList('heals', 1, 4, 'Nothing earlier on record.');
healList('heals-more', 4, undefined, 'Nothing earlier.');
dash.draw('upcoming', (el) => {
  const rows = rowsOf('upcoming').rows.slice(0, 10);
  el.replaceChildren(...rows.map((u) => h('li', null, h('span', {class: 'vh-when', text: u.when ? d3.utcFormat('%a %b %-d')(new Date(u.when + 'T00:00:00Z')) : 'Soon'}), h('span', {text: u.what}), h('span', {class: 'vh-chip' + (u.who === 'You' ? ' vh-chip-you' : ''), text: u.who}))));
});
