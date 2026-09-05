from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems.transactions import TransactionContext, TransactionOutcome
from simulation.systems.randomness import DeterministicRngPool
from simulation.systems.campus_vitals import change_vital, campus_vitals_invariant, recovery_skills
from simulation.systems.campus_combat import _new_battle, combat_policy_from_state, resolve_combat_effects, _persist_recovery_effects, _finish_victory
from simulation.systems.campus_locations import load_campus_location_graph
from simulation.systems.content_registry import ContentRegistry
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint, CheckpointError
from tests.test_campus_combat_deployment import execute, enter_with_owned_night_task
from tests.test_campus_combat_rounds import deploy_and_start


class CampusVitalsTests(unittest.TestCase):
    def setUp(self):
        self.bridge = CampusKernelBridge(42)
        self.state = self.bridge.kernel._state

    def wound(self, amount=60, actor_id="player"):
        return change_vital(self.state, actor_id, "health", -amount)

    def home(self):
        self.state.population["player"]["current_location_id"] = self.state.population["player"]["home_location_id"]

    def medicine(self):
        self.state.inventories["actors"]["player"]["quantities"]["bandage_roll"] = 2

    def test_every_actor_has_full_initial_resources(self):
        self.assertEqual(201, len(self.state.population))
        for actor in self.state.population.values():
            self.assertEqual(actor["vitals"]["health"], actor["vitals"]["max_health"])
        self.assertEqual([], list(campus_vitals_invariant(self.state)))

    def test_surface_home_rest_fully_recovers_hp_and_focus_once_budget(self):
        self.home()
        self.wound()
        change_vital(self.state, "player", "focus", -20)
        clock, inventory = self.state.clock.to_dict() if hasattr(self.state.clock, "to_dict") else vars(self.state.clock).copy(), self.state.inventories.copy()
        result = execute(self.bridge, "REST")
        self.assertTrue(result["ok"], result)
        player = result["snapshot"]["player"]
        self.assertEqual(player["vitals"]["max_health"], player["vitals"]["health"])
        self.assertEqual(player["vitals"]["max_focus"], player["vitals"]["focus"])
        self.assertEqual(0, player["action_budget"]["major_remaining"])
        self.assertEqual(clock, result["snapshot"]["clock"])
        self.assertEqual(inventory, self.bridge.kernel.state.inventories)

    def test_no_major_budget_does_not_restore(self):
        self.home()
        self.wound()
        self.state.action_economy["actors"]["player"]["major_remaining"] = 0
        before = self.state.population["player"]["vitals"].copy()
        result = execute(self.bridge, "REST")
        self.assertFalse(result["ok"])
        self.assertEqual(before, self.bridge.kernel.state.population["player"]["vitals"])

    def test_rest_outside_home_does_not_heal(self):
        self.wound()
        before = self.state.population["player"]["vitals"].copy()
        result = execute(self.bridge, "REST")
        self.assertTrue(result["ok"])
        self.assertEqual(before, self.bridge.kernel.state.population["player"]["vitals"])

    def test_night_rest_and_return_do_not_heal(self):
        execute(self.bridge, "ADVANCE_PHASE")
        execute(self.bridge, "ADVANCE_PHASE")
        self.assertTrue(execute(self.bridge, "ENTER_NIGHT_WORLD")["ok"])
        self.state = self.bridge.kernel._state
        self.home()
        self.wound()
        hp = self.state.population["player"]["vitals"]["health"]
        self.assertTrue(execute(self.bridge, "REST")["ok"])
        self.assertEqual(hp, self.bridge.kernel.state.population["player"]["vitals"]["health"])
        self.assertTrue(execute(self.bridge, "EXIT_NIGHT_WORLD")["ok"])
        self.assertEqual(hp, self.bridge.kernel.state.population["player"]["vitals"]["health"])
        self.assertTrue(execute(self.bridge, "REST")["ok"])
        vitals = self.bridge.kernel.state.population["player"]["vitals"]
        self.assertEqual(vitals["max_health"], vitals["health"])

    def test_bandage_heals_persistent_health_and_consumes_exactly_one(self):
        self.medicine()
        self.wound()
        before = self.state.population["player"]["vitals"]["health"]
        result = execute(self.bridge, "USE_ITEM", {"item_id": "bandage_roll"})
        self.assertTrue(result["ok"])
        self.assertGreater(result["snapshot"]["player"]["vitals"]["health"], before)
        self.assertEqual(1, result["snapshot"]["economy"]["inventory"]["quantities"]["bandage_roll"])
        self.assertEqual(1, result["snapshot"]["player"]["action_budget"]["major_remaining"])

    def test_full_health_does_not_consume_medicine(self):
        self.medicine()
        result = execute(self.bridge, "USE_ITEM", {"item_id": "bandage_roll"})
        self.assertFalse(result["ok"])
        self.assertEqual(2, result["snapshot"]["economy"]["inventory"]["quantities"]["bandage_roll"])

    def test_bandage_can_treat_colocated_npc_not_remote(self):
        self.medicine()
        target = "campus_student_001"
        self.wound(actor_id=target)
        params = {"item_id":"bandage_roll", "target_id":target}
        self.assertFalse(execute(self.bridge, "USE_ITEM", params)["ok"])
        self.bridge.kernel._state.population[target]["current_location_id"] = self.bridge.kernel._state.population["player"]["current_location_id"]
        self.assertTrue(execute(self.bridge, "USE_ITEM", params, marker="colocated-treatment")["ok"])

    def test_new_encounters_keep_health_focus_and_victory_does_not_heal(self):
        deploy_and_start(self.bridge)
        self.state = self.bridge.kernel._state
        battle = next(value for value in self.state.battles.values() if value["result"] == "active")
        task = self.state.tasks[battle["situation_id"]].copy()
        self.wound(30)
        change_vital(self.state, "player", "focus", -15)
        before = self.state.population["player"]["vitals"].copy()
        for enemy_id in battle["enemy_health"]:
            battle["enemy_health"][enemy_id] = 0
        command = SimulationCommand("victory-fixture", "player", "TEST", self.state.revision)
        context = TransactionContext(self.state, DeterministicRngPool(42), command)
        self.assertTrue(_finish_victory(context, battle))
        self.assertEqual(before, self.state.population["player"]["vitals"])
        registry = ContentRegistry.load_default(Path(__file__).parents[1] / "content")
        second = _new_battle(self.state, "player", task, combat_policy_from_state(self.state), load_campus_location_graph(registry))
        self.assertEqual(before["health"], second["health"]["player"])
        self.assertEqual(before["focus"], second["focus"]["player"])

    def test_combat_heal_changes_persistent_state_and_projection(self):
        deploy_and_start(self.bridge)
        self.state = self.bridge.kernel._state
        battle = next(value for value in self.state.battles.values() if value["result"] == "active")
        self.wound(40)
        before = self.state.population["player"]["vitals"]["health"]
        command = SimulationCommand("healing-fixture", "player", "TEST", self.state.revision)
        context = TransactionContext(self.state, DeterministicRngPool(42), command)
        effects = resolve_combat_effects(battle, "player", {"effect_ids":["restore_health"], "base_power":7}, "player")
        _persist_recovery_effects(context, effects)
        self.assertGreater(self.state.population["player"]["vitals"]["health"], before)
        self.assertEqual([], list(campus_vitals_invariant(self.state)))

    def test_preparation_cancel_does_not_restore(self):
        task = enter_with_owned_night_task(self.bridge)
        self.state = self.bridge.kernel._state
        self.wound(30)
        hp = self.state.population["player"]["vitals"]["health"]
        prepared = execute(self.bridge, "START_BATTLE_PREPARATION", {"task_id":task["task_id"]})
        self.assertTrue(prepared["ok"])
        battle = prepared["snapshot"]["combat"]["active_battle"]
        self.assertFalse(execute(self.bridge, "REST")["ok"])
        self.assertTrue(execute(self.bridge, "CANCEL_BATTLE_PREPARATION", {"battle_id":battle["battle_id"]}, marker="cancel")["ok"])
        self.assertEqual(hp, self.bridge.kernel.state.population["player"]["vitals"]["health"])

    def test_field_skill_requires_real_ability_and_focus(self):
        caster = next(key for key in self.state.population if recovery_skills(self.state, key))
        self.state.population[caster]["current_location_id"] = self.state.population["player"]["current_location_id"]
        self.wound()
        skill_id = recovery_skills(self.state, caster)[0]["card_id"]
        params = {"target_id":"player", "skill_id":skill_id}
        command = SimulationCommand("field-skill", caster, "USE_RECOVERY_SKILL", self.state.revision, parameters=params, source="rule")
        before = self.state.population[caster]["vitals"]["focus"]
        self.assertTrue(self.bridge.kernel.execute(command).success)
        after = self.bridge.kernel.state
        self.assertEqual(before - 10, after.population[caster]["vitals"]["focus"])
        self.assertTrue(self.bridge.kernel.execute(command).replayed)
        self.assertFalse(execute(self.bridge, "USE_RECOVERY_SKILL", {**params, "caster_id":caster})["ok"], "cannot control an unrelated NPC")

    def test_missing_skill_does_not_cost_focus(self):
        self.wound()
        before = self.state.population["player"]["vitals"].copy()
        self.assertFalse(execute(self.bridge, "USE_RECOVERY_SKILL", {"skill_id":"made-up"})["ok"])
        self.assertEqual(before, self.bridge.kernel.state.population["player"]["vitals"])

    def test_npc_rest_uses_same_full_recovery_and_major_budget(self):
        npc = "campus_student_001"
        actor = self.state.population[npc]
        actor["current_location_id"] = actor["home_location_id"]
        self.wound(actor_id=npc)
        command = SimulationCommand("npc-rest", npc, "REST", self.state.revision, source="rule")
        self.assertTrue(self.bridge.kernel.execute(command).success)
        after = self.bridge.kernel.state
        self.assertEqual(after.population[npc]["vitals"]["max_health"], after.population[npc]["vitals"]["health"])
        self.assertEqual(0, after.action_economy["actors"][npc]["major_remaining"])

    def test_field_skill_insufficient_focus_and_remote_target_rollback(self):
        caster = next(key for key in self.state.population if recovery_skills(self.state, key))
        skill_id = recovery_skills(self.state, caster)[0]["card_id"]
        self.wound(actor_id=caster)
        change_vital(self.state, caster, "focus", -10000)
        before = self.state.population[caster]["vitals"].copy()
        command = SimulationCommand("no-focus", caster, "USE_RECOVERY_SKILL", self.state.revision,
                                    parameters={"skill_id":skill_id}, source="rule")
        self.assertEqual("insufficient_focus", self.bridge.kernel.execute(command).code)
        self.assertEqual(before, self.bridge.kernel.state.population[caster]["vitals"])
        command = SimulationCommand("remote-heal", caster, "USE_RECOVERY_SKILL", self.state.revision,
                                    parameters={"skill_id":skill_id, "target_id":"player"}, source="rule")
        self.assertEqual("location_mismatch", self.bridge.kernel.execute(command).code)

    def test_failed_transaction_rolls_back_healing_inventory_and_budget(self):
        self.home()
        self.wound()
        before = self.state.to_dict()
        self.bridge.kernel.add_invariant(lambda state: ["forced regression failure"])
        with self.assertRaises(ValueError):
            execute(self.bridge, "REST")
        self.assertEqual(before, self.bridge.kernel.state.to_dict())

    def test_checkpoint_preserves_and_validates_vitals(self):
        self.wound()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "save.json"
            save_kernel_checkpoint(path, self.state, DeterministicRngPool(42))
            loaded = load_kernel_checkpoint(path)
            self.assertEqual(self.state.population["player"]["vitals"], loaded.state.population["player"]["vitals"])
            self.state.population["player"]["vitals"]["health"] = -1
            with self.assertRaises(CheckpointError):
                save_kernel_checkpoint(path, self.state, DeterministicRngPool(42))

    def test_vital_projection_drift_is_rejected(self):
        deploy_and_start(self.bridge)
        state = self.bridge.kernel._state
        battle = next(value for value in state.battles.values() if value["result"] == "active")
        battle["health"]["player"] -= 10
        self.assertTrue(list(campus_vitals_invariant(state)))


if __name__ == "__main__":
    unittest.main()
