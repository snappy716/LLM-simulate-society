from collections import Counter
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems.transactions import TransactionContext
from simulation.systems import DeterministicRngPool, load_campus_activity_definitions, load_campus_decision_policy
from simulation.systems.campus_support_followup import source_valid, relationship_receipt_valid
from simulation.systems.campus_goals import goal_candidates, goal_step, personal_goals_invariant, record_goal_outcome
from simulation.systems.campus_anomalies import anomalies_invariant
from simulation.systems.campus_growth import mastery_by_topic, _actor_growth, _topic_progress
from simulation.systems.campus_messaging import load_campus_messaging_policy
from simulation.systems.campus_support_preparation import advance_support_preparations
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_support_preparation import prepare_support_fixture
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_combat_deployment import travel_to_location


def prepare_supported_pair(bridge, near_cap=False):
    target, helper, cid = prepare_support_fixture(bridge)
    state = bridge.kernel._state
    case = state.situations["campus_anomalies"]["cases"][cid]
    # Explicit first-support knowledge and willingness. No later knowledge or
    # completion is injected; support and its relationship effects are real.
    _topic_progress(_actor_growth(state, helper), case["topic_id"])["theory"] = 20
    state.population[helper]["personality"]["risk_tolerance"] = 60
    if near_cap:
        for owner, other in ((target, helper), (helper, target)):
            state.relationships[owner][other].update(trust=99, closeness=99, respect=99)
    travel_to_location(bridge, state.population[target]["current_location_id"], helper)
    result = as_npc(bridge, helper, "SUPPORT_ANOMALY", {"npc_id": target, "case_id": cid, "expected_case_revision": case["revision"]})
    assert result.success, result.code
    return target, helper, cid


def next_dawn(bridge):
    for _ in range(4):
        result = as_npc(bridge, "player", "ADVANCE_PHASE", {})
        assert result.success, result.code


def prepare_followup_fixture(bridge):
    target, helper, cid = prepare_supported_pair(bridge)
    # Preserve a genuine protected-duty boundary so the new goal does not
    # acquire knowledge in this fixture before its inspector is tested.
    for who in (helper, target):
        bridge.kernel._state.population[who]["weekly_schedule"]["2"]["morning"]["priority"] = 95
    next_dawn(bridge)
    assert "followup:" + cid in bridge.kernel._state.cognition["long_term_plans"]["actors"][helper]
    return target, helper, cid


class SupportFollowupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.target, cls.helper, cls.cid = prepare_followup_fixture(cls.bridge)
        cls.initial, cls.rng = cls.bridge.kernel.capture_checkpoint()
        cls.defs = load_campus_activity_definitions(cls.bridge.registry)
        cls.policy = load_campus_decision_policy(cls.bridge.registry, cls.defs, cls.bridge.location_graph)
        cls.phone_policy = load_campus_messaging_policy(cls.bridge.registry)

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.bridge.cognition_runtime.configure_rule()

    @property
    def state(self): return self.bridge.kernel._state

    @property
    def case(self): return self.state.situations["campus_anomalies"]["cases"][self.cid]

    @property
    def goal(self): return self.state.cognition["long_term_plans"]["actors"][self.helper]["followup:" + self.cid]

    def context(self):
        return TransactionContext(self.state, DeterministicRngPool(42), SimulationCommand("followup-test", "player", "ADVANCE_PHASE", self.state.revision))

    def candidates(self, priority=20):
        return goal_candidates(self.context(), self.helper, {"activity_id": "SELF_STUDY", "location_id": self.state.population[self.helper]["home_location_id"], "priority": priority},
            self.bridge.location_graph, Counter(), self.policy, self.defs, 40)

    def test_actual_support_receipt_has_capped_bilateral_relationship_effect(self):
        receipt = self.case["history"][0]
        self.assertTrue(relationship_receipt_valid(self.case, receipt))
        self.assertEqual({"trust": 8, "closeness": 4, "respect": 3}, receipt["relationship_changes"]["subject"]["applied"])
        self.assertEqual({"trust": 2, "closeness": 3, "respect": 1}, receipt["relationship_changes"]["helper"]["applied"])
        self.assertNotIn("obligation", receipt["relationship_changes"]["subject"]["applied"])
        self.assertEqual([], anomalies_invariant(self.state))

    def test_real_relationship_gain_caps_and_rejected_repeat_does_not_reward(self):
        bridge = CampusKernelBridge(42)
        target, helper, cid = prepare_supported_pair(bridge, near_cap=True)
        case = bridge.kernel._state.situations["campus_anomalies"]["cases"][cid]
        self.assertEqual({"trust": 1, "closeness": 1, "respect": 1}, case["history"][0]["relationship_changes"]["subject"]["applied"])
        before = deepcopy(bridge.kernel._state.relationships)
        result = as_npc(bridge, helper, "SUPPORT_ANOMALY", {"npc_id": target, "case_id": cid, "expected_case_revision": case["revision"]})
        self.assertEqual("support_today_complete", result.code)
        self.assertEqual(before, bridge.kernel._state.relationships)

    def test_followup_is_not_complete_after_only_one_support_or_readiness(self):
        self.goal["status"] = "completed"
        self.assertIn("personal goal falsely completed", personal_goals_invariant(self.state))
        self.assertEqual("unknown_personal_episode", as_npc(self.bridge, self.helper, "ASK_ANOMALY_EXPERIENCE", {"npc_id": self.target, "case_id": "not-this-person"}).code)

    def test_goal_requires_own_past_support_and_not_fake_case_experience(self):
        self.assertTrue(source_valid(self.state, self.helper, self.goal))
        self.assertEqual("support_followup", self.goal["kind"])
        self.assertEqual(3, self.state.clock.day)
        self.assertEqual(20, mastery_by_topic(self.state, self.helper)[self.goal["topic_id"]])
        # The NPC may really fight during the four normal phase advances. Those
        # valid experiences stay; the care goal must not invent a battle case.
        cases = self.state.knowledge.get("growth", {}).get("actors", {}).get(self.helper, {}).get("case_records", {})
        for record in cases.values():
            self.assertIn(self.helper, self.state.battles[record["battle_id"]]["participant_ids"])
        self.assertTrue(set(self.goal["source_ids"]).isdisjoint(cases))
        self.assertNotIn("player", self.state.cognition["long_term_plans"]["actors"])
        self.assertEqual("completed", self.state.cognition["long_term_plans"]["actors"][self.helper]["support:" + self.cid]["status"])
        self.assertEqual([], personal_goals_invariant(self.state))

    def test_ordinary_intraday_execution_does_not_create_followup_or_grant_knowledge(self):
        bridge = CampusKernelBridge(42)
        target, helper, cid = prepare_supported_pair(bridge)
        self.assertNotIn("followup:" + cid, bridge.kernel._state.cognition["long_term_plans"]["actors"][helper])
        result = as_npc(bridge, "player", "ADVANCE_PHASE", {})
        self.assertTrue(result.success, result.code)
        self.assertNotIn("followup:" + cid, bridge.kernel._state.cognition["long_term_plans"]["actors"][helper])

    def test_dawn_repeated_call_does_not_repeat_messages_or_create_goals(self):
        before = deepcopy((self.state.cognition, self.state.relationships, self.state.action_economy))
        advance_support_preparations(self.context(), self.bridge.location_graph, self.phone_policy)
        self.assertEqual(before, (self.state.cognition, self.state.relationships, self.state.action_economy))

    def test_protected_work_and_changed_willingness_keep_goal_but_block_study(self):
        self.assertEqual([], self.candidates(priority=95))
        self.state.relationships[self.helper][self.target]["trust"] = 0
        self.assertEqual([], self.candidates())
        self.assertEqual("blocked", self.goal["status"])
        self.assertEqual(20, mastery_by_topic(self.state, self.helper)[self.goal["topic_id"]])

    def test_actual_followup_reading_costs_action_not_instant_appointment(self):
        # Explicit spare-action/free-slot boundary after the protected morning.
        self.state.action_economy["actors"][self.helper]["major_remaining"] = 1
        self.state.population[self.helper]["needs"].update(rest=0, food=0, safety=0)
        candidate = next(c for c in self.candidates() if c["personal_goal_id"] == self.goal["goal_id"])
        self.assertEqual("READ_KNOWLEDGE", candidate["activity_id"])
        before = deepcopy((self.state.situations, self.state.clock))
        travel_to_location(self.bridge, candidate["location_id"], self.helper)
        result = as_npc(self.bridge, self.helper, candidate["activity_id"], candidate["parameters"])
        self.assertTrue(result.success, result.code)
        record_goal_outcome(self.context(), self.helper, candidate, result)
        self.assertEqual(40, mastery_by_topic(self.state, self.helper)[self.goal["topic_id"]])
        self.assertEqual(0, self.state.action_economy["actors"][self.helper]["major_remaining"])
        self.assertEqual(before, (self.state.situations, self.state.clock))
        self.assertNotEqual("completed", self.goal["status"])

    def test_old_history_does_not_gain_retroactive_relationships_or_goals(self):
        bridge = CampusKernelBridge(42)
        _, helper, cid = prepare_supported_pair(bridge)
        state = bridge.kernel._state
        state.situations["campus_anomalies"]["cases"][cid]["history"][0].pop("relationship_changes")
        self.assertEqual([], anomalies_invariant(state))
        # No retroactive seeding from an older receipt, even when reviewed later.
        next_dawn(bridge)
        goals = bridge.kernel._state.cognition["long_term_plans"]["actors"][helper]
        self.assertNotIn("followup:" + cid, goals)

    def test_current_refusal_blocks_followup_until_next_dawn(self):
        self.state.relationships[self.target][self.helper]["trust"] = 0
        next_dawn(self.bridge)
        self.assertEqual("check_in", goal_step(self.state, self.helper, self.goal))
        self.assertEqual("blocked", self.goal["status"])
        self.assertEqual([], self.candidates())

    def test_checkpoint_and_source_or_relationship_corruption_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "followup.json"
            save_kernel_checkpoint(path, self.state, DeterministicRngPool(42))
            restored = load_kernel_checkpoint(path).state
            self.assertEqual([], personal_goals_invariant(restored))
            restored.cognition["long_term_plans"]["actors"][self.helper][self.goal["goal_id"]]["source_revision"] = 999
            self.assertIn("support followup lacks actual shared source", personal_goals_invariant(restored))
        self.case["history"][0]["relationship_changes"]["subject"]["after"]["trust"] = 1000
        self.assertIn("invalid support relationship receipt", anomalies_invariant(self.state))

    def test_private_model_context_and_volunteered_plan_are_not_worldwide(self):
        from simulation.systems.campus_goals import own_goal_context
        own = own_goal_context(self.state, self.helper)
        self.assertEqual("actual_shared_support", own[0]["basis"])
        travel_to_location(self.bridge, self.state.population["player"]["current_location_id"], self.helper)
        before = deepcopy(self.state.action_economy)
        result = as_npc(self.bridge, "player", "ASK_NPC_PLAN", {"npc_id": self.helper})
        self.assertTrue(result.success, result.code)
        self.assertIn("继续学习", result.payload["report"]["summary"])
        self.assertNotIn(self.state.population[self.target]["display_name"], result.payload["report"]["summary"])
        self.assertEqual(before, self.state.action_economy)
        self.assertNotIn("long_term_plans", self.bridge.snapshot()["population"][self.helper])


if __name__ == "__main__": unittest.main()
