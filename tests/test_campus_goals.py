"""Persistent NPC plan sources, legal next steps, replanning and volunteered reports."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.systems import ContentRegistry, load_campus_activity_definitions, load_campus_decision_policy, load_campus_location_graph
from simulation.systems.campus_goals import advance_personal_goals, goal_candidates, personal_goals_invariant, own_goal_context
from simulation.systems.campus_growth import _actor_growth, _topic_progress
from simulation.persistence.kernel_checkpoint import load_kernel_checkpoint, save_kernel_checkpoint
from tests.test_campus_combat_deployment import execute
from tests.test_campus_cognition import LastLegalProvider


class CampusGoalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(46)
        # Real four-phase NPC task execution supplies the initial case sources.
        for index in range(4):
            result = execute(cls.bridge, "ADVANCE_PHASE", {}, marker=f"goal-setup-{index}")
            assert result["ok"], result
        cls.baseline, cls.rng = cls.bridge.kernel.capture_checkpoint()
        cls.registry = ContentRegistry.load_default(Path(__file__).resolve().parents[1] / "content")
        cls.graph = load_campus_location_graph(cls.registry)
        cls.definitions = load_campus_activity_definitions(cls.registry)
        cls.policy = load_campus_decision_policy(cls.registry, cls.definitions, cls.graph)

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.state = self.bridge.kernel._state
        self.bridge.cognition_runtime.configure_rule()
        self.events = []
        self.context = SimpleNamespace(state=self.state, emit=lambda *args, **kwargs: self.events.append((args, kwargs)))
        advance_personal_goals(self.context)
        ledger = self.state.cognition["long_term_plans"]["actors"]
        self.npc = next(iter(ledger))
        self.goal = next(iter(ledger[self.npc].values()))
        self.topic = self.goal["topic_id"]
        self.actor = self.state.population[self.npc]
        self.actor["current_location_id"] = self.actor["home_location_id"]
        self.actor.pop("current_activity", None)
        self.actor.pop("current_decision", None)
        self.actor.pop("active_forum_task_id", None)
        # Only candidate-unit fixtures clear transient needs; multi-day tests restore baseline.
        self.actor["needs"].update(rest=0, food=0, safety=0)
        self.state.situations["night_world"]["actor_states"][self.npc]["layer"] = "surface"
        self.state.action_economy["actors"][self.npc]["major_remaining"] = 1
        self.plan = {"activity_id": "SELF_STUDY", "location_id": self.actor["home_location_id"], "priority": 20}

    def candidates(self):
        return goal_candidates(self.context, self.npc, self.plan, self.graph, Counter(), self.policy, self.definitions, 40)

    def act(self, action, params=None, actor_id="player", marker="goal-action"):
        state = self.bridge.kernel.state
        return self.bridge.execute({"command_id": f"{marker}:{state.revision}", "actor_id": actor_id,
            "action_id": action, "parameters": params or {}, "target_ids": [], "source": "player" if actor_id == "player" else "rule",
            "expected_world_revision": state.revision, "issued_day": state.clock.day, "issued_phase": state.clock.phase, "issued_minute": state.clock.minute})

    def test_goals_start_only_from_owned_actual_cases_and_are_not_duplicated(self):
        self.assertGreater(len(self.state.cognition["long_term_plans"]["actors"]), 0)
        self.assertNotIn("player", self.state.cognition["long_term_plans"]["actors"])
        before = deepcopy(self.state.cognition["long_term_plans"])
        self.assertEqual(0, advance_personal_goals(self.context)["personal_goals_created"])
        self.assertEqual(before, self.state.cognition["long_term_plans"])
        self.assertEqual([], personal_goals_invariant(self.state))
        other = next(key for key in self.state.population if key != "player" and key not in before["actors"])
        _topic_progress(_actor_growth(self.state, other), self.topic)["theory"] = 40
        advance_personal_goals(self.context)
        self.assertNotIn(other, self.state.cognition["long_term_plans"]["actors"])

    def test_read_step_is_legal_and_common_handler_charges_own_action(self):
        candidate = self.candidates()[0]
        self.assertEqual("READ_KNOWLEDGE", candidate["activity_id"])
        self.actor["current_location_id"] = candidate["location_id"]
        before = self.bridge.kernel.state
        result = self.act(candidate["activity_id"], candidate["parameters"], self.npc)
        self.assertTrue(result["ok"], result)
        after = self.bridge.kernel.state
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(0, after.action_economy["actors"][self.npc]["major_remaining"])
        self.assertEqual(before.action_economy["actors"]["player"], after.action_economy["actors"]["player"])
        self.assertEqual(20, after.knowledge["growth"]["actors"][self.npc]["topics"][self.topic]["theory"])

    def test_protected_duty_and_emergency_do_not_erase_goal(self):
        original_id = self.goal["goal_id"]
        self.plan["priority"] = 95
        self.assertEqual([], self.candidates())
        self.assertEqual("blocked", self.goal["status"])
        self.assertIn("课程", self.goal["blocked_reason"])
        self.plan["priority"] = 20
        self.actor["needs"]["rest"] = 100
        self.assertEqual([], self.candidates())
        self.actor["needs"]["rest"] = 0
        self.assertTrue(self.candidates())
        self.assertEqual(original_id, self.goal["goal_id"])
        self.assertEqual("active", self.goal["status"])

    def test_existing_task_night_layer_and_spent_budget_defer_plan(self):
        self.actor["active_forum_task_id"] = "explicit-unit-commitment"
        self.assertEqual([], self.candidates())
        self.actor.pop("active_forum_task_id")
        self.state.situations["night_world"]["actor_states"][self.npc]["layer"] = "night"
        self.assertEqual([], self.candidates())
        self.state.situations["night_world"]["actor_states"][self.npc]["layer"] = "surface"
        self.state.action_economy["actors"][self.npc]["major_remaining"] = 0
        self.assertEqual([], self.candidates())

    def reflection_fixture(self, wealth=100):
        # Explicit threshold/resource fixture; actual shared action is tested separately.
        _topic_progress(_actor_growth(self.state, self.npc), self.topic)["theory"] = 40
        self.state.inventories["actors"][self.npc]["quantities"].pop("blank_notebook", None)
        self.actor["wealth"] = wealth

    def test_missing_material_creates_real_purchase_step_then_replans_to_reflection(self):
        self.reflection_fixture()
        candidate = self.candidates()[0]
        self.assertEqual("BUY_ITEM", candidate["activity_id"])
        self.assertEqual("blank_notebook", candidate["parameters"]["item_id"])
        self.assertEqual(1, candidate["parameters"]["quantity"])
        # Another actor's gift/acquisition changes actual inventory; next plan must notice.
        self.state.inventories["actors"][self.npc]["quantities"]["blank_notebook"] = 1
        self.assertEqual("REFLECT_ON_CASE", self.candidates()[0]["activity_id"])

    def test_missing_money_uses_existing_paid_work_and_never_credits_free_money(self):
        self.reflection_fixture(0)
        candidate = self.candidates()[0]
        self.assertEqual("CAMPUS_SERVICE_SHIFT", candidate["activity_id"])
        self.assertEqual(0, self.actor["wealth"])
        self.assertEqual("earn_money", self.goal["step"])

    def test_actual_purchase_conserves_stock_and_money_without_major_cost(self):
        self.reflection_fixture()
        candidate = self.candidates()[0]
        self.actor["current_location_id"] = candidate["location_id"]
        before = self.bridge.kernel.state
        result = self.act("BUY_ITEM", candidate["parameters"], self.npc)
        self.assertTrue(result["ok"], result)
        after = self.bridge.kernel.state
        shop = candidate["parameters"]["shop_id"]
        price = before.inventories["catalog"]["blank_notebook"]["base_price"]
        self.assertEqual(before.population[self.npc]["wealth"] - price, after.population[self.npc]["wealth"])
        self.assertEqual(before.inventories["shops"][shop]["cash"] + price, after.inventories["shops"][shop]["cash"])
        self.assertEqual(before.inventories["shops"][shop]["quantities"]["blank_notebook"] - 1, after.inventories["shops"][shop]["quantities"]["blank_notebook"])
        self.assertEqual(before.action_economy, after.action_economy)

    def test_disclosed_report_does_not_make_private_goal_events_visible(self):
        from simulation.api.views import npc_chronicle_view
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)
        result = self.act("ADVANCE_PHASE")
        self.assertTrue(result["ok"], result)
        state = self.bridge.kernel._state
        goals = state.cognition["long_term_plans"]["actors"]
        for npc in goals:
            state.population["player"]["current_location_id"] = state.population[npc]["current_location_id"]
            view = npc_chronicle_view(state, npc)
            self.assertFalse(any(item.get("event_type", "").startswith("NPC_PERSONAL_GOAL") for item in view["items"]))
        private_entries = [item for item in state.chronicles["entries"].values() if item["event_type"].startswith("NPC_PERSONAL_GOAL")]
        self.assertTrue(private_entries)
        self.assertTrue(all(item["visibility"] == "private" for item in private_entries))
        self.assertTrue(all(item["entry_id"] not in state.chronicles["known_by"].get("player", {}) for item in private_entries))

    def test_out_of_stock_and_capacity_block_then_resume_without_dropping_goal(self):
        self.reflection_fixture()
        for shop in self.state.inventories["shops"].values():
            shop["quantities"].pop("blank_notebook", None)
        self.assertEqual([], self.candidates())
        self.assertEqual("blocked", self.goal["status"])
        self.state.inventories["shops"]["campus_market"]["quantities"]["blank_notebook"] = 1
        self.assertTrue(self.candidates())
        self.state.inventories["actors"][self.npc]["max_weight"] = 0
        self.assertEqual([], self.candidates())

    def test_completed_goals_do_not_repeat_or_claim_full_mastery(self):
        progress = _topic_progress(_actor_growth(self.state, self.npc), self.topic)
        progress.update(theory=40, reflection=10)
        advance_personal_goals(self.context)
        self.assertEqual("completed", self.goal["status"])
        self.assertNotIn(self.goal["goal_id"], [item["personal_goal_id"] for item in self.candidates()])
        self.assertLess(sum(progress.values()), 100)

    def test_llm_sees_only_own_goals_and_keeps_server_owned_parameters(self):
        candidates = self.candidates()
        provider = LastLegalProvider()
        self.bridge.cognition_runtime.provider = provider
        self.state.cognition["focused_ids"] = [self.npc]
        result = self.bridge.cognition_runtime.select(self.state, self.npc, candidates)
        self.assertEqual(candidates[-1]["parameters"], result["parameters"])
        self.assertEqual(1, len(provider.requests))
        self.assertEqual(own_goal_context(self.state, self.npc), provider.requests[0].state["personal_goals"])
        self.assertEqual("llm", result["decision_source"])

    def test_disclosure_is_free_dated_and_does_not_reveal_secret_topic_or_live_plan(self):
        self.state.population["player"]["current_location_id"] = self.actor["current_location_id"]
        self.actor["personality"]["risk_tolerance"] = 60
        snapshot = self.bridge.snapshot()
        self.assertEqual({}, snapshot["population"][self.npc]["stated_plan"])
        before = self.bridge.kernel.state
        result = self.act("ASK_NPC_PLAN", {"npc_id": self.npc})
        self.assertTrue(result["ok"], result)
        after = self.bridge.kernel.state
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(before.action_economy, after.action_economy)
        report = self.bridge.snapshot()["population"][self.npc]["stated_plan"]
        self.assertEqual(after.clock.day, report["day"])
        self.assertNotIn(self.topic, str(report))
        self.assertNotIn("source_ids", str(report))
        self.assertNotIn("long_term_plans", str(self.bridge.snapshot().get("cognition", {})))
        self.bridge.kernel._state.cognition["long_term_plans"]["actors"][self.npc][self.goal["goal_id"]]["blocked_reason"] = "secret-plan-change"
        self.assertEqual(report, self.bridge.snapshot()["population"][self.npc]["stated_plan"])

    def test_guarded_npc_can_decline_and_remote_or_layer_mismatch_is_atomic(self):
        self.state.population["player"]["current_location_id"] = self.actor["current_location_id"]
        self.actor["personality"]["risk_tolerance"] = 0
        result = self.act("ASK_NPC_PLAN", {"npc_id": self.npc})
        self.assertTrue(result["result"]["payload"]["report"]["withheld"])
        state = self.bridge.kernel._state
        state.population["player"]["current_location_id"] = "south_gate_region"
        before = self.bridge.kernel.state
        result = self.act("ASK_NPC_PLAN", {"npc_id": self.npc})
        self.assertFalse(result["ok"])
        self.assertEqual(before.cognition, self.bridge.kernel.state.cognition)

    def test_checkpoint_preserves_plans_and_malformed_ledgers_are_rejected(self):
        state, rng = self.bridge.kernel.capture_checkpoint()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "goals.json"
            save_kernel_checkpoint(path, state, rng)
            loaded = load_kernel_checkpoint(path, expected_content_version=state.content_version)
            self.assertEqual(state.cognition["long_term_plans"], loaded.state.cognition["long_term_plans"])
        for malformed in ([], {"schema_version": 1, "actors": [], "disclosures": {}},
                          {"schema_version": 1, "actors": {self.npc: {"bad": []}}, "disclosures": {}}):
            altered = deepcopy(state)
            altered.cognition["long_term_plans"] = malformed
            self.assertTrue(personal_goals_invariant(altered))
        self.goal["source_ids"] = ["someone-elses-invented-case"]
        self.assertTrue(personal_goals_invariant(self.state))

    def test_actual_no_player_phase_execution_progresses_persistent_goals(self):
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)
        for _ in range(12):
            result = self.act("ADVANCE_PHASE")
            self.assertTrue(result["ok"], result)
        state = self.bridge.kernel.state
        goals = [goal for records in state.cognition["long_term_plans"]["actors"].values() for goal in records.values()]
        progressed = [goal for goal in goals if goal["attempts"] > 0]
        self.assertTrue(progressed)
        self.assertTrue(any(goal["status"] == "completed" for goal in goals), [(g["step"], g["attempts"], g["blocked_reason"]) for g in goals])
        self.assertEqual([], personal_goals_invariant(state))
        self.assertEqual({}, state.knowledge["growth"]["actors"].get("player", {}).get("topics", {}))


if __name__ == "__main__":
    unittest.main()
