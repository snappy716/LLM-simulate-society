from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_combat import campus_combat_invariant
from simulation.systems.campus_vitals import change_vital
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_combat_deployment import execute
from tests.test_campus_combat_rounds import deploy_and_start


class CampusEnemyTurnTests(unittest.TestCase):
    def setUp(self):
        self.bridge = CampusKernelBridge(42)
        self.battle = deploy_and_start(self.bridge)

    def end_round(self):
        battle = self.bridge.snapshot()["combat"]["active_battle"]
        result = execute(self.bridge, "END_COMBAT_ROUND", {"battle_id": battle["battle_id"], "expected_battle_revision": battle["revision"]})
        self.assertTrue(result["ok"], result["result"]["code"])
        return result

    def test_intent_is_visible_and_damage_persists_in_world(self):
        self.assertTrue(self.battle["enemy_intents"])
        before = self.bridge.kernel.state.population["player"]["vitals"]["health"]
        result = self.end_round()
        damage = result["result"]["payload"]["enemy_results"][0]["damage"]
        self.assertGreater(damage, 0)
        self.assertEqual(before - damage, self.bridge.kernel.state.population["player"]["vitals"]["health"])
        self.assertEqual(2, next(iter(result["snapshot"]["combat"]["active_battle"]["enemy_intents"].values()))["round"])
        self.assertEqual([], list(campus_combat_invariant(self.bridge.kernel.state)))

    def test_guard_absorbs_damage_and_expires_after_enemy_turn(self):
        stored = self.bridge.kernel._state.battles[self.battle["battle_id"]]
        stored["barriers"]["player"] = 100
        before = self.bridge.kernel.state.population["player"]["vitals"]["health"]
        result = self.end_round()
        effect = result["result"]["payload"]["enemy_results"][0]
        self.assertEqual(0, effect["damage"])
        self.assertGreater(effect["absorbed"], 0)
        self.assertEqual(before, self.bridge.kernel.state.population["player"]["vitals"]["health"])
        self.assertEqual(0, self.bridge.kernel.state.battles[self.battle["battle_id"]]["barriers"]["player"])

    def test_disruption_weakens_one_attack_then_is_removed(self):
        enemy_id = next(iter(self.battle["enemy_units"]))
        stored = self.bridge.kernel._state.battles[self.battle["battle_id"]]
        stored["enemy_units"][enemy_id]["statuses"].append("disrupted")
        first = self.end_round()["result"]["payload"]["enemy_results"][0]
        second = self.end_round()["result"]["payload"]["enemy_results"][0]
        self.assertTrue(first["disrupted"])
        self.assertFalse(second["disrupted"])
        self.assertLess(first["damage"], second["damage"])

    def test_reposition_out_of_announced_row_causes_miss_without_retarget(self):
        card_id = next(iter(self.battle["character_cards"]))
        result = execute(self.bridge, "REPOSITION_COMBAT_CHARACTER", {
            "battle_id": self.battle["battle_id"], "expected_battle_revision": self.battle["revision"],
            "character_card_instance_id": card_id, "destination_row": "back",
        })
        self.assertTrue(result["ok"], result["result"]["code"])
        self.assertTrue(self.end_round()["result"]["payload"]["enemy_results"][0]["missed"])

    def test_defeat_fails_task_and_advances_world_to_full_recovery_next_morning(self):
        change_vital(self.bridge.kernel._state, "player", "health", -10000)
        # Keep one HP so the actual enemy attack causes the defeat.
        change_vital(self.bridge.kernel._state, "player", "health", 1)
        change_vital(self.bridge.kernel._state, "player", "focus", -10)
        before_items = deepcopy(self.bridge.kernel.state.inventories["actors"]["player"])
        result = self.end_round()
        self.assertEqual("defeat", result["result"]["payload"]["result"])
        state = self.bridge.kernel.state
        self.assertEqual((2, "morning"), (state.clock.day, state.clock.phase))
        self.assertIsNone(result["snapshot"]["combat"]["active_battle"])
        self.assertEqual("failed", state.tasks[self.battle["situation_id"]]["state"])
        self.assertTrue(any(h.get("kind") == "failed" and h.get("message") for h in state.tasks[self.battle["situation_id"]]["history"]))
        self.assertNotIn("active_forum_task_id", state.population["player"])
        actor = state.population["player"]
        self.assertEqual(actor["home_location_id"], actor["current_location_id"])
        self.assertEqual(actor["vitals"]["max_health"], actor["vitals"]["health"])
        self.assertEqual(actor["vitals"]["max_focus"], actor["vitals"]["focus"])
        self.assertEqual(before_items, state.inventories["actors"]["player"])
        self.assertEqual(1, state.action_economy["actors"]["player"]["major_remaining"])
        self.assertTrue(state.battles[self.battle["battle_id"]]["consequences"]["rescue"]["recovered"])
        events = [e["event_type"] for e in result["result"]["events"]]
        self.assertIn("COMBAT_CHARACTER_INCAPACITATED", events)
        self.assertIn("COMBAT_OVERNIGHT_RECOVERY", events)

    def test_old_active_save_projects_intents_without_mutating_and_can_continue(self):
        self.bridge.kernel._state.battles[self.battle["battle_id"]]["enemy_intents"] = {}
        before = deepcopy(self.bridge.kernel.state.battles)
        self.assertTrue(self.bridge.snapshot()["combat"]["active_battle"]["enemy_intents"])
        self.assertEqual(before, self.bridge.kernel.state.battles)
        self.assertTrue(self.end_round()["result"]["payload"]["enemy_results"])

    def test_save_restore_replays_same_enemy_result(self):
        state, rng = self.bridge.kernel.capture_checkpoint()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "battle.json"
            save_kernel_checkpoint(path, state, rng)
            loaded = load_kernel_checkpoint(path)
        first = self.end_round()["result"]["payload"]["enemy_results"]
        self.bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=self.bridge.kernel.state.revision)
        second = self.end_round()["result"]["payload"]["enemy_results"]
        self.assertEqual(first, second)

    def test_stale_round_request_does_not_damage_twice(self):
        self.end_round()
        before = deepcopy(self.bridge.kernel.state.population["player"]["vitals"])
        result = execute(self.bridge, "END_COMBAT_ROUND", {
            "battle_id": self.battle["battle_id"], "expected_battle_revision": self.battle["revision"],
        }, marker="stale-enemy")
        self.assertFalse(result["ok"])
        self.assertEqual(before, self.bridge.kernel.state.population["player"]["vitals"])

    def test_three_person_defeat_exhausts_downed_cards_then_recovers_whole_party(self):
        self.bridge = CampusKernelBridge(46)
        self.battle = deploy_and_start(self.bridge, teammate_count=2)
        ids = self.battle["participant_ids"]
        self.assertEqual(3, len(ids))
        for actor_id in ids:
            state = self.bridge.kernel._state
            change_vital(state, actor_id, "health", 1 - state.population[actor_id]["vitals"]["health"])
        first = self.end_round()
        active = first["snapshot"]["combat"]["active_battle"]
        self.assertEqual("evening", first["snapshot"]["clock"]["phase"])
        self.assertTrue(all(active["card_instances"][card_id]["owner_actor_id"] != "player" for card_id in active["shared_hand_ids"]))
        self.end_round()
        result = self.end_round()
        self.assertEqual("defeat", result["result"]["payload"]["result"])
        state = self.bridge.kernel.state
        for actor_id in ids:
            actor = state.population[actor_id]
            self.assertEqual(actor["vitals"]["max_health"], actor["vitals"]["health"])
            self.assertEqual(actor["home_location_id"], actor["current_location_id"])
        self.assertEqual([], list(campus_combat_invariant(state)))

    def test_pending_rescue_hook_does_not_itself_fast_forward_global_clock(self):
        # The shared resolver never owns the global clock. The player-facing
        # handler alone performs overnight progression; NPC background runners
        # can call the same resolver and wait for natural world advancement.
        from simulation.actions import SimulationCommand
        from simulation.systems.transactions import TransactionContext
        from simulation.systems.campus_enemy_turns import resolve_enemy_turn, recovering_from_defeat, recover_defeated_parties
        state, rng = self.bridge.kernel.capture_checkpoint()
        change_vital(state, "player", "health", 1 - state.population["player"]["vitals"]["health"])
        context = TransactionContext(state, rng, SimulationCommand(command_id="background-resolver-boundary", actor_id="player", action_id="END_COMBAT_ROUND", expected_world_revision=state.revision))
        resolve_enemy_turn(context, state.battles[self.battle["battle_id"]])
        self.assertEqual((1, "evening"), (state.clock.day, state.clock.phase))
        self.assertTrue(recovering_from_defeat(state, "player"))
        recover_defeated_parties(context)
        self.assertEqual(0, state.population["player"]["vitals"]["health"])

    def test_corrupt_intent_or_rescue_is_rejected_by_runtime_invariants(self):
        state = self.bridge.kernel.state
        battle = state.battles[self.battle["battle_id"]]
        next(iter(battle["enemy_intents"].values()))["power"] = -1
        self.assertTrue(list(campus_combat_invariant(state)))
        next(iter(battle["enemy_intents"].values()))["power"] = 20
        battle["consequences"]["rescue"] = {"recover_day": True, "actor_ids": [], "recovered": False}
        self.assertTrue(list(campus_combat_invariant(state)))
