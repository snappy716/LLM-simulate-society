from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems.campus_inventory import (
    CAMPUS_ITEM_ACTIONS, campus_inventory_invariant, campus_inventory_view,
    install_campus_inventory, make_campus_inventory_handler,
)
from simulation.systems.content_registry import ContentRegistry
from simulation.systems.randomness import DeterministicRngPool
from simulation.systems.transactions import WorldKernel, RevisionConflictError


class CampusInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = CampusKernelBridge(42).kernel.state

    def setUp(self):
        self.state = self.baseline.clone()
        self.state.population["player"]["current_location_id"] = "supermarket_sales_floor"
        self.kernel = self.make_kernel(self.state)
        self.counter = 0

    @staticmethod
    def make_kernel(state, rng=None):
        kernel = WorldKernel(state, rng=rng)
        kernel.add_invariant(campus_inventory_invariant)
        for action in CAMPUS_ITEM_ACTIONS:
            kernel.register_handler(action, make_campus_inventory_handler())
        return kernel

    def command(self, action, *, actor="player", **params):
        self.counter += 1
        return SimulationCommand(str(self.counter), actor, action, self.kernel.state.revision,
                                 parameters={"item_id":"bread_loaf", "shop_id":"campus_market", **params},
                                 issued_day=self.kernel.state.clock.day, issued_phase=self.kernel.state.clock.phase,
                                 source="player" if actor == "player" else "rule")

    def run_action(self, action, **params):
        return self.kernel.execute(self.command(action, **params))

    def test_install_coverage_currency_and_catalog(self):
        self.assertEqual(201, len(self.state.inventories["actors"]))
        self.assertEqual(9, len(self.state.inventories["catalog"]))
        self.assertEqual("元", self.state.inventories["currency"])
        self.assertNotIn("wealth", self.state.inventories["actors"]["player"])
        self.assertEqual([], list(campus_inventory_invariant(self.state)))

    def test_reinstallation_cannot_replenish(self):
        registry = ContentRegistry.load_default(Path(__file__).parents[1] / "content")
        with self.assertRaises(ValueError):
            install_campus_inventory(self.state, registry)

    def test_buy_sell_atomic_conservation_free_time_and_budget(self):
        before = self.kernel.state
        self.assertTrue(self.run_action("BUY_ITEM", quantity=3).success)
        after = self.kernel.state
        self.assertEqual(488, after.population["player"]["wealth"])
        self.assertEqual(5, after.inventories["actors"]["player"]["quantities"]["bread_loaf"])
        self.assertEqual(197, after.inventories["shops"]["campus_market"]["quantities"]["bread_loaf"])
        self.assertEqual(3012, after.inventories["shops"]["campus_market"]["cash"])
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(before.action_economy, after.action_economy)
        self.assertTrue(self.run_action("SELL_ITEM", quantity=3).success)
        final = self.kernel.state
        self.assertEqual(3500, final.population["player"]["wealth"] + final.inventories["shops"]["campus_market"]["cash"])
        self.assertEqual(2, final.inventories["actors"]["player"]["quantities"]["bread_loaf"])

    def test_replay_does_not_buy_twice(self):
        command = self.command("BUY_ITEM")
        self.assertTrue(self.kernel.execute(command).success)
        before = self.kernel.state.to_dict()
        self.assertTrue(self.kernel.execute(command).replayed)
        self.assertEqual(before, self.kernel.state.to_dict())

    def test_stale_price_view_rejected(self):
        first, stale = self.command("BUY_ITEM"), self.command("BUY_ITEM")
        self.kernel.execute(first)
        with self.assertRaises(RevisionConflictError):
            self.kernel.execute(stale)

    def test_client_cannot_set_price_or_balance(self):
        result = self.run_action("BUY_ITEM", unit_price=0, total_price=0, balance=99999)
        self.assertEqual(4, result.payload["total_price"])
        self.assertEqual(496, self.kernel.state.population["player"]["wealth"])

    def assert_rollback(self, expected_code, action="BUY_ITEM", **params):
        before = self.kernel.state
        result = self.run_action(action, **params)
        self.assertFalse(result.success)
        self.assertEqual(expected_code, result.code)
        after = self.kernel.state
        self.assertEqual(before.inventories, after.inventories)
        self.assertEqual(before.population, after.population)
        self.assertEqual(before.revision, after.revision)
        self.assertEqual(before.event_sequence, after.event_sequence)

    def test_invalid_quantities_rollback(self):
        for qty in [0, -1, 1.5, True, "1", 1000, None, [], {}]:
            with self.subTest(qty=qty):
                self.assert_rollback("invalid_quantity", quantity=qty)

    def test_remote_purchase_rejected(self):
        self.kernel._state.population["player"]["current_location_id"] = "campus_gate_region"
        self.assert_rollback("location_mismatch")

    def test_shop_closed_rejected(self):
        self.kernel._state.clock.phase = "late_night"
        self.assert_rollback("shop_closed")

    def test_night_cannot_shop_surface(self):
        self.kernel._state.situations["night_world"]["actor_states"]["player"]["layer"] = "night"
        self.assert_rollback("location_mismatch")

    def test_insufficient_funds_stock_capacity_and_shop_cash(self):
        self.assert_rollback("insufficient_funds", quantity=150)
        self.kernel._state.inventories["shops"]["campus_market"]["quantities"]["bread_loaf"] = 1
        self.assert_rollback("item_missing", quantity=2)
        self.kernel._state.inventories["actors"]["player"]["max_weight"] = 1.1
        self.assert_rollback("inventory_full")
        self.kernel._state.inventories["shops"]["campus_market"]["cash"] = 0
        self.assert_rollback("insufficient_funds", "SELL_ITEM")

    def test_food_consumes_one_changes_real_need(self):
        before = self.kernel.state
        self.assertTrue(self.run_action("USE_ITEM").success)
        after = self.kernel.state
        self.assertEqual(0, after.population["player"]["needs"]["food"])
        self.assertEqual(1, after.inventories["actors"]["player"]["quantities"]["bread_loaf"])
        self.assertEqual(before.action_economy, after.action_economy)
        self.assertEqual(before.clock, after.clock)
        self.assert_rollback("no_effect", "USE_ITEM")

    def test_unsupported_item_effect_does_not_fake_success(self):
        self.assert_rollback("requires_other_system", "USE_ITEM", item_id="blank_notebook")

    def test_equip_protect_unequip_sell(self):
        self.assertTrue(self.run_action("BUY_ITEM", item_id="leather_gloves").success)
        self.assertTrue(self.run_action("EQUIP_ITEM", item_id="leather_gloves").success)
        self.assert_rollback("item_protected", "SELL_ITEM", item_id="leather_gloves")
        self.assert_rollback("slot_occupied", "EQUIP_ITEM", item_id="leather_gloves")
        self.assertTrue(self.run_action("UNEQUIP_ITEM", item_id="leather_gloves").success)
        self.assertTrue(self.run_action("SELL_ITEM", item_id="leather_gloves").success)

    def test_drop_pickup_same_layer_and_location(self):
        self.assertTrue(self.run_action("DROP_ITEM").success)
        self.kernel._state.situations["night_world"]["actor_states"]["player"]["layer"] = "night"
        self.assert_rollback("item_missing", "PICK_UP_ITEM")
        self.kernel._state.situations["night_world"]["actor_states"]["player"]["layer"] = "surface"
        self.assertTrue(self.run_action("PICK_UP_ITEM").success)
        self.assertEqual(2, self.kernel.state.inventories["actors"]["player"]["quantities"]["bread_loaf"])

    def test_give_requires_colocation_and_conserves_quantity(self):
        npc = next(key for key in self.state.population if key != "player")
        self.assert_rollback("location_mismatch", "GIVE_ITEM", target_id=npc)
        self.kernel._state.population[npc]["current_location_id"] = "supermarket_sales_floor"
        self.assertTrue(self.run_action("GIVE_ITEM", target_id=npc).success)
        actors = self.kernel.state.inventories["actors"]
        self.assertEqual(1, actors["player"]["quantities"]["bread_loaf"])
        self.assertEqual(3, actors[npc]["quantities"]["bread_loaf"])

    def test_npc_professional_tool_reserve(self):
        npc = next(key for key, actor in self.state.population.items() if actor["occupation_id"] == "medical_staff")
        self.kernel._state.population["player"]["current_location_id"] = self.state.population[npc]["current_location_id"]
        self.assertTrue(self.run_action("GIVE_ITEM", actor=npc, target_id="player", item_id="bandage_roll").success)
        self.assert_rollback("item_protected", "GIVE_ITEM", actor=npc, target_id="player", item_id="bandage_roll")

    def test_battle_cannot_bypass_item_costs(self):
        self.kernel._state.metadata["campus_combat"]["active_battle_by_actor"]["player"] = "test-battle"
        self.assert_rollback("battle_locked", "USE_ITEM")

    def test_snapshot_is_private_and_defensive(self):
        view = campus_inventory_view(self.kernel.state)
        self.assertNotIn("actors", view)
        view["inventory"]["quantities"].clear()
        self.assertTrue(self.kernel.state.inventories["actors"]["player"]["quantities"])

    def test_checkpoint_resume_preserves_inventory_and_replay(self):
        command = self.command("BUY_ITEM", quantity=2)
        self.kernel.execute(command)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checkpoint.json"
            save_kernel_checkpoint(path, self.kernel.state, DeterministicRngPool.from_snapshot(self.kernel.rng_snapshot))
            loaded = load_kernel_checkpoint(path)
            restored = self.make_kernel(loaded.state, loaded.rng)
            self.assertEqual(json.loads(json.dumps(self.kernel.state.to_dict())), restored.state.to_dict())
            self.assertTrue(restored.execute(command).replayed)
            self.assertEqual([], list(campus_inventory_invariant(restored.state)))

    def test_invariant_detects_invalid_equipment_negative_stock_and_money(self):
        for mutate in [
            lambda state: state.population["player"].update(wealth=-1),
            lambda state: state.inventories["actors"]["player"]["quantities"].update(bread_loaf=-1),
            lambda state: state.inventories["actors"]["player"]["equipped"].update(body="bread_loaf"),
        ]:
            state = self.state.clone()
            mutate(state)
            self.assertTrue(list(campus_inventory_invariant(state)))

    def test_bridge_economy_command_needs_no_old_world(self):
        from simulation.api.server import SimulationBridge
        bridge = SimulationBridge()
        self.assertFalse(hasattr(bridge, "world"))
        command = self.command("USE_ITEM")
        response = bridge.campus.execute(command.to_dict())
        self.assertTrue(response["ok"])
        self.assertFalse(hasattr(bridge, "world"))
        self.assertEqual(1, response["snapshot"]["economy"]["inventory"]["quantities"]["bread_loaf"])


if __name__ == "__main__":
    unittest.main()
