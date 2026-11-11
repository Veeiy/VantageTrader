import json

import pytest

from vantage_trader.earnings import cli, health, proposals
from vantage_trader.earnings.config import EngineInputError


def _write(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _prop(pid, kind="tooling", decider="agent", typ="heal"):
    return {"event": "proposal", "id": pid, "date": "2026-11-10", "type": typ, "kind": kind, "title": "t",
            "problem": "p", "change": "c", "measure": "m", "decider": decider}


def test_owner_kinds_need_the_owner(tmp_path):
    with pytest.raises(EngineInputError, match="owner's decision"):
        proposals.read_proposals(_write(tmp_path, "a.jsonl", [_prop("P1", kind="risk", decider="agent")]))
    rows = [_prop("P1", kind="rule", decider="owner"),
            {"event": "decision", "id": "P1", "decision": "approved", "by": "agent"}]
    with pytest.raises(EngineInputError, match="only be approved by the owner"):
        proposals.read_proposals(_write(tmp_path, "b.jsonl", rows))


def test_order_of_events_is_enforced(tmp_path):
    with pytest.raises(EngineInputError, match="before it is approved"):
        proposals.read_proposals(_write(tmp_path, "a.jsonl", [_prop("P1"), {"event": "implemented", "id": "P1"}]))
    rows = [_prop("P1"), {"event": "decision", "id": "P1", "decision": "approved", "by": "agent"},
            {"event": "verified", "id": "P1", "result": "worked"}]
    with pytest.raises(EngineInputError, match="before it is implemented"):
        proposals.read_proposals(_write(tmp_path, "b.jsonl", rows))
    rows = [_prop("P1", kind="cost", decider="owner"),
            {"event": "decision", "id": "P1", "decision": "declined", "by": "Brad"},
            {"event": "implemented", "id": "P1"}]
    with pytest.raises(EngineInputError, match="before it is approved"):
        proposals.read_proposals(_write(tmp_path, "c.jsonl", rows))


def test_view_groups_by_status(tmp_path):
    rows = [
        _prop("P1"), {"event": "decision", "id": "P1", "decision": "approved", "by": "agent"},
        {"event": "implemented", "id": "P1", "ref": "abc123"},
        _prop("P2", kind="risk", decider="owner"),
        _prop("P3", kind="cost", decider="owner"), {"event": "decision", "id": "P3", "decision": "approved", "by": "Brad 11/11"},
        _prop("P4"), {"event": "decision", "id": "P4", "decision": "approved", "by": "agent"},
        {"event": "implemented", "id": "P4", "ref": "def456"}, {"event": "verified", "id": "P4", "result": "worked"},
        _prop("P5", kind="rule", decider="owner"), {"event": "decision", "id": "P5", "decision": "deferred", "by": "Brad"},
        _prop("P6", kind="rule", decider="owner"), {"event": "decision", "id": "P6", "decision": "declined", "by": "Brad"},
    ]
    view = proposals.proposals_view(proposals.read_proposals(_write(tmp_path, "a.jsonl", rows)))
    assert [r["id"] for r in view["awaiting_owner"]] == ["P2", "P5"]
    assert [r["id"] for r in view["approved_not_implemented"]] == ["P3"]
    assert [(r["id"], r["ref"]) for r in view["implemented_not_verified"]] == [("P1", "abc123")]
    assert view["closed"] == {"declined": 1, "worked": 1, "did_not_work": 0, "inconclusive": 0}
    out, code = cli.run(["proposals", "--proposals", str(tmp_path / "a.jsonl")])
    assert code == 0 and len(out["awaiting_owner"]) == 2


def _files(tmp_path, qty_journal=1, qty_book=1, cap=650, with_exit=False):
    base = {"order_id": None, "implied_move": None, "edge_ratio": None, "realized_move": None, "pnl": None, "notes": ""}
    j = [{**base, "ts": "2026-11-10T19:42:34Z", "event": "entry_filled", "symbol": "AAA", "structure": "iron_fly",
          "price": 1.28, "quantity": qty_journal, "direction": "credit"}]
    m = [{"trade_id": "AAA-1", "record": "entry", "ts": "2026-11-10T19:42:34Z", "symbol": "AAA", "live": True}]
    if with_exit:
        m.append({"trade_id": "AAA-1", "record": "exit", "ts": "2026-11-11T14:50:00Z", "symbol": "AAA", "live": True})
    pos = {"open": [{"symbol": "AAA", "quantity": qty_book, "max_loss_usd": 172}],
           "risk": {"total_max_loss_usd": 172, "exit_reserves_usd": 50, "cap_usd": cap}}
    (tmp_path / "positions.json").write_text(json.dumps(pos))
    return dict(journal=str(_write(tmp_path, "journal.jsonl", j)), metrics=str(_write(tmp_path, "metrics.jsonl", m)),
                positions=str(tmp_path / "positions.json"), lessons=str(tmp_path / "none-l.jsonl"),
                proposals=str(tmp_path / "none-p.jsonl"))


def test_selfcheck_passes_when_files_agree(tmp_path):
    out = health.selfcheck(**_files(tmp_path))
    assert out["ok"] is True and {c["check"] for c in out["checks"]} >= {
        "journal_parses", "positions_match_journal", "metrics_match_positions", "risk_within_cap"}


def test_selfcheck_catches_drift(tmp_path):
    bad_qty = health.selfcheck(**_files(tmp_path, qty_journal=2, qty_book=1))
    assert bad_qty["ok"] is False
    assert [c["check"] for c in bad_qty["checks"] if not c["ok"]] == ["positions_match_journal"]
    over_cap = health.selfcheck(**_files(tmp_path, cap=200))
    assert [c["check"] for c in over_cap["checks"] if not c["ok"]] == ["risk_within_cap"]
    exited = health.selfcheck(**_files(tmp_path, with_exit=True))
    assert [c["check"] for c in exited["checks"] if not c["ok"]] == ["metrics_match_positions"]


def test_selfcheck_reports_a_broken_ledger_and_exit_code(tmp_path):
    f = _files(tmp_path)
    (tmp_path / "bad.jsonl").write_text("{nope}\n")
    f["lessons"] = str(tmp_path / "bad.jsonl")
    out = health.selfcheck(**f)
    assert out["ok"] is False and [c["check"] for c in out["checks"] if not c["ok"]] == ["lessons_parse"]
    args = ["selfcheck", "--journal", f["journal"], "--metrics", f["metrics"], "--positions", f["positions"],
            "--lessons", f["lessons"], "--proposals", f["proposals"]]
    assert cli.run(args)[1] == 4
    args[args.index("--lessons") + 1] = str(tmp_path / "none-l.jsonl")
    assert cli.run(args)[1] == 0


def test_standing_delegation_lets_the_agent_approve_owner_kinds_inside_its_scope(tmp_path):
    """Brad, 2026-11-11: "you have owners permission to automate" (RULES_CHANGELOG, Delegation)."""
    by = "agent, under Brad's standing delegation of 2026-11-11: \"you have owners permission to automate\""
    ok = [_prop("P1", kind="rule", decider="owner"),
          {"event": "decision", "id": "P1", "decision": "approved", "by": by, "ts": "2026-11-12T16:00:00Z"},
          {"event": "implemented", "id": "P1"}]
    assert len(proposals.read_proposals(_write(tmp_path, "ok.jsonl", ok))) == 3
    # a decision dated before the delegation does not count
    early = [_prop("P1", kind="rule", decider="owner"),
             {"event": "decision", "id": "P1", "decision": "approved", "by": by, "ts": "2026-11-10T16:00:00Z"}]
    with pytest.raises(EngineInputError, match="only be approved by the owner"):
        proposals.read_proposals(_write(tmp_path, "early.jsonl", early))
    # no timestamp, or no mention of the delegation: still the owner's
    for row in ({"event": "decision", "id": "P1", "decision": "approved", "by": by},
                {"event": "decision", "id": "P1", "decision": "approved", "by": "agent", "ts": "2026-11-12T16:00:00Z"}):
        with pytest.raises(EngineInputError, match="only be approved by the owner"):
            proposals.read_proposals(_write(tmp_path, "x.jsonl", [_prop("P1", kind="risk", decider="owner"), row]))
    # outside the delegation's scope: the proposal is flagged and needs Brad himself
    flagged = dict(_prop("P1", kind="risk", decider="owner"), needs_owner=True)
    with pytest.raises(EngineInputError, match="only be approved by the owner"):
        proposals.read_proposals(_write(tmp_path, "f.jsonl", [flagged, {"event": "decision", "id": "P1",
                                 "decision": "approved", "by": by, "ts": "2026-11-12T16:00:00Z"}]))
    brad = [flagged, {"event": "decision", "id": "P1", "decision": "approved", "by": "Brad, 2026-11-12: \"yes\""}]
    assert len(proposals.read_proposals(_write(tmp_path, "b.jsonl", brad))) == 2
    assert proposals.under_delegation(by, "2026-11-11T16:13:00Z") and not proposals.under_delegation(by, "")
