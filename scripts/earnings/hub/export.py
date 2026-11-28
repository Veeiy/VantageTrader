#!/usr/bin/env python3
"""Export the trading ledgers for the Vantage Trading Hub dashboard.

Usage: python3 export.py --repo /home/user/VantageTrader --out <dir> [--today YYYY-MM-DD]

Writes three files into <dir>:
  book.json       positions, legs, trades and the account snapshot (changes with every trade)
  model.json      rule versions, proposals, lessons, projection scores, replay evidence,
                  what is coming up, the pilot and the paper desk (changes at the daily reflection)
  live_args.json  the option ids and symbols the dashboard's live quote calls use, and the
                  store writes that put them there (the documents are in <dir>/store/)

It reads the repo's files and the engine's own read-only commands. No network, no broker, no
account number. The output depends on the ledgers and the trading date alone, so a second run
with nothing new writes the same bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LA = ZoneInfo("America/Los_Angeles")
LINE = {"earnings": "Earnings", "non_earnings": "Other", "intraday_0dte": "Same-day"}
MAX_IDS_PER_CALL = 10          # the broker's option-history call takes ten contracts
MIN_CHART_MINUTES = 15         # a fly closed today is drawn only if it was open this long in the session


def jl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def cli(repo, *args):
    """One read-only engine command, parsed. None when it fails."""
    env = dict(os.environ, PYTHONPATH=os.path.join(repo, "src"))
    r = subprocess.run([sys.executable, "-m", "vantage_trader.earnings", *args], cwd=repo, env=env,
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def utc(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pt_date(ts):
    return utc(ts).astimezone(LA).strftime("%Y-%m-%d")


def pt_time(ts):
    return utc(ts).astimezone(LA).strftime("%H:%M")


def clip(text, n):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def strikes_of(structure):
    m = re.search(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", structure or "")
    return [float(x) for x in m.groups()] if m else [None, None, None]


def lane_of(entry):
    """Who decided and who placed it. Read from the journal entry's own flags and notes."""
    notes = str(entry.get("notes") or "")
    if entry.get("lane") == "owner_executed":
        return "brad_lane", "You, 4-leg ticket"
    if entry.get("hand_entered"):
        return "brad_hand", "You, by hand"
    if entry.get("owner_override") or re.match(r"\s*(Owner-directed|OWNER OVERRIDE)", notes):
        return "agent_override", "Agent, your call"
    return "agent", "Agent"


# ------------------------------------------------------------------ book.json

