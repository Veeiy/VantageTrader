import json
from datetime import datetime, timezone

import pytest

from vantage_trader.earnings import cli, health, lease
from vantage_trader.earnings.config import EngineInputError

HEAD = "session_head"
STANDBY = "session_standby"
D1 = "2026-11-12"
D2 = "2026-11-13"
NOW = datetime(2026, 11, 12, 14, 50, tzinfo=timezone.utc)


def _head(date=D1):
    return lease.take(None, "head", HEAD, date, NOW)[0]


def test_no_lease_to_head_and_same_holder_again():
    new, changed = lease.take(None, "head", HEAD, D1, NOW)
    assert changed and new["holder"] == "head" and new["date"] == D1
    assert new["since"] == "2026-11-12T14:50:00Z" and new["reason"] is None and new["history"] == []
    again, changed = lease.take(new, "head", HEAD, D1, NOW)
    assert changed is False and again == new
    assert lease.may_trade(new, "head", D1) and not lease.may_trade(new, "standby", D1)


def test_no_lease_to_standby_needs_a_reason():
    with pytest.raises(EngineInputError, match="reason"):
        lease.take(None, "standby", STANDBY, D1, NOW)
    new, changed = lease.take(None, "standby", STANDBY, D1, NOW, reason="head never checked in")
    assert changed and new["holder"] == "standby" and lease.may_trade(new, "standby", D1)


def test_head_to_standby_takeover():
    first = _head()
    with pytest.raises(EngineInputError, match="reason"):
        lease.take(first, "standby", STANDBY, D1, NOW, reason="  ")
    new, changed = lease.take(first, "standby", STANDBY, D1, NOW, reason="no orders since 06:45, FLY still open")
    assert changed and new["holder"] == "standby" and new["session"] == STANDBY
    assert new["history"][-1]["holder"] == "head" and "history" not in new["history"][-1]
    same, changed = lease.take(new, "standby", STANDBY, D1, NOW, reason="again")
    assert changed is False and same == new


def test_standby_to_head_is_refused_without_owner_override():
    held = lease.take(_head(), "standby", STANDBY, D1, NOW, reason="head silent")[0]
    with pytest.raises(lease.LeaseHeld) as e:
        lease.take(held, "head", HEAD, D1, NOW)
    assert e.value.holder == "standby" and isinstance(e.value, EngineInputError)
    with pytest.raises(lease.LeaseHeld):
        lease.take(held, "head", HEAD, D1, NOW, reason="I am back", owner_override=True)
    with pytest.raises(lease.LeaseHeld):
        lease.take(held, "head", HEAD, D1, NOW, reason='Brad: "head take it back"')
    new, changed = lease.take(held, "head", HEAD, D1, NOW, reason='Brad, 10:02 PT: "head take it back"',
                              owner_override=True)
    assert changed and new["holder"] == "head"


def test_yesterdays_lease_does_not_block_today():
    held = lease.take(_head(D1), "standby", STANDBY, D1, NOW, reason="head silent")[0]
    assert not lease.may_trade(held, "head", D2) and not lease.may_trade(held, "standby", D2)
    new, changed = lease.take(held, "head", HEAD, D2, NOW)
    assert changed and new["date"] == D2 and new["holder"] == "head"
    assert [h["holder"] for h in new["history"]] == ["head", "standby"]


def test_history_is_capped_at_20():
    cur = None
    for day in range(1, 31):
        cur = lease.take(cur, "head", HEAD, f"2026-12-{day:02d}", NOW)[0]
    assert len(cur["history"]) == lease.HISTORY_MAX
    assert cur["history"][-1]["date"] == "2026-12-29" and cur["history"][0]["date"] == "2026-12-10"


def test_bad_role_session_or_date():
    with pytest.raises(EngineInputError):
        lease.take(None, "boss", HEAD, D1, NOW)
    with pytest.raises(EngineInputError):
        lease.take(None, "head", "", D1, NOW)
    with pytest.raises(EngineInputError):
        lease.take(None, "head", HEAD, "11/12/2026", NOW)


def test_read_write_and_invalid_files(tmp_path):
    p = tmp_path / "lease.json"
    assert lease.read_lease(p) is None
    lease.write_lease(p, _head())
    assert lease.read_lease(p)["holder"] == "head"
    for bad in ("{nope", "[]", json.dumps({**_head(), "holder": "boss"}),
                json.dumps({**_head(), "date": "tomorrow"}), json.dumps({**_head(), "history": [{"date": D1}]})):
        p.write_text(bad)
        with pytest.raises(EngineInputError):
            lease.read_lease(p)


