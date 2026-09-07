"""Authoritative medicine use, hostile inputs and persistent resource accounting."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems.campus_combat import incapacitate_character
from simulation.systems.campus_vitals import change_vital
from tests.test_campus_combat_deployment import execute
from tests.test_campus_combat_rounds import deploy_and_start


class CampusCombatItemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(46)
        # Location fixture only; purchase and deployment use real commands.
        cls.bridge.kernel._state.population["player"]["current_location_id"] = "hospital_pharmacy"
        bought = execute(cls.bridge, "BUY_ITEM", {"item_id": "bandage_roll", "quantity": 3,
                                                "shop_id": "campus_pharmacy"})
        assert bought["ok"], bought
        deploy_and_start(cls.bridge, teammate_count=2)
        cls.baseline, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.counter = 0
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng,
                                             expected_revision=self.bridge.kernel.state.revision)
        self.battle_id = next(iter(self.bridge.kernel._state.battles))
        self.battle = self.bridge.kernel._state.battles[self.battle_id]
        self.members = list(self.battle["participant_ids"])
        self.middle = next(card["actor_id"] for card in self.battle["character_cards"].values()
                           if card["row"] == "middle")
        self.back = next(card["actor_id"] for card in self.battle["character_cards"].values()
                         if card["row"] == "back")
        change_vital(self.bridge.kernel._state, "player", "health", -60)

    def use(self, **params):
        self.counter += 1
        return execute(self.bridge, "USE_COMBAT_ITEM", {
            "battle_id": self.battle_id, "expected_battle_revision": self.battle["revision"],
            "item_id": "bandage_roll", "source_actor_id": "player", "target_id": "player", **params},
            marker=f"item-use-{self.counter}")

    def assert_failure_unchanged(self, code, **params):
        before, rng = self.bridge.kernel.capture_checkpoint()
        result = self.use(**params)
        self.assertFalse(result["ok"], result)
        self.assertEqual(code, result["result"]["code"])
        after, after_rng = self.bridge.kernel.capture_checkpoint()
        for field in ("inventories", "battles", "population", "action_economy", "clock", "revision"):
            self.assertEqual(getattr(before, field), getattr(after, field), field)
        self.assertEqual(rng.snapshot(), after_rng.snapshot())

    def test_real_purchased_stock_heals_and_spends_exactly_one_point_without_world_time(self):
        before = self.bridge.kernel.state
        result = self.use()
        self.assertTrue(result["ok"], result)
        after = self.bridge.kernel.state
        vitals = after.population["player"]["vitals"]
        amount = min(60, (vitals["max_health"] * 25 + 99) // 100)
        self.assertEqual(before.population["player"]["vitals"]["health"] + amount, vitals["health"])
        self.assertEqual(vitals["health"], after.battles[self.battle_id]["health"]["player"])
        self.assertEqual(2, after.inventories["actors"]["player"]["quantities"]["bandage_roll"])
        self.assertEqual(2, after.battles[self.battle_id]["command_points"]["party:player"])
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(before.action_economy, after.action_economy)
        self.assertEqual(before.battles[self.battle_id]["pollution"], after.battles[self.battle_id]["pollution"])
        self.assertEqual(1, sum(event["event_type"] == "COMBAT_ITEM_USED" for event in result["result"]["events"]))

    def test_adjacent_teammate_spends_own_last_bandage_not_player_stock(self):
        self.bridge.kernel._state.inventories["actors"][self.middle]["quantities"]["bandage_roll"] = 1
        result = self.use(source_actor_id=self.middle)
        self.assertTrue(result["ok"], result)
        inventory = self.bridge.kernel.state.inventories["actors"]
        self.assertNotIn("bandage_roll", inventory[self.middle]["quantities"])
        self.assertEqual(3, inventory["player"]["quantities"]["bandage_roll"])

    def test_preview_matches_effect_and_only_exposes_available_deployed_stock(self):
        options = self.bridge.snapshot()["combat"]["active_battle"]["action_options"]["items"]
        option = next(item for item in options if item["source_actor_id"] == "player")
        self.assertEqual(["player"], option["target_ids"])
        result = self.use()
        self.assertEqual(option["targets"][0]["heal_amount"], result["result"]["payload"]["health"]["delta"])
        self.assertTrue(all(item["source_actor_id"] in self.members for item in options))

    def test_full_health_and_nonadjacent_target_never_consume(self):
        self.assert_failure_unchanged("invalid_healing_target", target_id=self.middle)
        change_vital(self.bridge.kernel._state, self.back, "health", -30)
        self.assert_failure_unchanged("invalid_healing_target", target_id=self.back)

    def test_insufficient_stock_points_and_nonmedicine_never_consume(self):
        self.assert_failure_unchanged("item_missing", source_actor_id=self.middle)
        self.assert_failure_unchanged("item_not_combat_usable", item_id="bread_loaf")
        self.battle["command_points"]["party:player"] = 0
        self.assert_failure_unchanged("insufficient_command_points")
        options = self.bridge.snapshot()["combat"]["active_battle"]["action_options"]["items"]
        self.assertTrue(all(not option["playable"] for option in options))

    def test_invalid_quantity_identity_and_stale_revision(self):
        for quantity in (0, 2, True, "1"):
            self.assert_failure_unchanged("invalid_quantity", quantity=quantity)
        self.assert_failure_unchanged("invalid_target", target_id=[])
        self.assert_failure_unchanged("source_not_controlled", source_actor_id="outsider")
        self.assert_failure_unchanged("battle_revision_conflict", expected_battle_revision=-1)

    def test_enemy_phase_and_backpack_shortcut_rejected(self):
        self.battle["phase"] = "enemy_turn"
        self.assert_failure_unchanged("wrong_battle_phase")
        result = execute(self.bridge, "USE_ITEM", {"item_id": "bandage_roll"}, marker="backpack-shortcut")
        self.assertEqual("battle_locked", result["result"]["code"])

    def test_incapacitated_target_cannot_be_resurrected_by_bandage(self):
        context = SimpleNamespace(state=self.bridge.kernel._state, emit=lambda *args, **kwargs: None)
        card_id = next(key for key, card in self.battle["character_cards"].items() if card["actor_id"] == self.middle)
        incapacitate_character(context, self.battle, card_id)
        self.assert_failure_unchanged("invalid_healing_target", target_id=self.middle)
        self.assert_failure_unchanged("source_not_controlled", source_actor_id=self.middle)

    def test_duplicate_request_and_checkpoint_restore_do_not_repeat_consumption(self):
        snapshot = self.bridge.snapshot()
        command = {"command_id": "combat-item-idempotent", "actor_id": "player",
                   "action_id": "USE_COMBAT_ITEM", "target_ids": [], "source": "player",
                   "expected_world_revision": snapshot["revision"],
                   "issued_day": snapshot["clock"]["day"], "issued_phase": snapshot["clock"]["phase"],
                   "issued_minute": snapshot["clock"]["minute"],
                   "parameters": {"battle_id": self.battle_id, "item_id": "bandage_roll",
                                  "expected_battle_revision": self.battle["revision"]}}
        self.assertTrue(self.bridge.execute(command)["ok"])
        after, rng = self.bridge.kernel.capture_checkpoint()
        self.assertTrue(self.bridge.execute(command)["ok"])
        self.assertEqual(after.to_dict(), self.bridge.kernel.state.to_dict())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "battle.json"
            save_kernel_checkpoint(path, after, rng)
            loaded = load_kernel_checkpoint(path, expected_content_version=after.content_version)
            self.bridge.kernel.restore_checkpoint(loaded.state, loaded.rng,
                                                 expected_revision=self.bridge.kernel.state.revision)
            restored = self.bridge.kernel.state
            self.assertTrue(self.bridge.execute(command)["ok"])
            self.assertEqual(restored.to_dict(), self.bridge.kernel.state.to_dict())

    def test_stale_clock_and_impersonation_rejected(self):
        snapshot = self.bridge.snapshot()
        command = {"command_id": "item-stale-clock", "actor_id": "player",
                   "action_id": "USE_COMBAT_ITEM", "target_ids": [], "source": "player",
                   "expected_world_revision": snapshot["revision"], "issued_day": 2,
                   "issued_minute": snapshot["clock"]["minute"],
                   "issued_phase": snapshot["clock"]["phase"],
                   "parameters": {"battle_id": self.battle_id, "item_id": "bandage_roll"}}
        before = self.bridge.kernel.state.inventories
        result = self.bridge.execute(command)
        self.assertFalse(result["ok"])
        command.update(command_id="item-impersonation", actor_id=self.middle, issued_day=1)
        result = self.bridge.execute(command)
        self.assertFalse(result["ok"])
        self.assertEqual(before, self.bridge.kernel.state.inventories)


if __name__ == "__main__":
    unittest.main()
