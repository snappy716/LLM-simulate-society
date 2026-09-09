"""Observe real decision-time eligibility without changing any selected action."""
import json
from collections import Counter
from unittest.mock import patch
from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems import campus_relationship_anchors as anchors
from simulation.systems.campus_anomalies import _support_problem, _consents
from simulation.systems.campus_growth import mastery_by_topic

original = anchors.automatic_support_parameters
for seed in (42, 7):
    bridge = CampusKernelBridge(seed)
    stats = Counter()
    def observed(context, case, helper):
        state = context.state
        if _support_problem(state, case, helper) is None:
            stats["eligible_ordinary_supports"] += 1
            knowledge = mastery_by_topic(state, helper).get(case["topic_id"], 0) >= 40
            shared = bool(anchors.sources(state, case, helper))
            consent = _consents(state, case["actor_id"], helper, 65)
            stats["knowledge_40"] += int(knowledge)
            stats["real_shared_source"] += int(shared)
            stats["current_anchor_consent"] += int(consent)
            stats["all_three"] += int(knowledge and shared and consent)
        return original(context, case, helper)
    with patch.object(anchors, "automatic_support_parameters", observed):
        for index in range(28):
            state = bridge.kernel._state
            result = bridge.kernel.execute(SimulationCommand(f"anchor-opportunity:{index}", "player", "ADVANCE_PHASE", state.revision,
                issued_day=state.clock.day, issued_phase=state.clock.phase, issued_minute=state.clock.minute))
            assert result.success, result.code
    print(json.dumps({"seed": seed, "days": 7, "at_real_support_decision": dict(stats), "api_calls": bridge.kernel._state.cognition["usage"]["calls"]}), flush=True)
print("ANCHOR_OPPORTUNITY_AUDIT_OK observer_preserves_original_actions no_injection no_api")
