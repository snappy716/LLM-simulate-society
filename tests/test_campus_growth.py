"""Real learning costs, source-bound gains, owned decks and knowledge tactics."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from simulation.api.server import CampusKernelBridge
from simulation.domain.events import SimulationEvent
from simulation.systems.campus_growth import _actor_growth, _topic_progress, growth_invariant, project_growth_events, mastery_by_topic
from simulation.systems.campus_combat import resolve_combat_effects
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_combat_deployment import execute
from tests.test_campus_combat_rounds import deploy_and_start


class CampusGrowthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(46)
        cls.bridge.kernel._state.population["player"]["current_location_id"] = "east_dorm_room_pool"
        cls.baseline, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.counter = 0

    def act(self, action, **params):
        self.counter += 1
        return execute(self.bridge, action, params, marker=f"growth-{self.counter}")

    def assert_rejected(self, code, action, **params):
        before, rng = self.bridge.kernel.capture_checkpoint()
        result = self.act(action, **params)
        self.assertFalse(result["ok"], result)
        self.assertEqual(code, result["result"]["code"])
        after, current_rng = self.bridge.kernel.capture_checkpoint()
        for field in ("population", "knowledge", "battles", "inventories", "action_economy", "clock", "revision"):
            self.assertEqual(getattr(before, field), getattr(after, field), field)
        self.assertEqual(rng.snapshot(), current_rng.snapshot())

    def test_reading_spends_one_action_not_a_phase_and_only_grants_theory(self):
        before = self.bridge.kernel.state
        result = self.act("READ_KNOWLEDGE", topic_id="moon_fragment")
        self.assertTrue(result["ok"], result)
        after = self.bridge.kernel.state
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(before.inventories, after.inventories)
        self.assertEqual(before.action_economy["actors"]["player"]["major_remaining"] - 1, after.action_economy["actors"]["player"]["major_remaining"])
        topic = after.knowledge["growth"]["actors"]["player"]["topics"]["moon_fragment"]
        self.assertEqual({"theory": 20, "cases": 0, "application": 0, "reflection": 0}, topic)

    def test_theory_cap_no_free_mastery_and_missing_reflection_prerequisite(self):
        self.act("READ_KNOWLEDGE", topic_id="moon_fragment")
        self.act("ADVANCE_PHASE")
        self.assertTrue(self.act("READ_KNOWLEDGE", topic_id="moon_fragment")["ok"])
        self.act("ADVANCE_PHASE")
        self.assert_rejected("component_complete", "READ_KNOWLEDGE", topic_id="moon_fragment")
        self.assert_rejected("reflection_requires_case", "REFLECT_ON_CASE", topic_id="moon_fragment")
        self.assertEqual(40, mastery_by_topic(self.bridge.kernel.state, "player")["moon_fragment"])

    def test_wrong_location_no_budget_and_unknown_topic_are_atomic(self):
        self.assert_rejected("unknown_knowledge_topic", "READ_KNOWLEDGE", topic_id=[])
        self.bridge.kernel._state.population["player"]["current_location_id"] = "south_gate_region"
        self.assert_rejected("study_unavailable", "READ_KNOWLEDGE", topic_id="moon_fragment")
        self.bridge.kernel._state.population["player"]["current_location_id"] = "east_dorm_room_pool"
        self.bridge.kernel._state.action_economy["actors"]["player"]["major_remaining"] = 0
        self.assert_rejected("study_unavailable", "READ_KNOWLEDGE", topic_id="moon_fragment")

    def test_focus_is_free_and_ordinary_major_learning_contributes_to_selected_topic(self):
        before = self.bridge.kernel.state.action_economy
        self.assertTrue(self.act("SET_STUDY_FOCUS", topic_id="empty_face")["ok"])
        self.assertEqual(before, self.bridge.kernel.state.action_economy)
        result = self.act("SELF_STUDY", location_id="east_dorm_room_pool")
        self.assertTrue(result["ok"], result)
        self.assertEqual(5, mastery_by_topic(self.bridge.kernel.state, "player")["empty_face"])
        self.assertTrue(all(progress["experience"] == 5 for progress in self.bridge.kernel.state.population["player"]["ability_progress"].values()))

    def test_free_self_care_does_not_grant_growth(self):
        self.act("SET_STUDY_FOCUS", topic_id="empty_face")
        before = self.bridge.kernel.state.population["player"]
        self.act("REST")
        after = self.bridge.kernel.state.population["player"]
        self.assertEqual(before["attributes"], after["attributes"])
        self.assertEqual(before["ability_progress"], after["ability_progress"])
        self.assertEqual({}, mastery_by_topic(self.bridge.kernel.state, "player"))

    def test_attribute_growth_raises_capacity_without_healing_and_preserves_source_idempotency(self):
        state = self.bridge.kernel._state
        actor = state.population["player"]
        initial = actor["attributes"]["physique"]
        actor["vitals"]["health"] -= 10
        health = actor["vitals"]["health"]
        event_args = dict(event_type="CAMPUS_ACTIVITY_EFFECT_APPLIED", day=1, phase="morning", minute=0,
                          world_revision=1, command_id="activity", public_summary="主要活动已结算", actor_ids=("player",),
                          payload={"activity_id": "SECURITY_PATROL", "effects": {"category": "work", "budget": {"action_class": "major"}}})
        # Explicit committed-event fixture: no claim this accelerated practice is live gameplay.
        for index in range(8 + initial * 2):
            event = SimulationEvent(event_id=f"practice:{index}", **event_args)
            project_growth_events(state, [event])
            before = deepcopy(state.knowledge)
            project_growth_events(state, [event])
            self.assertEqual(before, state.knowledge)
        self.assertEqual(initial + 1, actor["attributes"]["physique"])
        self.assertEqual(health, actor["vitals"]["health"])

    def test_owned_deck_save_is_free_and_rejects_unowned_or_missing_basics(self):
        before = self.bridge.kernel.state
        cards = ["general:brace", "general:center"] + [before.population["player"]["card_pool_ids"][0]] * 6
        self.assertTrue(self.act("CONFIGURE_ACTOR_DECK", card_ids=cards)["ok"])
        after = self.bridge.kernel.state
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(before.action_economy, after.action_economy)
        self.assertEqual(cards, after.knowledge["growth"]["actors"]["player"]["deck_ids"])
        for invalid in ([], ["unknown"] * 8, [cards[-1]] * 8, [None] * 8):
            self.assert_rejected("invalid_deck", "CONFIGURE_ACTOR_DECK", card_ids=invalid)
        self.assert_rejected("deck_actor_not_controlled", "CONFIGURE_ACTOR_DECK", card_actor_id="stranger", card_ids=cards)

    def test_checkpoint_preserves_growth_and_custom_deck(self):
        self.act("READ_KNOWLEDGE", topic_id="moon_fragment")
        cards = ["general:brace", "general:center"] + [self.bridge.kernel.state.population["player"]["card_pool_ids"][0]] * 6
        self.assertTrue(self.act("CONFIGURE_ACTOR_DECK", card_ids=cards)["ok"])
        state, rng = self.bridge.kernel.capture_checkpoint()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "growth.json"
            save_kernel_checkpoint(path, state, rng)
            loaded = load_kernel_checkpoint(path, expected_content_version=state.content_version)
            self.bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=state.revision)
        self.assertEqual(state.knowledge, self.bridge.kernel.state.knowledge)
        self.assertEqual([], growth_invariant(self.bridge.kernel.state))

    def test_selected_owned_deck_is_used_by_real_battle_instances(self):
        cards = ["general:brace", "general:center"] + [self.bridge.kernel.state.population["player"]["card_pool_ids"][0]] * 6
        self.assertTrue(self.act("CONFIGURE_ACTOR_DECK", card_ids=cards)["ok"])
        deploy_and_start(self.bridge, teammate_count=1)
        battle = next(iter(self.bridge.kernel.state.battles.values()))
        self.assertEqual(cards, battle["actor_decks"]["player"])
        owned = [item["card_id"] for item in battle["card_instances"].values() if item["owner_actor_id"] == "player"]
        self.assertCountEqual(cards, owned)

    def test_npc_can_read_with_own_budget_and_does_not_grant_player_knowledge(self):
        state = self.bridge.kernel._state
        npc = next(key for key in state.population if key != "player")
        state.population[npc]["current_location_id"] = state.population[npc]["home_location_id"]
        before = self.bridge.kernel.state
        result = self.bridge.execute({"command_id": "npc-read", "actor_id": npc, "action_id": "READ_KNOWLEDGE", "parameters": {"topic_id": "empty_face"}, "target_ids": [], "source": "rule", "expected_world_revision": before.revision, "issued_day": before.clock.day, "issued_phase": before.clock.phase, "issued_minute": 0})
        self.assertTrue(result["ok"], result)
        after = self.bridge.kernel.state
        self.assertEqual(20, mastery_by_topic(after, npc)["empty_face"])
        self.assertEqual({}, mastery_by_topic(after, "player"))
        self.assertEqual(before.action_economy["actors"]["player"], after.action_economy["actors"]["player"])
        self.assertEqual(before.action_economy["actors"][npc]["major_remaining"] - 1, after.action_economy["actors"][npc]["major_remaining"])

    def test_view_is_read_only_and_does_not_reveal_other_actor_learning(self):
        npc = next(key for key in self.bridge.kernel._state.population if key != "player")
        _topic_progress(_actor_growth(self.bridge.kernel._state, npc), "empty_face")["theory"] = 40
        before = self.bridge.kernel.state.to_dict()
        view = self.bridge.snapshot()["growth"]
        self.assertTrue(all(item["mastery"] == 0 for item in view["topics"]))
        self.assertEqual(before, self.bridge.kernel.state.to_dict())

    def test_npcs_earn_task_cases_without_player_or_card_battle(self):
        for _step in range(4):
            self.assertTrue(self.act("ADVANCE_PHASE")["ok"])
        state = self.bridge.kernel.state
        self.assertEqual({}, state.battles)
        cases = [(actor_id, case) for actor_id, record in state.knowledge["growth"]["actors"].items()
                 for case in record["case_records"].values()]
        self.assertGreater(len(cases), 0)
        for actor_id, case in cases:
            self.assertNotEqual("player", actor_id)
            task = state.tasks[case["task_id"]]
            self.assertEqual("completed", task["state"])
            self.assertEqual(actor_id, task["assignee_id"])
            self.assertIn(case["claim_id"], state.knowledge["beliefs_by_actor"][actor_id])

    def test_invalid_component_values_and_containers_rejected(self):
        self.act("READ_KNOWLEDGE", topic_id="moon_fragment")
        original = self.bridge.kernel.state
        for invalid in (True, -1, 41, "20", []):
            state = deepcopy(original)
            state.knowledge["growth"]["actors"]["player"]["topics"]["moon_fragment"]["theory"] = invalid
            self.assertTrue(growth_invariant(state))
        state = deepcopy(original)
        state.knowledge["growth"]["actors"]["player"]["deck_ids"] = {}
        self.assertTrue(growth_invariant(state))


class CampusKnowledgeBattleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(46)
        deploy_and_start(cls.bridge, teammate_count=1)
        cls.baseline, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.counter = 0
        self.battle_id = next(iter(self.bridge.kernel._state.battles))
        self.enemy_id = next(iter(self.bridge.kernel._state.battles[self.battle_id]["enemy_units"]))
        self.topic = self.bridge.kernel._state.battles[self.battle_id]["enemy_units"][self.enemy_id]["archetype_id"]

    def act(self, action, **params):
        self.counter += 1
        battle = self.bridge.kernel._state.battles[self.battle_id]
        return execute(self.bridge, action, {"battle_id": self.battle_id, "expected_battle_revision": battle["revision"], **params}, marker=f"knowledge-battle-{self.counter}")

    def understanding_fixture(self, theory=40, cases=30, application=5, reflection=0):
        # Explicit threshold fixture; independent tests verify earned credits.
        state = self.bridge.kernel._state
        _actor_growth(state, "player")["topics"][self.topic] = dict(theory=theory, cases=cases, application=application, reflection=reflection)
        project_growth_events(state, [])

    def test_low_understanding_has_no_insight_and_failed_command_changes_nothing(self):
        self.assertEqual([], self.bridge.snapshot()["combat"]["active_battle"]["action_options"]["insights"])
        before = self.bridge.kernel.state
        result = self.act("USE_KNOWLEDGE_INSIGHT", target_id=self.enemy_id, tactic="interrupt")
        self.assertFalse(result["ok"])
        after = self.bridge.kernel.state
        self.assertEqual(before.battles, after.battles)
        self.assertEqual(before.knowledge, after.knowledge)

    def test_insight_interrupt_costs_two_points_blocks_one_attack_and_cannot_repeat(self):
        self.understanding_fixture()
        before = self.bridge.kernel.state
        self.assertTrue(self.act("USE_KNOWLEDGE_INSIGHT", target_id=self.enemy_id, tactic="interrupt")["ok"])
        battle = self.bridge.kernel.state.battles[self.battle_id]
        self.assertEqual(1, battle["command_points"]["party:player"])
        result = self.act("END_COMBAT_ROUND")
        self.assertTrue(result["ok"], result)
        self.assertTrue(any(event["payload"].get("interrupted") for event in result["result"]["events"]))
        self.assertEqual(before.population["player"]["vitals"]["health"], self.bridge.kernel.state.population["player"]["vitals"]["health"])
        self.assertFalse(self.act("USE_KNOWLEDGE_INSIGHT", target_id=self.enemy_id, tactic="interrupt")["ok"])

    def test_knowledge_damage_and_exposure_change_real_effects(self):
        self.understanding_fixture()
        battle = deepcopy(self.bridge.kernel._state.battles[self.battle_id])
        enemy = battle["enemy_units"][self.enemy_id]
        enemy["weaknesses"] = ["physical"]
        blueprint = {"base_power": 5, "effect_ids": ["deal_physical"]}
        normal = deepcopy(battle)
        source = next(card for card in normal["character_cards"].values() if card["actor_id"] == "player")
        source["knowledge_mastery"] = {}
        base = resolve_combat_effects(normal, "player", blueprint, self.enemy_id)[0]["amount"]
        learned = resolve_combat_effects(deepcopy(battle), "player", blueprint, self.enemy_id)[0]["amount"]
        enemy["statuses"].append("knowledge_exposed")
        exposed = resolve_combat_effects(battle, "player", blueprint, self.enemy_id)[0]["amount"]
        self.assertGreater(learned, base)
        self.assertGreater(exposed, learned)

    def test_actual_victory_adds_owned_case_not_book_pages_and_deduplicates(self):
        state = self.bridge.kernel._state
        state.battles[self.battle_id]["enemy_health"][self.enemy_id] = 1
        # Explicit one-health enemy fixture, killed by the real command pipeline.
        active = self.bridge.snapshot()["combat"]["active_battle"]
        choice = next((actor_id, item) for actor_id, item in active["action_options"]["base_commands"].items() if self.enemy_id in item["target_ids"])
        inventory = deepcopy(state.inventories)
        result = self.act("USE_COMBAT_BASE_COMMAND", source_actor_id=choice[0], target_ids=[self.enemy_id])
        self.assertTrue(result["ok"], result)
        self.assertEqual("victory", self.bridge.kernel.state.battles[self.battle_id]["result"])
        record = self.bridge.kernel.state.knowledge["growth"]["actors"]["player"]
        self.assertEqual(10, record["topics"][self.topic]["cases"])
        self.assertEqual(0, record["topics"][self.topic]["theory"])
        self.assertEqual(inventory, self.bridge.kernel.state.inventories)
        events = [SimulationEvent.from_dict(event) for event in result["result"]["events"]]
        after = deepcopy(self.bridge.kernel._state.knowledge)
        project_growth_events(self.bridge.kernel._state, events)
        self.assertEqual(after, self.bridge.kernel._state.knowledge)

    def test_application_requires_theory_and_is_once_per_battle_method(self):
        self.understanding_fixture(theory=40, cases=0, application=0)
        self.assertTrue(self.act("USE_KNOWLEDGE_INSIGHT", target_id=self.enemy_id, tactic="observe")["ok"])
        self.assertEqual(5, self.bridge.kernel.state.knowledge["growth"]["actors"]["player"]["topics"][self.topic]["application"])
        self.assertFalse(self.act("USE_KNOWLEDGE_INSIGHT", target_id=self.enemy_id, tactic="observe")["ok"])

    def test_study_and_reconfiguration_are_locked_during_battle(self):
        self.assertFalse(self.act("READ_KNOWLEDGE", topic_id=self.topic)["ok"])
        self.assertFalse(self.act("CONFIGURE_ACTOR_DECK", card_ids=["general:brace"] * 8)["ok"])

    def test_new_character_fields_are_declared_and_invalid_mastery_is_rejected(self):
        import json
        from simulation.systems.campus_combat import campus_combat_invariant
        state = self.bridge.kernel.state
        card = next(iter(state.battles[self.battle_id]["character_cards"].values()))
        schema = json.loads((Path(__file__).resolve().parents[1] / "contracts/combat_character_card.schema.json").read_text())
        self.assertTrue(set(card).issubset(schema["properties"]))
        card["knowledge_mastery"] = {self.topic: 101}
        self.assertTrue(list(campus_combat_invariant(state)))

    def test_real_case_then_reading_unlocks_one_reflection_without_consuming_notebook(self):
        self.bridge.kernel._state.battles[self.battle_id]["enemy_health"][self.enemy_id] = 1
        active = self.bridge.snapshot()["combat"]["active_battle"]
        actor_id = next(key for key, item in active["action_options"]["base_commands"].items() if self.enemy_id in item["target_ids"])
        self.assertTrue(self.act("USE_COMBAT_BASE_COMMAND", source_actor_id=actor_id, target_ids=[self.enemy_id])["ok"])
        self.assertTrue(self.act("EXIT_NIGHT_WORLD")["ok"])
        state = self.bridge.kernel._state
        state.population["player"]["current_location_id"] = state.population["player"]["home_location_id"]
        self.assertTrue(self.act("ADVANCE_PHASE")["ok"])
        self.assertTrue(self.act("READ_KNOWLEDGE", topic_id=self.topic)["ok"])
        self.assertTrue(self.act("ADVANCE_PHASE")["ok"])
        before = self.bridge.kernel.state.inventories
        result = self.act("REFLECT_ON_CASE", topic_id=self.topic)
        self.assertTrue(result["ok"], result)
        progress = self.bridge.kernel.state.knowledge["growth"]["actors"]["player"]["topics"][self.topic]
        self.assertEqual({"theory": 20, "cases": 10, "application": 0, "reflection": 10}, progress)
        self.assertEqual(before, self.bridge.kernel.state.inventories)


if __name__ == "__main__":
    unittest.main()
