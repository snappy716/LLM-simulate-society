"""Read-only-to-user-data acceptance: isolated real multi-day shared history."""
from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_relationship_anchors import sources
from simulation.systems.campus_anomalies import anomalies_invariant
from tests.test_campus_relationship_anchors import prepare_anchor_fixture
from tests.test_campus_contact_inquiries import as_npc

bridge = CampusKernelBridge(42)
target, helper, cid, _ = prepare_anchor_fixture(bridge)
state = bridge.kernel._state
result = as_npc(bridge, helper, "SUPPORT_ANOMALY", {"npc_id": target, "case_id": cid, "expected_case_revision": 0})
assert result.success, result.code
for _ in range(4):
    result = as_npc(bridge, "player", "ADVANCE_PHASE", {})
    assert result.success, result.code
state = bridge.kernel._state
case = state.situations["campus_anomalies"]["cases"][cid]
assert "support:1" in [r["source_id"] for r in sources(state, case, helper)]
assert as_npc(bridge, helper, "ASK_ANOMALY_EXPERIENCE", {"npc_id": target}).success
result = as_npc(bridge, helper, "CONFIRM_RELATIONSHIP_ANCHOR", {"npc_id": target,
    "case_id": cid, "expected_case_revision": case["revision"], "source_id": "support:1"})
assert result.success, result.code
assert result.payload["anchor"]["source_id"] == "support:1"
assert result.payload["anchor"]["day"] == 3
assert not anomalies_invariant(bridge.kernel._state)
print("PREVIOUS_SUPPORT_ANCHOR_OK real_day2_support four_actual_phase_commands day3_voluntary_confirmation no_outcome_or_clock_injection explicit_initial_thresholds no_api")
