"""Real shared NPC battle actions, accounting, defeat, privacy and replay."""
from copy import deepcopy
import unittest
from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_combat import campus_combat_view, combat_policy_from_state, combat_round_policy_from_state
from simulation.systems.campus_autonomous_combat import choose_combat_action, autonomous_combat_invariant
from simulation.systems.campus_parties import create_party, party_policy_from_state, party_for_actor
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from tests.test_campus_combat_deployment import execute


class AutonomousCombatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        for index in range(2):
            result = execute(cls.bridge, "ADVANCE_PHASE", marker=f"npc-combat-{index}")
            assert result["ok"], result["result"]["code"]
        cls.baseline, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.sequence = 0
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.state = self.bridge.kernel._state
        self.bridge.cognition_runtime.configure_rule()
        self.task = next(task for task in self.state.tasks.values() if task.get("forum") == "night"
                         and task.get("resolution_kind") != "field_recon" and task.get("assignee_id")
                         and party_for_actor(self.state, task["assignee_id"]) is None)
        self.npc = self.task["assignee_id"]
        # Explicit unit precondition: at an actually owned task with one action.
        self.actor = self.state.population[self.npc]
        self.actor["current_location_id"] = self.task["scene_id"]
        self.actor.pop("current_activity", None)
        self.actor.pop("current_decision", None)
        self.state.action_economy["actors"][self.npc].update(major_remaining=1, night_combat_paid=False)

    def act(self, action="EXECUTE_NPC_NIGHT_TASK", params=None, actor_id=None, source="rule", command_id=None):
        self.sequence += 1
        state = self.bridge.kernel.state
        return self.bridge.execute({"command_id": command_id or f"auto:{state.revision}:{action}:{self.sequence}",
            "actor_id": actor_id or self.npc, "action_id": action, "source": source, "target_ids": [],
            "parameters": params if params is not None else {"task_id": self.task["task_id"]},
            "expected_world_revision": state.revision, "issued_day": state.clock.day, "issued_phase": state.clock.phase,
            "issued_minute": state.clock.minute})

    def test_actual_phase_executes_battles_without_player_or_free_victory(self):
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)
        result = execute(self.bridge, "ADVANCE_PHASE", marker="real-background-phase")
        self.assertTrue(result["ok"], result["result"]["code"])
        state = self.bridge.kernel.state
        self.assertGreater(len(state.battles), 0)
        self.assertEqual("late_night", state.clock.phase)
        types = {event["event_type"] for event in result["result"]["events"]}
        self.assertTrue({"BATTLE_DEPLOYMENT_CONFIRMED", "COMBAT_ROUND_STARTED", "COMBAT_CARD_PLAYED", "NPC_NIGHT_TASK_EXECUTED"} <= types, types)
        for battle in state.battles.values():
            self.assertNotIn("player", battle["participant_ids"])
            self.assertEqual("resolved", battle["phase"])
            self.assertIn(battle["result"], {"victory", "defeat", "escaped"})
            if battle["result"] == "victory":
                task = state.tasks[battle["situation_id"]]
                self.assertEqual(battle["battle_id"], task["completion_evidence"]["battle_id"])
                self.assertEqual("completed", task["state"])
        self.assertFalse(any(party_id != "party:player" for party_id in state.parties))

    def test_real_resources_action_cost_no_player_mutation_and_receipt(self):
        before = deepcopy(self.state)
        result = self.act()
        self.assertTrue(result["ok"], result["result"]["code"])
        state = self.bridge.kernel.state
        self.assertEqual(before.clock, state.clock)
        self.assertEqual(before.population["player"], state.population["player"])
        self.assertEqual(before.action_economy["actors"]["player"], state.action_economy["actors"]["player"])
        self.assertEqual(0, state.action_economy["actors"][self.npc]["major_remaining"])
        self.assertTrue(state.action_economy["actors"][self.npc]["night_combat_paid"])
        task = state.tasks[self.task["task_id"]]
        receipt = task["execution_receipts"][0]
        self.assertEqual(receipt["result"], state.battles[receipt["battle_id"]]["result"])
        self.assertTrue(any("实际卡牌战斗" in h["message"] for h in task["history"]))

    def test_same_legal_command_sequence_has_identical_battle_and_resource_math(self):
        checkpoint, rng = self.bridge.kernel.capture_checkpoint()
        result = self.act()
        self.assertTrue(result["ok"], result["result"]["code"])
        auto = self.bridge.kernel.state
        self.bridge.kernel.restore_checkpoint(checkpoint, rng, expected_revision=auto.revision)
        state = self.bridge.kernel._state
        create_party(state, self.npc, party_policy_from_state(state), purpose_id="autonomous_task")
        self.assertTrue(self.act("START_BATTLE_PREPARATION")["ok"])
        battle = self.bridge.snapshot()["combat"]  # Player view must not expose NPC's battle.
        self.assertIsNone(battle["active_battle"])
        def view():
            current = self.bridge.kernel.state
            return campus_combat_view(current, self.npc, combat_policy_from_state(current))["active_battle"]
        battle = view(); card_id, card = next(iter(battle["character_cards"].items()))
        for action, params in (("DEPLOY_COMBAT_CHARACTER", {"character_card_instance_id": card_id, "destination_row": card["preferred_row"]}),
                               ("CONFIRM_BATTLE_DEPLOYMENT", {}), ("START_CARD_COMBAT", {})):
            result = self.act(action, params)
            self.assertTrue(result["ok"], result["result"]["code"])
        for _ in range(180):
            battle = view()
            if battle is None:
                break
            action, params = choose_combat_action(self.bridge.kernel.state, battle, self.npc, combat_round_policy_from_state(self.bridge.kernel.state))
            result = self.act(action, params)
            self.assertTrue(result["ok"], result["result"]["code"])
        manual = self.bridge.kernel.state
        self.assertEqual(auto.battles, manual.battles)
        self.assertEqual(auto.population[self.npc]["vitals"], manual.population[self.npc]["vitals"])
        self.assertEqual(auto.population[self.npc]["wealth"], manual.population[self.npc]["wealth"])
        self.assertEqual(auto.inventories["actors"][self.npc], manual.inventories["actors"][self.npc])
        self.assertEqual(auto.action_economy["actors"][self.npc], manual.action_economy["actors"][self.npc])

    def test_spent_action_location_and_source_refuse_without_side_effects(self):
        self.state.action_economy["actors"][self.npc]["major_remaining"] = 0
        before = self.bridge.kernel.state
        result = self.act()
        self.assertFalse(result["ok"])
        self.assertEqual("night_combat_action_exhausted", result["result"]["code"])
        after = self.bridge.kernel.state
        # Failed command receipts are deliberately cached; game state is unchanged.
        after.processed_commands = before.processed_commands
        self.assertEqual(before, after)
        self.assertFalse(self.act(source="player")["ok"])
        self.assertFalse(self.act(actor_id="player")["ok"])

    def test_duplicate_command_and_checkpoint_do_not_duplicate_rewards(self):
        before = self.bridge.kernel.state
        payload = {"command_id": "one-background-battle", "actor_id": self.npc, "action_id": "EXECUTE_NPC_NIGHT_TASK",
            "source": "rule", "parameters": {"task_id": self.task["task_id"]}, "expected_world_revision": before.revision,
            "issued_day": before.clock.day, "issued_phase": before.clock.phase, "issued_minute": before.clock.minute, "target_ids": []}
        first = self.bridge.execute(payload)
        self.assertTrue(first["ok"], first["result"]["code"])
        state, rng = self.bridge.kernel.capture_checkpoint()
        repeated = self.bridge.execute(payload)
        self.assertTrue(repeated["result"]["replayed"])
        self.assertEqual(state, self.bridge.kernel.state)
        self.bridge.kernel.restore_checkpoint(state, rng, expected_revision=state.revision)
        self.assertFalse(self.act()["ok"])
        self.assertEqual(state.population[self.npc]["wealth"], self.bridge.kernel.state.population[self.npc]["wealth"])

    def test_forced_defeat_rescues_npc_without_advancing_clock_or_healing_player(self):
        # Explicit severe encounter boundary, not a claim about normal difficulty.
        archetype = self.state.metadata["campus_combat"]["enemy_archetypes"][self.task["enemy_archetype_id"]]
        archetype.update(max_health=10000, speed=1000)
        self.actor["vitals"]["health"] = 1
        self.state.inventories["actors"][self.npc]["quantities"] = {}
        before = self.bridge.kernel.state
        result = self.act()
        self.assertTrue(result["ok"], result["result"]["code"])
        state = self.bridge.kernel.state
        battle = next(iter(state.battles.values()))
        self.assertEqual("defeat", battle["result"])
        self.assertEqual(before.clock, state.clock)
        self.assertEqual(before.population["player"]["vitals"], state.population["player"]["vitals"])
        self.assertEqual(0, state.population[self.npc]["vitals"]["health"])
        self.assertEqual(self.actor["home_location_id"], state.population[self.npc]["current_location_id"])
        self.assertFalse(battle["consequences"]["rescue"]["recovered"])
        self.assertEqual("failed", state.tasks[self.task["task_id"]]["state"])

    def test_second_battle_in_same_phase_does_not_charge_again(self):
        first = self.act()
        self.assertTrue(first["ok"], first["result"]["code"])
        state = self.bridge.kernel._state
        self.assertEqual("victory", first["result"]["payload"]["autonomous_battle"]["result"])
        task = next(t for t in state.tasks.values() if t.get("forum") == "night"
                    and t.get("resolution_kind") != "field_recon"
                    and t["state"] in {"open", "viewed", "considering"} and t["issuer_id"] != self.npc)
        claimed = self.act("CLAIM_FORUM_TASK", {"task_id": task["task_id"], "expected_task_revision": task["lock_revision"]})
        self.assertTrue(claimed["ok"], claimed["result"]["code"])
        # Arrival fixture isolates the second-entry fee; actual routing is tested by the phase test.
        self.bridge.kernel._state.population[self.npc]["current_location_id"] = task["scene_id"]
        result = self.act(params={"task_id": task["task_id"]})
        self.assertTrue(result["ok"], result["result"]["code"])
        charge = next(e for e in result["result"]["events"] if e["event_type"] == "NIGHT_COMBAT_ENTRY_ACCOUNTED")
        self.assertEqual([], charge["payload"]["due_actor_ids"])
        self.assertEqual(0, self.bridge.kernel.state.action_economy["actors"][self.npc]["major_remaining"])

    def test_player_party_cannot_be_taken_over(self):
        self.actor["night_access"] = "willing"
        self.actor["needs"].update(rest=0, safety=0, commitment_pressure=0)
        self.state.relationships.setdefault(self.npc, {}).setdefault("player", deepcopy(DEFAULT_RELATIONSHIP)).update(trust=100, closeness=100, respect=100, suspicion=0, conflict=0)
        invited = self.act("INVITE_PARTY_MEMBER", {"target_id": self.npc}, actor_id="player", source="player")
        self.assertTrue(invited["ok"], invited["result"]["code"])
        before = self.bridge.kernel.state
        result = self.act()
        self.assertFalse(result["ok"])
        self.assertEqual("party_commitment", result["result"]["code"])
        after = self.bridge.kernel.state
        self.assertEqual(before.parties, after.parties)
        self.assertEqual(before.battles, after.battles)
        self.assertEqual(before.action_economy, after.action_economy)

    def test_wrong_place_and_forged_receipt_cannot_be_used(self):
        self.actor["current_location_id"] = next(key for key, place in self.state.places.items()
            if place.get("node_type") == "region" and key != self.task["execution_region_id"])
        result = self.act()
        self.assertFalse(result["ok"])
        self.assertEqual("task_location_required", result["result"]["code"])
        self.assertEqual({}, self.bridge.kernel.state.battles)
        state = self.bridge.kernel.state
        state.tasks[self.task["task_id"]]["execution_receipts"] = [{"battle_id": "invented"}]
        self.assertTrue(autonomous_combat_invariant(state))
        with self.assertRaises(ValueError):
            self.bridge.kernel.restore_checkpoint(state, self.rng, expected_revision=self.bridge.kernel.state.revision)
