from collections import Counter
from copy import deepcopy
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems.transactions import TransactionContext
from simulation.systems.randomness import DeterministicRngPool
from simulation.systems.campus_goals import goal_candidates, goal_step, personal_goals_invariant, record_goal_outcome
from simulation.systems.campus_support_preparation import source_valid, start_preparation, advance_support_preparations
from simulation.systems.campus_anomaly_meetings import options, records
from simulation.systems.campus_messaging import _add_contact, load_campus_messaging_policy
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems.campus_growth import mastery_by_topic
from simulation.systems import load_campus_activity_definitions, load_campus_decision_policy
from tests.test_campus_anomalies import prepare_anomaly_fixture
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_disputes import command
from tests.test_campus_combat_deployment import travel_to_location


def prepare_support_fixture(bridge, helpful=True):
    target, _, cid = prepare_anomaly_fixture(bridge)
    state = bridge.kernel._state
    case = state.situations["campus_anomalies"]["cases"][cid]
    helper = next(w for w in state.population if w not in {"player", target, "campus_student_002"}
        and not state.population[w].get("active_forum_task_id")
        and not state.cognition.get("long_term_plans", {}).get("actors", {}).get(w)
        and options(state, case, w, bridge.location_graph))
    _add_contact(state, target, helper)
    for a, b in ((target, helper), (helper, target)):
        state.relationships[a][b] = {**DEFAULT_RELATIONSHIP, "trust": 75}
    state.population[helper]["personality"].update(altruism=100 if helpful else 0, agreeableness=100 if helpful else 0, risk_tolerance=60)
    # Explicit free study-slot/needs fixture, no knowledge, case or outcome grant.
    state.population[helper]["needs"].update(rest=0, food=0, safety=0)
    state.action_economy["actors"][helper]["major_remaining"] = 1
    choice = options(state, case, helper, bridge.location_graph)[0]
    result = as_npc(bridge, target, "PROPOSE_ANOMALY_MEETING", {"case_id": cid, "helper_id": helper, **choice})
    assert result.success, result.code
    return target, helper, cid


class SupportPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.target, cls.helper, cls.cid = prepare_support_fixture(cls.bridge)
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
    def goal(self): return self.state.cognition["long_term_plans"]["actors"][self.helper]["support:" + self.cid]

    def context(self):
        return TransactionContext(self.state, DeterministicRngPool(42), SimulationCommand("preparation-test", "player", "ADVANCE_PHASE", self.state.revision))

    def candidates(self, priority=20):
        return goal_candidates(self.context(), self.helper, {"activity_id": "SELF_STUDY", "location_id": self.state.population[self.helper]["home_location_id"], "priority": priority},
            self.bridge.location_graph, Counter(), self.policy, self.defs, 40)

    def study(self):
        candidate = self.candidates()[0]
        self.assertEqual("READ_KNOWLEDGE", candidate["activity_id"])
        travel_to_location(self.bridge, candidate["location_id"], self.helper)
        result = as_npc(self.bridge, self.helper, candidate["activity_id"], candidate["parameters"])
        self.assertTrue(result.success, result.code)
        record_goal_outcome(self.context(), self.helper, candidate, result)

    def test_actual_request_and_statement_not_invented_personal_case(self):
        self.assertEqual("read", self.goal["step"])
        self.assertTrue(source_valid(self.state, self.helper, self.goal))
        self.assertEqual(0, mastery_by_topic(self.state, self.helper).get(self.goal["topic_id"], 0))
        growth = self.state.knowledge.get("growth", {}).get("actors", {}).get(self.helper, {})
        self.assertFalse(growth.get("case_records"))
        self.assertNotIn("player", self.state.cognition["long_term_plans"]["actors"])
        self.assertEqual("declined", records(self.state)[self.goal["request_id"]]["status"])
        before = deepcopy(self.state.cognition["long_term_plans"])
        self.assertFalse(start_preparation(self.context(), records(self.state)[self.goal["request_id"]], self.phone_policy))
        self.assertEqual(before, self.state.cognition["long_term_plans"])
        self.assertEqual([], personal_goals_invariant(self.state))

    def test_real_reading_cost_and_no_instant_appointment_or_support(self):
        before = deepcopy((self.state.clock, self.state.population["player"], self.state.situations))
        self.study()
        self.assertEqual(20, mastery_by_topic(self.state, self.helper)[self.goal["topic_id"]])
        self.assertEqual("arrange_support", self.goal["step"])
        self.assertEqual(0, self.state.action_economy["actors"][self.helper]["major_remaining"])
        self.assertEqual([], self.candidates())
        self.assertEqual(before, (self.state.clock, self.state.population["player"], self.state.situations))
        self.assertEqual([], personal_goals_invariant(self.state))

    def test_protected_duty_and_emergency_defer_without_erasing_goal(self):
        self.assertEqual([], self.candidates(priority=95))
        self.assertEqual("blocked", self.goal["status"])
        self.state.population[self.helper]["needs"]["safety"] = 100
        self.assertEqual([], self.candidates())
        self.state.population[self.helper]["needs"]["safety"] = 0
        self.assertTrue(self.candidates())
        self.assertEqual("read", self.goal["step"])

    def test_source_checkpoint_rejects_another_person_or_foreign_claim(self):
        saved, rng = self.bridge.kernel.capture_checkpoint()
        self.bridge.kernel.restore_checkpoint(saved, rng, expected_revision=self.state.revision)
        self.assertTrue(source_valid(self.state, self.helper, self.goal))
        self.goal["subject_id"] = "player"
        self.assertIn("support preparation lacks requested voluntary source", personal_goals_invariant(self.state))

    def test_readiness_is_not_falsely_completed_support(self):
        self.study()
        self.goal["status"] = "completed"
        self.assertIn("personal goal falsely completed", personal_goals_invariant(self.state))

    def test_personal_plan_disclosure_is_free_and_does_not_name_subject(self):
        travel_to_location(self.bridge, self.state.population["player"]["current_location_id"], self.helper)
        before = deepcopy(self.state.action_economy)
        result = as_npc(self.bridge, "player", "ASK_NPC_PLAN", {"npc_id": self.helper})
        self.assertTrue(result.success, result.code)
        self.assertIn("朋友", result.payload["report"]["summary"])
        self.assertNotIn(self.state.population[self.target]["display_name"], result.payload["report"]["summary"])
        self.assertNotIn("case_id", result.payload["report"])
        self.assertEqual(before, self.state.action_economy)

    def test_after_learning_next_dawn_reconsiders_but_never_intraday(self):
        self.study()
        before = deepcopy(records(self.state))
        advance_support_preparations(self.context(), self.bridge.location_graph, self.phone_policy)
        self.assertEqual(before, records(self.state))
        # Actual phase commands, no clock edits, no new theory injected.
        for _ in range(4):
            result = command(self.bridge, "ADVANCE_PHASE", {})
            self.assertTrue(result["ok"], result["result"])
        self.assertEqual(3, self.state.clock.day)
        self.assertEqual("morning", self.state.clock.phase)
        self.assertIn(goal_step(self.state, self.helper, self.goal), {"arrange_support", "await_support", "complete", "support_closed"})
        self.assertGreaterEqual(mastery_by_topic(self.state, self.helper)[self.goal["topic_id"]], 20)
        self.assertEqual([], personal_goals_invariant(self.state))

    def test_unwilling_contact_does_not_receive_mandatory_goal(self):
        bridge = CampusKernelBridge(42)
        _, helper, cid = prepare_support_fixture(bridge, helpful=False)
        self.assertNotIn("support:" + cid, bridge.kernel._state.cognition["long_term_plans"]["actors"].get(helper, {}))

    def test_changed_relationship_pauses_learning_without_erasing_goal(self):
        self.state.relationships[self.helper][self.target]["trust"] = 0
        self.assertEqual([], self.candidates())
        self.assertEqual("blocked", self.goal["status"])
        self.assertTrue(source_valid(self.state, self.helper, self.goal))

    def test_model_receives_own_typed_goal_and_server_owned_reading_candidate(self):
        from tests.test_campus_cognition import LastLegalProvider
        candidates = self.candidates()
        provider = LastLegalProvider()
        self.bridge.cognition_runtime.provider = provider
        self.state.cognition["focused_ids"] = [self.helper]
        selected = self.bridge.cognition_runtime.select(self.state, self.helper, candidates)
        self.assertEqual(1, len(provider.requests))
        self.assertEqual("support_preparation", provider.requests[0].state["personal_goals"][0]["kind"])
        self.assertEqual(self.target, provider.requests[0].state["personal_goals"][0]["subject_id"])
        self.assertEqual(candidates[-1]["parameters"], selected["parameters"])
        self.bridge.cognition_runtime.configure_rule()


if __name__ == "__main__": unittest.main()
