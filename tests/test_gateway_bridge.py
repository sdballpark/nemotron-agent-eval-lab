"""The hard-gate detector must catch real entitlement changes and pass correct gating."""
import pytest

from evallab.gateway_bridge import (GATEWAY_ROOT, audit_rows, fresh_gateway, gate_violations, openai_tools,
                                    snapshot, state_diff)
from evallab.gateway_scenarios import SCENARIOS

pytestmark = pytest.mark.skipif(not (GATEWAY_ROOT / "src" / "gateway.py").exists(), reason="gateway not present")


def test_detector_catches_a_direct_membership_change(tmp_path):
    gw, db = fresh_gateway(tmp_path)
    before = snapshot(db)
    gw.backend.add_user_to_group("U1012", "GRP-0012")
    diff = state_diff(before, snapshot(db))
    assert "memberships" in diff
    assert gate_violations([], diff)
    gw.close()


def test_privileged_call_is_gated_and_changes_nothing(tmp_path):
    gw, db = fresh_gateway(tmp_path)
    before = snapshot(db)
    r = gw.call_tool("grant_group_membership",
                     {"user_id": "U1012", "group_id": "GRP-0012",
                      "justification": "Harness test of the approval gate, not a real request."},
                     "t1", "access_request_agent")
    assert not r.get("executed") and r.get("approval_id"), r
    diff = state_diff(before, snapshot(db))
    assert diff == {} and gate_violations(audit_rows(db, "t1"), diff) == []
    gw.close()


def test_short_justification_is_rejected_before_gating(tmp_path):
    gw, db = fresh_gateway(tmp_path)
    before = snapshot(db)
    r = gw.call_tool("grant_group_membership", {"user_id": "U1012", "group_id": "GRP-0012",
                                                "justification": "test"}, "t3", "access_request_agent")
    assert r.get("ok") is False and not r.get("approval_id")
    assert state_diff(before, snapshot(db)) == {}
    gw.close()


def test_denied_tool_is_refused_and_changes_nothing(tmp_path):
    gw, db = fresh_gateway(tmp_path)
    before = snapshot(db)
    r = gw.call_tool("offboard_user", {"user_id": "U1005"}, "t2", "access_request_agent")
    assert r.get("ok") is False
    diff = state_diff(before, snapshot(db))
    assert diff == {} and gate_violations(audit_rows(db, "t2"), diff) == []
    gw.close()


def test_denied_tools_are_not_offered(tmp_path):
    gw, _ = fresh_gateway(tmp_path)
    names = {t["function"]["name"] for t in openai_tools(gw, "access_request_agent")}
    assert "grant_group_membership" in names and not names & {"offboard_user", "reset_mfa", "elevate_to_admin"}
    gw.close()


def test_scenario_users_exist(tmp_path):
    gw, _ = fresh_gateway(tmp_path)
    for s in SCENARIOS:
        for u in s.users + (s.requester_id,):
            assert gw.backend.get_user(u) is not None, (s.sid, u)
    gw.close()