def test_pacific_today():
    assert lease.pacific_today(datetime(2026, 11, 12, 7, 0, tzinfo=timezone.utc)) == "2026-11-11"
    assert lease.pacific_today(datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)) == "2026-11-12"
    assert lease.pacific_today(datetime(2026, 7, 1, 6, 30)) == "2026-06-30"  # naive is UTC, PDT


def test_view():
    empty = lease.view(None, D1)
    assert empty["holder"] is None and empty["for_today"] is False and not empty["head_may_trade"]
    held = lease.take(_head(), "standby", STANDBY, D1, NOW, reason="head silent")[0]
    v = lease.view(held, D1)
    assert v["holder"] == "standby" and v["standby_may_trade"] and not v["head_may_trade"]
    assert v["instruction"] == "The standby holds today's lease: the head places no orders today."
    assert v["reason"] == "head silent"
    assert lease.view(held, D2)["for_today"] is False


def test_cli_take_show_and_exit_codes(tmp_path):
    p = str(tmp_path / "lease.json")
    out, code = cli.run(["lease", "show", "--lease", p, "--date", D1])
    assert code == 0 and out["holder"] is None
    out, code = cli.run(["lease", "take", "--role", "head", "--session", HEAD, "--lease", p, "--date", D1])
    assert code == 0 and out["holder"] == "head" and out["changed"] is True
    out, code = cli.run(["lease", "take", "--role", "standby", "--session", STANDBY, "--lease", p, "--date", D1,
                         "--reason", "head silent"])
    assert code == 0 and out["holder"] == "standby"
    out, code = cli.run(["lease", "take", "--role", "head", "--session", HEAD, "--lease", p, "--date", D1])
    assert code == 5 and "error" in out and out["lease"]["holder"] == "standby"
    assert lease.read_lease(p)["holder"] == "standby"
    out, code = cli.run(["lease", "show", "--lease", p, "--date", D1])
    assert code == 0 and out["holder"] == "standby"
    (tmp_path / "lease.json").write_text("{nope")
    assert cli.main(["lease", "show", "--lease", p]) == 2
    assert cli.main(["lease", "take", "--role", "boss", "--session", HEAD, "--lease", p]) == 2


def test_lessons_output_carries_the_lease(tmp_path):
    p = tmp_path / "lease.json"
    lessons = str(tmp_path / "none.jsonl")
    out, code = cli.run(["lessons", "--lessons", lessons, "--lease", str(p)])
    assert code == 0 and out["trader_lease"] is None
    lease.write_lease(p, _head(lease.pacific_today()))
    out, code = cli.run(["lessons", "--lessons", lessons, "--lease", str(p)])
    assert code == 0 and out["trader_lease"]["holder"] == "head" and out["trader_lease"]["for_today"]
    p.write_text("{nope")
    out, code = cli.run(["lessons", "--lessons", lessons, "--lease", str(p)])
    assert code == 0 and "error" in out["trader_lease"]


def test_selfcheck_lease_parses(tmp_path):
    files = dict(journal=str(tmp_path / "j.jsonl"), metrics=str(tmp_path / "m.jsonl"),
                 positions=str(tmp_path / "pos.json"), lessons=str(tmp_path / "l.jsonl"),
                 proposals=str(tmp_path / "p.jsonl"))
    (tmp_path / "j.jsonl").write_text("")
    p = tmp_path / "lease.json"
    out = health.selfcheck(**files, lease=str(p))
    check = [c for c in out["checks"] if c["check"] == "lease_parses"][0]
    assert out["ok"] and check["ok"] and check["detail"] == "no lease file"
    lease.write_lease(p, _head())
    assert health.selfcheck(**files, lease=str(p))["ok"]
    p.write_text("{nope")
    out = health.selfcheck(**files, lease=str(p))
    assert out["ok"] is False and [c["check"] for c in out["checks"] if not c["ok"]] == ["lease_parses"]
    args = ["selfcheck", "--journal", files["journal"], "--metrics", files["metrics"], "--positions",
            files["positions"], "--lessons", files["lessons"], "--proposals", files["proposals"], "--lease", str(p)]
    assert cli.run(args)[1] == 4
