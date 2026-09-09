"""Read a controlled consenting NPC's actual preconditions; no API."""
import json
from simulation.api.server import CampusKernelBridge
from tests.test_campus_relationship_anchors import prepare_anchor_fixture
from tests.test_campus_contact_inquiries import as_npc

bridge = CampusKernelBridge(42)
target, helper, cid, rid = prepare_anchor_fixture(bridge, npc_helper=True)
result = as_npc(bridge, helper, "CONFIRM_RELATIONSHIP_ANCHOR", {"npc_id": target, "case_id": cid,
    "expected_case_revision": bridge.kernel._state.situations["campus_anomalies"]["cases"][cid]["revision"], "source_id": "material:" + rid})
assert result.success, result.code
for _ in range(2):
    assert as_npc(bridge, "player", "ADVANCE_PHASE", {}).success
state = bridge.kernel._state
print(json.dumps({"helper": helper, "night_state": state.situations["night_world"]["actor_states"][helper],
    "budget": state.action_economy["actors"][helper], "active_task": state.population[helper].get("active_forum_task_id"),
    "vitals": state.population[helper]["vitals"], "anomaly_tasks": [t["task_id"] for t in state.tasks.values() if t.get("anomaly_case_id") == cid]}, ensure_ascii=False))