def build_book(repo, today):
    D = os.path.join(repo, "state", "earnings")
    pos = json.load(open(os.path.join(D, "positions.json")))
    journal = jl(os.path.join(D, "journal.jsonl"))
    lm = jl(os.path.join(D, "live_metrics.jsonl"))
    metrics = cli(repo, "live-metrics") or {}
    cost_by_id = {t["trade_id"]: t.get("round_trip_cost") for t in metrics.get("trades", [])}
    entry_recs = [r for r in lm if r.get("record") == "entry"]
    ids_by_symbol = {}
    for r in entry_recs:
        ids_by_symbol.setdefault(r["symbol"], []).append(r["trade_id"])

    # -- closed round trips: pair entries and exits per symbol, adds merged (as journal.closed_trades)
    open_by, pairs, heals = {}, [], []
    for ev in journal:
        kind, sym = ev.get("event"), ev.get("symbol")
        if kind == "entry_filled":
            if ev.get("add") and open_by.get(sym):
                open_by[sym][-1]["adds"].append(ev)
            else:
                open_by.setdefault(sym, []).append({"first": ev, "adds": []})
        elif kind == "exit_filled" and open_by.get(sym):
            pairs.append((open_by[sym].pop(0), ev))
        elif kind == "heal" and isinstance(ev.get("pnl"), (int, float)) and ev["pnl"] != 0:
            heals.append(ev)
    seen = {}

    def trade_id(sym):
        n = seen.get(sym, 0)
        seen[sym] = n + 1
        ids = ids_by_symbol.get(sym, [])
        return ids[n] if n < len(ids) else f"{sym}-{n + 1}"

    trades = []
    closed_today_tranches = []
    for ent, ex in pairs:
        first, tranches = ent["first"], [ent["first"]] + ent["adds"]
        qty = sum(float(t.get("quantity") or 0) for t in tranches) or float(ex.get("quantity") or 1)
        credit = sum(float(t["price"]) * float(t.get("quantity") or 0) for t in tranches) / qty
        tid = trade_id(first["symbol"])
        lane, lane_label = lane_of(first)
        for t in ent["adds"]:                       # an add ordered by Brad marks the whole trade
            if lane == "agent" and lane_of(t)[0] != "agent":
                lane, lane_label = lane_of(t)
        max_loss = ex.get("max_loss") or sum(float(t.get("max_loss") or 0) for t in tranches) or None
        if ex.get("pnl") is not None:
            pnl = float(ex["pnl"])
        else:                                       # an exit journaled without its result: credit minus the closing price
            pnl = round((credit - float(ex.get("price") or 0.0)) * 100 * qty, 2)
        trades.append({
            "id": tid, "row_type": "Closed", "date": pt_date(ex["ts"]), "time_pt": pt_time(ex["ts"]),
            "exit_ts": iso(utc(ex["ts"])), "entry_ts": iso(utc(first["ts"])),
            "symbol": first["symbol"], "strikes": "/".join(f"{s:g}" for s in strikes_of(first.get("structure")) if s is not None),
            "line": LINE.get(first.get("kind"), "Earnings"), "lane": lane, "lane_label": lane_label,
            "qty": int(qty), "credit": round(credit, 4), "close": ex.get("price"), "pnl": round(pnl, 2),
            "max_loss": max_loss, "pct_max_loss": round(pnl / max_loss, 4) if max_loss else None,
            "cost_share": cost_by_id.get(tid), "hold_hours": round((utc(ex["ts"]) - utc(first["ts"])).total_seconds() / 3600, 1),
            "win": pnl >= 0, "outside_test_data": bool(first.get("outside_test_data")),
        })
        if pt_date(ex["ts"]) == today:
            for t in tranches:
                closed_today_tranches.append({"trade_id": tid, "symbol": first["symbol"], "legs": t.get("legs") or [],
                                              "qty": float(t.get("quantity") or 1), "from": t["ts"], "to": ex["ts"]})
    open_by_symbol = {p["symbol"]: p for p in pos.get("open", [])}
    adjust_recs = {(r["symbol"], r["ts"][:19]): r for r in lm if r.get("record") == "adjust"}
    for ev in heals:
        sym, pnl = ev["symbol"], float(ev["pnl"])
        rec = adjust_recs.get((sym, ev["ts"][:19]), {})
        p = open_by_symbol.get(sym)
        partial = bool(ev.get("hand_exit")) or rec.get("tag") == "owner_partial_close"
        qty = int(ev.get("quantity") or 1)
        credit = None
        if rec.get("close_debit") is not None and rec.get("pnl_before_fees_usd") is not None:
            credit = round(rec["close_debit"] + rec["pnl_before_fees_usd"] / 100 / qty, 4)
        lane, lane_label = ("brad_hand", "You, by hand") if ev.get("hand_exit") else ("agent", "Agent")
        max_loss = (rec.get("risk") or {}).get("max_loss_usd")
        ids = ids_by_symbol.get(sym, [])
        trades.append({
            "id": f"{sym}-adj-{pt_date(ev['ts'])}", "row_type": "Partial close" if partial else "Adjustment",
            "date": pt_date(ev["ts"]), "time_pt": pt_time(ev["ts"]), "exit_ts": iso(utc(ev["ts"])), "entry_ts": None,
            "symbol": sym, "strikes": "/".join(f"{s:g}" for s in strikes_of(ev.get("structure")) if s is not None),
            "line": LINE.get(ev.get("kind"), "Earnings"), "lane": lane, "lane_label": lane_label,
            "qty": qty, "credit": credit, "close": ev.get("price") if partial else None, "pnl": round(pnl, 2),
            "max_loss": max_loss, "pct_max_loss": round(pnl / max_loss, 4) if max_loss else None,
            "cost_share": None, "hold_hours": None, "win": pnl >= 0, "outside_test_data": False,
            "of_trade": ids[-1] if ids else None,
        })
        if partial and p and pt_date(ev["ts"]) == today:
            legs = [{"option_id": v["option_id"], "side": "sell" if k.startswith("short") else "buy",
                     "strike": float(re.sub(r"[CP]$", "", k.split("_", 1)[1])), "type": "call" if k.endswith("C") else "put",
                     "fill": v["fill"]} for k, v in p["legs"].items()]
            closed_today_tranches.append({"trade_id": p["trade_id"], "symbol": sym, "legs": legs, "qty": float(qty),
                                          "from": p["opened"], "to": ev["ts"]})
    trades.sort(key=lambda t: t["exit_ts"])

    # -- open positions and their legs
    positions, legs, stock = [], [], []
    for p in pos.get("open", []):
        if p.get("kind") == "equity":
            # Shares (e.g. the owner's hand buy of ANT on 2026-11-20) have no fly to draw: list them on the account row.
            who = "yours" if p.get("hand_entered") or p.get("lane") == "owner_hand" else "agent"
            stock.append(f"{p['symbol']} {int(p['quantity'])} sh at {float(p['avg_price']):.2f} ({who})")
            continue
        lo, body, hi = strikes_of(p.get("structure"))
        if p.get("lane") == "owner_executed":
            lane, lane_label = "brad_lane", "You, 4-leg ticket"
        elif p.get("hand_entered"):
            lane, lane_label = "brad_hand", "You, by hand"
        elif p.get("owner_override"):
            lane, lane_label = "agent_override", "Agent, your call"
        else:
            lane, lane_label = "agent", "Agent"
        plan = p.get("plan") or {}
        rider = p.get("rider") or {}
        if rider:
            ct = rider.get("close_today") or {}
            plan_text = "Your hold. " + (f"Closing ticket to you at {ct['ticket_and_push_pt']} PT today." if ct.get("ticket_and_push_pt")
                                         else "Your call when to close.")
        else:
            plan_text = clip(re.sub(r"\s*\(.*$", "", str(plan.get("exit") or "")), 90)
            plan_text = plan_text[:1].upper() + plan_text[1:]
        be = p.get("breakevens") or [None, None]
        positions.append({
            "trade_id": p["trade_id"], "symbol": p["symbol"], "line": LINE.get(p.get("kind"), "Earnings"),
            "lane": lane, "lane_label": lane_label, "qty": int(p["quantity"]), "credit": p["net_credit"],
            "max_loss": p["max_loss_usd"], "max_profit": p.get("max_profit_usd"), "be_low": be[0], "be_high": be[1],
            "wing_low": lo, "body": body, "wing_high": hi, "expiry": p.get("expiry"), "opened": iso(utc(p["opened"])),
            "opened_pt": utc(p["opened"]).astimezone(LA).strftime("%b %-d, %H:%M"), "plan": plan_text,
            "report": clip(p.get("report"), 60) or None,
        })
        for k, v in p["legs"].items():
            name = k.split("_", 1)[1]
            legs.append({"trade_id": p["trade_id"], "symbol": p["symbol"], "instrument_id": v["option_id"],
                         "side": "short" if k.startswith("short") else "long", "strike": float(name[:-1]),
                         "type": "call" if name.endswith("C") else "put", "fill": v["fill"], "qty": int(v.get("qty") or p["quantity"]),
                         "from_ts": iso(utc(p["opened"])), "to_ts": None, "open": True})
    session_start = datetime.fromisoformat(today + "T06:30:00").replace(tzinfo=LA)
    for t in closed_today_tranches:
        start = max(utc(t["from"]), session_start.astimezone(timezone.utc))
        if (utc(t["to"]) - start) < timedelta(minutes=MIN_CHART_MINUTES):
            continue
        for leg in t["legs"]:
            if not leg.get("option_id") or leg.get("fill") is None:
                continue
            legs.append({"trade_id": t["trade_id"], "symbol": t["symbol"], "instrument_id": leg["option_id"],
                         "side": "short" if leg.get("side") == "sell" else "long", "strike": float(leg["strike"]),
                         "type": leg.get("type"), "fill": leg["fill"], "qty": int(t["qty"]),
                         "from_ts": iso(utc(t["from"])), "to_ts": iso(utc(t["to"])), "open": False})

    risk = pos.get("risk") or {}
    account = [{
        "account": "MCP account ending 3413", "as_of": pos.get("as_of"), "account_value": pos.get("account_value"),
        "buying_power": pos.get("buying_power"), "max_loss_open": risk.get("total_max_loss_usd"),
        "exit_reserves": risk.get("exit_reserves_usd"), "risk_used": risk.get("used_usd"),
        "risk_cap": risk.get("cap_usd"), "risk_free": risk.get("free_usd"), "open_positions": len(positions),
        "first_trade": trades[0]["date"] if trades else None, "trading_date": today,
        "stock_positions": "; ".join(stock) or None,
    }]
    check = {"closed_trades": sum(1 for t in trades if t["row_type"] == "Closed"),
             "closed_pnl": round(sum(t["pnl"] for t in trades if t["row_type"] == "Closed"), 2),
             "engine_closed": (metrics.get("outcomes") or {}).get("n"), "engine_pnl": (metrics.get("outcomes") or {}).get("total_pnl_usd")}
    return {"account": account, "positions": positions, "legs": legs, "trades": trades}, check


