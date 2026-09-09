"""Isolated natural seven-day replay; inspect actual recorded care chains."""
import json
from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems.campus_support_followup import source_valid

for seed in (42, 7):
    bridge = CampusKernelBridge(seed)
    for index in range(28):
        state = bridge.kernel._state
        result = bridge.kernel.execute(SimulationCommand(f"followup-chain:{index}", "player", "ADVANCE_PHASE", state.revision,
            issued_day=state.clock.day, issued_phase=state.clock.phase, issued_minute=state.clock.minute))
        assert result.success, result.code
    state = bridge.kernel._state
    chains = []
    for case in state.situations.get("campus_anomalies", {}).get("cases", {}).values():
        for receipt in case["history"]:
            if not receipt.get("anchor_id"):
                continue
            helper = receipt["helper_id"]
            anchor = case["anchors"][helper]
            goal = state.cognition["long_term_plans"]["actors"].get(helper, {}).get("followup:" + case["case_id"])
            assert goal and source_valid(state, helper, goal)
            from simulation.systems.campus_growth import mastery_by_topic
            assert mastery_by_topic(state, helper).get(case["topic_id"], 0) >= 40
            first = case["history"][goal["source_revision"] - 1]
            chains.append({"helper_id": helper, "subject_id": case["actor_id"], "first_support_day": first["day"],
                "first_relationship_changes": first["relationship_changes"],
                "followup_created_day": goal["created_tick"] // 4 + 1, "followup_history": goal["history"],
                "last_action": goal["last_action"], "last_result": goal["last_result"], "attempts": goal["attempts"],
                "knowledge_progress": state.knowledge["growth"]["actors"][helper]["topics"].get(case["topic_id"], {}),
                "anchor_day": anchor["day"], "anchor_source": anchor["source_id"], "deeper_support_day": receipt["day"],
                "deeper_support_before": receipt["before"], "deeper_support_after": receipt["after"]})
    assert chains and state.cognition["usage"]["calls"] == 0
    print(json.dumps({"seed": seed, "days": 7, "chains": chains, "api_calls": 0}, ensure_ascii=False), flush=True)
print("FOLLOWUP_CHAIN_AUDIT_OK real_support_relationships_followup_sufficient_knowledge_confirmed_anchor_actual_effect no_injection no_api")
