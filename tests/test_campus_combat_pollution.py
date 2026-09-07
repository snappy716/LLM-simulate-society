from __future__ import annotations

import json
import unittest
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.systems import campus_combat_invariant
from tests.test_campus_combat_deployment import execute
from tests.test_campus_combat_rounds import deploy_and_start


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class CampusCombatPollutionTests(unittest.TestCase):
    def test_malformed_status_and_pollution_are_rejected_without_crashing_validator(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        before, rng = bridge.kernel.capture_checkpoint()
        for field, value in (("statuses", [{"unhashable": True}]), ("statuses", [1]),
                             ("pollution", "not-a-number"), ("pollution", None)):
            with self.subTest(field=field, value=value):
                corrupted = before.clone()
                corrupted.battles[battle["battle_id"]][field]["player"] = value
                self.assertTrue(list(campus_combat_invariant(corrupted)))
                with self.assertRaises(ValueError):
                    bridge.kernel.restore_checkpoint(corrupted, rng, expected_revision=before.revision)
                self.assertEqual(before.to_dict(), bridge.kernel.state.to_dict())
                self.assertEqual(rng.snapshot(), bridge.kernel.rng_snapshot)

    def _end_round(self, bridge, battle, marker):
        return execute(bridge, "END_COMBAT_ROUND", {
            "battle_id": battle["battle_id"],
            "expected_battle_revision": battle["revision"],
        }, marker=marker)

    def _set_pollution(self, bridge, battle_id, value):
        bridge.kernel._state.battles[battle_id]["pollution"]["player"] = value
        bridge.kernel._state.situations["night_world"]["actor_states"]["player"][
            "pollution"
        ] = value
        from simulation.systems.campus_combat import sync_combat_pollution_status
        sync_combat_pollution_status(bridge.kernel._state.battles[battle_id], "player")

    def test_enemy_intent_and_unit_expose_data_driven_pollution_threat(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        enemy_id, enemy = next(iter(battle["enemy_units"].items()))
        intent = battle["enemy_intents"][enemy_id]
        self.assertEqual(enemy["pollution_power"], intent["pollution_power"])
        self.assertGreater(intent["pollution_power"], 0)
        schema = json.loads((
            REPOSITORY_DIR / "contracts/combat_enemy_unit.schema.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), set(enemy))

    def test_unblocked_hit_persists_pollution_and_enters_visible_stage(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        self._set_pollution(bridge, battle["battle_id"], 29)
        battle = bridge.snapshot()["combat"]["active_battle"]

        result = self._end_round(bridge, battle, "pollution-threshold")

        effect = result["result"]["payload"]["enemy_results"][0]
        self.assertGreater(effect["pollution_gain"], 0)
        after = effect["pollution_after"]
        self.assertGreaterEqual(after, 30)
        self.assertEqual(
            after,
            bridge.kernel._state.situations["night_world"]["actor_states"]["player"]["pollution"],
        )
        active = result["snapshot"]["combat"]["active_battle"]
        self.assertIn("pollution_noticeable", active["statuses"]["player"])
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel.state)))

    def test_high_pollution_adds_readable_damage_risk(self):
        stable, severe = CampusKernelBridge(42), CampusKernelBridge(42)
        stable_battle, severe_battle = deploy_and_start(stable), deploy_and_start(severe)
        self._set_pollution(severe, severe_battle["battle_id"], 60)
        severe_battle = severe.snapshot()["combat"]["active_battle"]

        stable_hit = self._end_round(stable, stable_battle, "pollution-stable")["result"]["payload"]["enemy_results"][0]
        severe_hit = self._end_round(severe, severe_battle, "pollution-severe")["result"]["payload"]["enemy_results"][0]

        self.assertEqual(0, stable_hit["pollution_damage_bonus"])
        self.assertEqual(3, severe_hit["pollution_damage_bonus"])
        self.assertEqual(stable_hit["damage"] + 3, severe_hit["damage"])

    def test_full_guard_prevents_both_damage_and_contact_pollution(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        stored = bridge.kernel._state.battles[battle["battle_id"]]
        before = stored["pollution"]["player"]
        stored["barriers"]["player"] = 999
        battle = bridge.snapshot()["combat"]["active_battle"]

        result = self._end_round(bridge, battle, "pollution-guard")

        effect = result["result"]["payload"]["enemy_results"][0]
        self.assertEqual(0, effect["damage"])
        self.assertEqual(0, effect["pollution_gain"])
        self.assertEqual(before, effect["pollution_after"])

    def test_purification_effect_reduces_persistent_pollution_and_stage(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        self._set_pollution(bridge, battle["battle_id"], 35)
        stored = bridge.kernel._state.battles[battle["battle_id"]]
        card_id = stored["shared_hand_ids"][0]
        card = stored["card_instances"][card_id]
        card.update({
            "source_ability_id": "pollution_purification",
            "target": "self_or_ally", "range_pattern": "any_ally",
            "effect_ids": ["reduce_pollution"], "base_power": 8,
        })
        battle = bridge.snapshot()["combat"]["active_battle"]

        result = execute(bridge, "PLAY_COMBAT_CARD", {
            "battle_id": battle["battle_id"],
            "expected_battle_revision": battle["revision"],
            "card_instance_id": card_id, "target_ids": ["player"],
        }, marker="pollution-purify")

        self.assertTrue(result["ok"], result)
        effect = result["result"]["payload"]["effects"][0]
        self.assertEqual("reduce_pollution", effect["effect_id"])
        self.assertLess(effect["after"], effect["before"])
        self.assertEqual(
            effect["after"],
            bridge.kernel._state.situations["night_world"]["actor_states"]["player"]["pollution"],
        )
        self.assertNotIn(
            "pollution_noticeable",
            result["snapshot"]["combat"]["active_battle"]["statuses"]["player"],
        )

    def test_content_blueprint_gives_biochemistry_real_purification(self):
        bridge = CampusKernelBridge(42)
        blueprint = bridge.kernel.state.metadata["campus_abilities"]["card_blueprints"][
            "college:pollution_purification"
        ]
        self.assertIn("restore_focus", blueprint["effect_ids"])
        self.assertIn("reduce_pollution", blueprint["effect_ids"])


if __name__ == "__main__":
    unittest.main()