# ------------------------------------------------------------------ model.json

def build_model(repo, today):
    D = os.path.join(repo, "state", "earnings")
    # rule versions
    text = open(os.path.join(repo, "docs", "earnings", "RULES_CHANGELOG.md")).read()
    rules = []
    for m in re.finditer(r"^## (v[\d.]+) \((\d{4}-\d{2}-\d{2})[^)]*\)(?::\s*(.*))?$", text, re.M):
        rules.append({"version": m.group(1), "date": m.group(2), "title": clip(m.group(3) or "The first rule set", 120)})

    # proposals
    ev = jl(os.path.join(D, "proposals.jsonl"))
    props, order = {}, []
    for e in ev:
        pid = e.get("id")
        if e["event"] == "proposal":
            props[pid] = {"id": pid, "date": e.get("date") or e["ts"][:10], "title": clip(e.get("title"), 140), "type": e.get("type"),
                          "kind": e.get("kind"), "decider": e.get("decider"), "problem": clip(e.get("problem"), 380),
                          "change": clip(e.get("change"), 380), "measure": clip(e.get("measure"), 320),
                          "decision": None, "decided_by": None, "built": False, "verdict": None, "verdict_note": None}
            order.append(pid)
        elif pid in props and e["event"] == "decision":
            props[pid]["decision"], props[pid]["decided_by"] = e.get("decision"), e.get("by")
        elif pid in props and e["event"] == "implemented":
            props[pid]["built"] = True
        elif pid in props and e["event"] == "verified":
            props[pid]["verdict"], props[pid]["verdict_note"] = e.get("result"), clip(e.get("note"), 260)
    proposals = []
    for pid in order:
        p = props[pid]
        if p["verdict"]:
            state = "Closed"
        elif p["decision"] == "declined":
            state, p["verdict"] = "Closed", "declined"
        elif p["decision"] != "approved":
            state = "Waiting on you" if p["decider"] == "owner" else "Waiting on me"
        elif not p["built"]:
            state = "Approved, not built yet"
        else:
            state = "In force, being measured"
        dates = sorted(d for d in re.findall(r"20\d\d-\d\d-\d\d", p["measure"] or "") if d >= p["date"])
        p.update({"state": state, "review_date": dates[-1] if dates else None, "heal": p["type"] == "heal"})
        proposals.append(p)

    # lessons
    le = jl(os.path.join(D, "lessons.jsonl"))
    view = cli(repo, "lessons") or {}
    group = {}
    for g, label in (("apply_now", "In force"), ("being_tested", "Being tested"), ("awaiting_approval", "Waiting on you")):
        for x in view.get(g, []):
            group[x["id"]] = label
    tally, base = {}, {}
    for e in le:
        if e["event"] == "lesson":
            base[e["id"]] = e
        elif e["event"] == "evidence":
            t = tally.setdefault(e["id"], {"supports": 0, "contradicts": 0, "neutral": 0, "last": None})
            v = e.get("verdict")
            t[v if v in t else "neutral"] += 1
            t["last"] = e.get("date") or e["ts"][:10]
    lessons = []
    for lid, e in base.items():
        if lid not in group:
            continue
        t = tally.get(lid, {"supports": 0, "contradicts": 0, "neutral": 0, "last": None})
        lessons.append({"id": lid, "group": group[lid], "kind": e.get("kind"), "statement": clip(e.get("statement"), 460),
                        "since": e["ts"][:10], "supports": t["supports"], "contradicts": t["contradicts"], "neutral": t["neutral"],
                        "last_evidence": t["last"]})
    order_g = {"In force": 0, "Being tested": 1, "Waiting on you": 2}
    lessons.sort(key=lambda x: (order_g[x["group"]], x["id"]))

    # projections against results
    pr = jl(os.path.join(D, "projections.jsonl"))
    scores, done = [], set()
    actual_exit = {}
    for r in pr:
        if r.get("record") == "actual" and r.get("read") == "exit" and r.get("pnl_usd_after_fees") is not None:
            actual_exit[r["trade_id"]] = r
    for r in pr:
        if r.get("record") != "projection":
            continue
        tid = r["trade_id"]
        if r.get("stage") == "pre_report":
            a = (r.get("output") or {}).get("method_A_model") or {}
            act = actual_exit.get(tid)
            if tid.startswith("BOOK") or not a:
                continue
            scores.append({"trade_id": tid, "symbol": r["symbol"], "made": r["made_at"][:10], "method": "Before the report, with ranges",
                           "projected": a.get("mean"), "median": a.get("median"), "lo50": (a.get("band_50") or [None, None])[0],
                           "hi50": (a.get("band_50") or [None, None])[1], "lo80": (a.get("band_80") or [None, None])[0],
                           "hi80": (a.get("band_80") or [None, None])[1],
                           "actual": act["pnl_usd_after_fees"] if act else None, "status": "Closed" if act else "Still open"})
            done.add(tid)
    early = {}
    for r in pr:
        if r.get("record") == "projection" and r.get("stage") != "pre_report":
            tid = r["trade_id"]
            v = (r.get("output") or {}).get("base", {}).get("pnl_after_slippage_usd")
            if r.get("tranche") == "total":
                early[tid] = {"sym": r["symbol"], "made": r["made_at"][:10], "v": r.get("pnl_after_slippage_usd"), "total": True}
            elif v is not None and not early.get(tid, {}).get("total"):
                e = early.setdefault(tid, {"sym": r["symbol"], "made": r["made_at"][:10], "v": 0.0})
                e["v"] = round(e["v"] + v, 2)
    for tid, e in early.items():
        act = actual_exit.get(tid)
        scores.append({"trade_id": tid, "symbol": e["sym"], "made": e["made"], "method": "After the report, one number",
                       "projected": e["v"], "median": None, "lo50": None, "hi50": None, "lo80": None, "hi80": None,
                       "actual": act["pnl_usd_after_fees"] if act else None, "status": "Closed" if act else "Still open"})
    scores.sort(key=lambda s: (s["made"], s["trade_id"]))

    # replay evidence: the earnings fly by name cap
    evidence = []
    ft = os.path.join(D, "replay", "2026-11-11_batch2", "fly_table.json")
    if os.path.exists(ft):
        f = json.load(open(ft))
        for k, v in (f.get("cap_sweep") or {}).items():
            m = re.search(r"cap_(\d+|none)", k)
            if not m or not k.startswith("1.5x"):
                continue
            cap = m.group(1)
            evidence.append({"cap": "No cap" if cap == "none" else f"${cap}", "cap_usd": None if cap == "none" else int(cap),
                             "n": v.get("n"), "mean": v.get("mean"), "se": v.get("se"), "worst": v.get("worst"),
                             "events": f.get("clean_events"), "cost_share": f.get("cost_share")})
        # caps the stored table does not hold are priced by the repo's own script, into a temp file
        script = os.path.join(repo, "scripts", "earnings", "earnings_fly_table.py")
        have = {r["cap_usd"] for r in evidence}
        for cap in (600, 750):
            if cap in have or not os.path.exists(script):
                continue
            with tempfile.TemporaryDirectory() as td:
                outp = os.path.join(td, "table.json")
                subprocess.run([sys.executable, script, "--cap", str(cap), "--json", outp], cwd=repo, capture_output=True, text=True)
                if os.path.exists(outp):
                    v = json.load(open(outp))["capped"]["1.5"]["first"]["after_costs"]
                    evidence.append({"cap": f"${cap}", "cap_usd": cap, "n": v.get("n"), "mean": v.get("mean"), "se": v.get("se"),
                                     "worst": v.get("worst"), "events": f.get("clean_events"), "cost_share": f.get("cost_share")})
        evidence.sort(key=lambda r: (r["cap_usd"] is None, r["cap_usd"] or 0))

    # the same-day pilot and the paper desk
    st = (cli(repo, "intraday-status") or {})
    ps, lim = st.get("pilot") or {}, st.get("limits") or {}
    pilot = [{"probes_closed": ps.get("test_trades", ps.get("trades")), "your_override_trades": ps.get("override_trades", 0),
              "pnl_usd": ps.get("pnl_usd"), "paused": bool(ps.get("paused")), "loss_limit": lim.get("pilot_loss_limit"),
              "losses_in_a_row_limit": lim.get("losses_in_a_row"), "review_after": lim.get("review_after_trades"),
              "live": bool(st.get("live_enabled"))}]
    paper = {}
    names = {"intraday_0dte": "Same-day flies", "earnings_untraded": "Earnings names I skipped", "earnings_friday_entry": "Friday earnings entries",
             "non_earnings": "Other names", "earnings_early_entry": "Early earnings entries"}
    for r in jl(os.path.join(D, "live_metrics.jsonl")):
        if r.get("record") != "paper":
            continue
        g = paper.setdefault(r.get("kind"), {"test": names.get(r.get("kind"), r.get("kind")), "n": 0, "scored": 0, "pnl_mid": 0.0, "pnl_after_spreads": 0.0})
        g["n"] += 1
        if isinstance(r.get("pnl_mid_usd"), (int, float)):
            g["scored"] += 1
            g["pnl_mid"] += r["pnl_mid_usd"]
            g["pnl_after_spreads"] += r.get("pnl_natural_usd") or 0.0
    paper_rows = []
    for g in paper.values():
        g["pnl_mid"], g["pnl_after_spreads"] = round(g["pnl_mid"], 2), round(g["pnl_after_spreads"], 2)
        g["avg_after_spreads"] = round(g["pnl_after_spreads"] / g["scored"], 2) if g["scored"] else None
        paper_rows.append(g)
    paper_rows.sort(key=lambda g: -g["n"])

    # what is coming up
    pos = json.load(open(os.path.join(D, "positions.json")))
    upcoming = []
    for p in pos.get("open", []):
        rider = p.get("rider") or {}
        plan = p.get("plan") or {}
        if rider.get("close_today"):
            upcoming.append({"when": today, "sort": today + " 12:30", "what": f"{p['symbol']}: closing ticket to you at 12:30 PT, your hold", "who": "You"})
        elif p.get("kind") == "intraday_0dte":
            upcoming.append({"when": p.get("expiry"), "sort": f"{p.get('expiry')} 11:00", "what": f"{p['symbol']} same-day fly: out by 11:00 PT", "who": "Me"})
        else:
            m = re.search(r"(20\d\d-\d\d-\d\d)", str(plan.get("exit") or ""))
            when = m.group(1) if m else p.get("expiry")
            who = "You" if p.get("lane") == "owner_executed" or p.get("hand_entered") else "Me"
            upcoming.append({"when": when, "sort": f"{when} 06:40", "what": f"{p['symbol']}: close the morning after the report, about 06:40 PT", "who": who})
    for p in proposals:
        if p["state"] == "Approved, not built yet":
            m = re.search(r"20\d\d-\d\d-\d\d", p["change"] or "")
            upcoming.append({"when": m.group(0) if m else None, "sort": (m.group(0) if m else "9999") + " 00:00", "what": f"{p['id']}: {p['title']}", "who": "Me"})
        elif p["state"] == "In force, being measured" and p["review_date"] and p["review_date"] >= today:
            upcoming.append({"when": p["review_date"], "sort": p["review_date"] + " 23:00", "what": f"Review {p['id']}: {p['title']}", "who": "Me"})
    d = datetime.fromisoformat(today)
    sat = d + timedelta(days=(5 - d.weekday()) % 7 or 7)
    upcoming.append({"when": sat.strftime("%Y-%m-%d"), "sort": sat.strftime("%Y-%m-%d") + " 09:00",
                     "what": "Research day: the overnight fly test, a replay of the week's earnings reports, costs and spreads", "who": "Me"})
    upcoming.sort(key=lambda u: u["sort"])
    for u in upcoming:
        u.pop("sort")
    return {"rules": rules, "proposals": proposals, "lessons": lessons, "scores": scores, "evidence": evidence,
            "pilot": pilot, "paper": paper_rows, "upcoming": upcoming}


