from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.systems import campus_combat_invariant
from tests.test_campus_combat_deployment import execute
from tests.test_campus_combat_rounds import deploy_and_start


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


def card_with_effect(battle: dict, effect_id: str) -> tuple[str, dict]:
    for instance_id in battle["shared_hand_ids"]:
        instance = battle["card_instances"][instance_id]
        if effect_id in instance["effect_ids"]:
            return instance_id, instance
    raise AssertionError(f"current hand has no {effect_id} card")


class CampusCombatActionTests(unittest.TestCase):
    def test_night_task_builds_contract_valid_enemy_in_its_configured_row(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        self.assertEqual(1, len(battle["enemy_units"]))
        enemy_id, enemy = next(iter(battle["enemy_units"].items()))
        schema = json.loads(
            (REPOSITORY_DIR / "contracts/combat_enemy_unit.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(set(schema["required"]), set(enemy))
        self.assertIn(enemy_id, battle["enemy_formations"][enemy["row"]])
        task = bridge.kernel._state.tasks[battle["situation_id"]]
        self.assertEqual(task["enemy_archetype_id"], enemy["archetype_id"])
        self.assertEqual(enemy["max_health"], battle["enemy_health"][enemy_id])
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel.state)))

    def test_play_card_spends_shared_points_moves_card_and_applies_damage_atomically(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        card_id, card = card_with_effect(battle, "specialization_effect")
        enemy_id = battle["action_options"]["cards"][card_id]["target_ids"][0]
        before_health = battle["enemy_health"][enemy_id]
        before_points = battle["command_points"]["party:player"]
        result = execute(bridge, "PLAY_COMBAT_CARD", {
            "battle_id": battle["battle_id"],
            "expected_battle_revision": battle["revision"],
            "card_instance_id": card_id,
            "target_ids": [enemy_id],
        }, marker="play-card")
        self.assertTrue(result["ok"], result)
        updated = result["snapshot"]["combat"]["active_battle"]
        self.assertEqual(before_points - card["command_cost"], updated["command_points"]["party:player"])
        self.assertLess(updated["enemy_health"][enemy_id], before_health)
        self.assertNotIn(card_id, updated["shared_hand_ids"])
        self.assertIn(card_id, updated["discard_piles"]["player"])
        self.assertEqual("discard", updated["card_instances"][card_id]["zone"])
        event = next(
            item for item in result["result"]["events"]
            if item["event_type"] == "COMBAT_CARD_PLAYED"
        )
        self.assertEqual(card_id, event["payload"]["card_instance_id"])
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel.state)))

    def test_invalid_target_rejects_without_mutating_battle(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        card_id = battle["shared_hand_ids"][0]
        stored_before = deepcopy(bridge.kernel._state.battles[battle["battle_id"]])
        result = execute(bridge, "PLAY_COMBAT_CARD", {
            "battle_id": battle["battle_id"],
            "expected_battle_revision": battle["revision"],
            "card_instance_id": card_id,
            "target_ids": ["player"],
        }, marker="invalid-card-target")
        self.assertFalse(result["ok"])
        self.assertEqual("invalid_combat_target", result["result"]["code"])
        self.assertEqual(stored_before, bridge.kernel._state.battles[battle["battle_id"]])

    def test_observe_reveals_weakness_and_base_command_is_once_per_actor_each_round(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        option = battle["action_options"]["base_commands"]["player"]
        self.assertEqual("basic_observe", option["base_command_id"])
        enemy_id = option["target_ids"][0]
        used = execute(bridge, "USE_COMBAT_BASE_COMMAND", {
            "battle_id": battle["battle_id"],
            "expected_battle_revision": battle["revision"],
            "source_actor_id": "player",
            "target_ids": [enemy_id],
        }, marker="base-observe")
        self.assertTrue(used["ok"], used)
        updated = used["snapshot"]["combat"]["active_battle"]
        self.assertIn("player", updated["base_command_used_actor_ids"])
        self.assertTrue(any(value.startswith(enemy_id + ":") for value in updated["known_weaknesses"]))
        self.assertFalse(updated["action_options"]["base_commands"]["player"]["playable"])
        blocked = execute(bridge, "USE_COMBAT_BASE_COMMAND", {
            "battle_id": updated["battle_id"],
            "expected_battle_revision": updated["revision"],
            "source_actor_id": "player",
            "target_ids": [enemy_id],
        }, marker="base-observe-twice")
        self.assertFalse(blocked["ok"])
        self.assertEqual("base_command_already_used", blocked["result"]["code"])
        advanced = execute(bridge, "END_COMBAT_ROUND", {
            "battle_id": updated["battle_id"],
            "expected_battle_revision": updated["revision"],
        }, marker="base-next-round")
        self.assertTrue(advanced["ok"], advanced)
        self.assertTrue(
            advanced["snapshot"]["combat"]["active_battle"]["action_options"]
            ["base_commands"]["player"]["playable"]
        )

    def test_support_effects_use_the_same_pipeline_and_respect_maximums(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        stored = bridge.kernel._state.battles[battle["battle_id"]]
        player_card = next(
            card for card in stored["character_cards"].values()
            if card["actor_id"] == "player"
        )
        stored["focus"]["player"] = player_card["max_focus"] - 10
        # Force the existing base command through the same data-driven support
        # blueprint while keeping the authoritative per-round limit intact.
        player_card["base_command_id"] = "basic_coordinate"
        battle = bridge.snapshot()["combat"]["active_battle"]
        option = battle["action_options"]["base_commands"]["player"]
        result = execute(bridge, "USE_COMBAT_BASE_COMMAND", {
            "battle_id": battle["battle_id"],
            "expected_battle_revision": battle["revision"],
            "source_actor_id": "player",
            "target_ids": ["player"],
        }, marker="base-coordinate")
        self.assertTrue(result["ok"], result)
        updated = result["snapshot"]["combat"]["active_battle"]
        self.assertGreater(updated["focus"]["player"], player_card["max_focus"] - 10)
        self.assertLessEqual(updated["focus"]["player"], player_card["max_focus"])
        self.assertEqual("basic_coordinate", option["base_command_id"])

    def test_insufficient_points_rejects_before_card_or_effect_mutation(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        stored = bridge.kernel._state.battles[battle["battle_id"]]
        stored["command_points"]["party:player"] = 0
        snapshot = bridge.snapshot()["combat"]["active_battle"]
        card_id = snapshot["shared_hand_ids"][0]
        enemy_id = next(iter(snapshot["enemy_units"]))
        before = deepcopy(stored)
        result = execute(bridge, "PLAY_COMBAT_CARD", {
            "battle_id": snapshot["battle_id"],
            "expected_battle_revision": snapshot["revision"],
            "card_instance_id": card_id,
            "target_ids": [enemy_id],
        }, marker="no-points")
        self.assertFalse(result["ok"])
        self.assertEqual("insufficient_command_points", result["result"]["code"])
        self.assertEqual(before, bridge.kernel._state.battles[battle["battle_id"]])

    def test_final_damage_resolves_battle_and_completes_the_locked_task(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        card_id = battle["shared_hand_ids"][0]
        enemy_id = next(iter(battle["enemy_units"]))
        bridge.kernel._state.battles[battle["battle_id"]]["enemy_health"][enemy_id] = 1
        result = execute(bridge, "PLAY_COMBAT_CARD", {
            "battle_id": battle["battle_id"],
            "expected_battle_revision": battle["revision"],
            "card_instance_id": card_id,
            "target_ids": [enemy_id],
        }, marker="winning-card")
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["result"]["payload"]["battle_resolved"])
        self.assertIsNone(result["snapshot"]["combat"]["active_battle"])
        stored = bridge.kernel._state.battles[battle["battle_id"]]
        self.assertEqual("resolved", stored["phase"])
        self.assertEqual("victory", stored["result"])
        self.assertEqual("completed", bridge.kernel._state.tasks[battle["situation_id"]]["state"])
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel.state)))


if __name__ == "__main__":
    unittest.main()