# ------------------------------------------------------------------ live args and output

BAR_RULES = {"from": {"pattern": "^[0-9]{4}-[01][0-9]-[0-3][0-9](T[0-2][0-9]:[0-5][0-9]:00Z)?$"}, "bar": {"enum": ["minute", "5minute"]}}
LIVE_DOCS = {
    "quotes": ("Live option quotes for the open legs", "Bid and ask for each option leg that is open, from Robinhood.", "get_option_quotes"),
    "spots": ("Live stock prices", "Last price and prior close for the stocks behind the open flies, plus SPY and IWM.", "get_equity_quotes"),
    "bars_a": ("Option price history, first half", "Price bars for half of the option legs open in this session. One call takes ten contracts, so the legs are split in two.", "get_option_historicals"),
    "bars_b": ("Option price history, second half", "Price bars for the other half of the option legs open in this session.", "get_option_historicals"),
}


def live_args(book, out_dir):
    """The ids and symbols the dashboard's four live calls use, and the store documents that hold them."""
    open_legs = [l for l in book["legs"] if l["open"]]
    quote_ids = sorted({l["instrument_id"] for l in open_legs})
    chart_ids = []
    for l in book["legs"]:                              # open flies first, then the ones closed today
        if l["instrument_id"] not in chart_ids:
            chart_ids.append(l["instrument_id"])
    notes = []
    if len(chart_ids) > 2 * MAX_IDS_PER_CALL:
        notes.append(f"{len(chart_ids) - 2 * MAX_IDS_PER_CALL} contracts are not charted: two calls of ten carry twenty")
        chart_ids = chart_ids[: 2 * MAX_IDS_PER_CALL]
    if len(quote_ids) > 20:
        notes.append("more than twenty open legs: the live quote call carries the first twenty")
    half = min(MAX_IDS_PER_CALL, (len(chart_ids) + 1) // 2)
    a, b = chart_ids[:half], chart_ids[half:]
    symbols = sorted({p["symbol"] for p in book["positions"]} | {"SPY", "IWM"})
    flat = not quote_ids
    args = {"spots": {"symbols": symbols}}
    if not flat:                                        # with nothing open the old documents stay; the page hides what reads them
        args["quotes"] = {"instrument_ids": quote_ids[:20]}
    if a:
        args["bars_a"] = {"instrument_ids": a, "start_time": "{{from}}", "interval": "{{bar}}"}
    if b:
        args["bars_b"] = {"instrument_ids": b, "start_time": "{{from}}", "interval": "{{bar}}"}
    store = os.path.join(out_dir, "store")
    os.makedirs(store, exist_ok=True)
    writes = []
    for doc_id, call_args in args.items():
        title, description, tool = LIVE_DOCS[doc_id]
        source = {"kind": "call", "connector": "Robinhood", "tool": tool, "args": call_args}
        if doc_id.startswith("bars"):
            source["rules"] = BAR_RULES
        path = os.path.join(store, f"datasets__{doc_id}.json")
        text = json.dumps({"title": title, "description": description, "source": source}, ensure_ascii=False)
        if not os.path.exists(path) or open(path).read() != text:
            with open(path, "w") as f:
                f.write(text)
        writes.append({"op": "set", "collection": "datasets", "doc_id": doc_id, "file_path": os.path.abspath(path)})
    return {"flat": flat, "quotes": quote_ids[:20], "spots": symbols, "bars_a": a, "bars_b": b, "notes": notes, "store_writes": writes}


def dump(obj):
    return json.dumps(obj, indent=1, sort_keys=False, ensure_ascii=False) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--today", default=None, help="trading date in Pacific time (default: the clock)")
    a = ap.parse_args()
    today = a.today or datetime.now(LA).strftime("%Y-%m-%d")
    os.makedirs(a.out, exist_ok=True)
    code = open(os.path.abspath(__file__)).read()
    book, check = build_book(a.repo, today)
    model = build_model(a.repo, today)
    args = live_args(book, a.out)
    book["chart"] = [{"bars_a": len(args["bars_a"]), "bars_b": len(args["bars_b"]), "flat": args["flat"], "trading_date": today}]
    book_meta = [{"label": "export.py", "value": code, "type": "code", "lang": "python"},
                 {"label": "Inputs", "value": "state/earnings/positions.json, journal.jsonl, live_metrics.jsonl; the engine's live-metrics command"},
                 {"label": "Trading date (Pacific)", "value": today}]
    model_meta = [{"label": "export.py", "value": code, "type": "code", "lang": "python"},
                  {"label": "Inputs", "value": "docs/earnings/RULES_CHANGELOG.md; state/earnings/proposals.jsonl, lessons.jsonl, projections.jsonl, "
                                               "live_metrics.jsonl, positions.json, replay/2026-11-11_batch2/fly_table.json; the engine's lessons and intraday-status commands"}]
    files = {"book.json": dump({"meta": book_meta, **book}), "model.json": dump({"meta": model_meta, **model}),
             "live_args.json": dump(args)}
    report = {}
    for name, text in files.items():
        path = os.path.join(a.out, name)
        old = open(path).read() if os.path.exists(path) else None
        report[name] = "new" if old is None else ("unchanged" if old == text else "CHANGED")
        if old != text:
            with open(path, "w") as f:
                f.write(text)
    print(json.dumps({
        "trading_date": today, "files": report,
        "sha256": {n: hashlib.sha256(t.encode()).hexdigest()[:12] for n, t in files.items()},
        "book": {"open_positions": len(book["positions"]), "legs": len(book["legs"]), "trade_rows": len(book["trades"]),
                 "realized_total": round(sum(t["pnl"] for t in book["trades"]), 2)},
        "check_against_engine": check,
        "model": {k: len(v) for k, v in model.items()},
        "live": {k: (len(v) if isinstance(v, list) else v) for k, v in args.items() if k != "store_writes"},
        "upload": [n for n in ("book.json", "model.json") if report[n] != "unchanged"],
        "live_documents_changed": report["live_args.json"] != "unchanged",
        "next": "upload each file under 'upload' as an asset, then one store batch: update datasets/<book|model> with the new url and "
                "updated.at, and, if live_documents_changed, the set writes listed in live_args.json (add if_version to each)",
    }, indent=1))


if __name__ == "__main__":
    main()
