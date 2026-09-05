from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint, CheckpointError
from simulation.systems.campus_inventory import campus_inventory_invariant, campus_inventory_view
from simulation.systems.campus_supply import (
    install_campus_supply, receive_campus_supply, review_campus_supply,
    campus_supply_invariant, validate_supply_policy, supply_view,
)
from simulation.systems.content_registry import ContentRegistry
from simulation.systems.randomness import DeterministicRngPool
from simulation.systems.transactions import WorldKernel, TransactionOutcome


class CampusSupplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = CampusKernelBridge(42).kernel.state

    def setUp(self):
        state = self.baseline.clone()
        state.inventories["shops"]["campus_market"]["quantities"]["bread_loaf"] = 50
        self.kernel = self.make_kernel(state)
        self.sequence = 0

    @staticmethod
    def make_kernel(state, rng=None):
        kernel = WorldKernel(state, rng=rng)
        kernel.add_invariant(campus_inventory_invariant)
        def tick(context, command):
            if "day" in command.parameters:
                context.state.clock.day = command.parameters["day"]
            if "phase" in command.parameters:
                context.state.clock.phase = command.parameters["phase"]
            summary = receive_campus_supply(context)
            summary.update(review_campus_supply(context))
            return TransactionOutcome(True, True, "success", "test supply tick", commit=True, payload=summary)
        kernel.register_handler("TEST_SUPPLY_TICK", tick)
        return kernel

    def command(self, **params):
        self.sequence += 1
        state = self.kernel.state
        return SimulationCommand(f"supply-test:{self.sequence}", "player", "TEST_SUPPLY_TICK", state.revision,
                                 parameters=params, issued_day=state.clock.day, issued_phase=state.clock.phase)

    def run_tick(self, **params):
        return self.kernel.execute(self.command(**params))

    def test_install_does_not_create_goods_or_spend_money(self):
        self.assertEqual(0, self.baseline.inventories["supply"]["supplier_receipts"])
        self.assertEqual({}, self.baseline.inventories["supply"]["orders"])
        self.assertEqual(3000, self.baseline.inventories["shops"]["campus_market"]["cash"])

    def test_reinstall_rejected_without_resetting_ledger(self):
        before = self.kernel.state.to_dict()
        with self.assertRaises(ValueError):
            install_campus_supply(self.kernel._state, ContentRegistry.load_default(Path(__file__).parents[1] / "content"))
        self.assertEqual(before, self.kernel.state.to_dict())

    def test_order_transfers_only_shop_cash_not_player_cash_or_stock(self):
        before = self.kernel.state
        result = self.run_tick()
        self.assertEqual(1, result.payload["supply_orders"])
        after = self.kernel.state
        self.assertEqual(before.population, after.population)
        self.assertEqual(before.action_economy, after.action_economy)
        self.assertEqual(50, after.inventories["shops"]["campus_market"]["quantities"]["bread_loaf"])
        self.assertEqual(2550, after.inventories["shops"]["campus_market"]["cash"])
        self.assertEqual(450, after.inventories["supply"]["supplier_receipts"])
        order = next(iter(after.inventories["supply"]["orders"].values()))
        self.assertEqual((150, 3, 2, "in_transit"), (order["quantity"], order["unit_price"], order["due_day"], order["status"]))

    def test_same_day_and_in_transit_do_not_double_order(self):
        self.run_tick()
        self.run_tick(phase="evening")
        self.assertEqual(1, len(self.kernel.state.inventories["supply"]["orders"]))
        self.assertEqual(50, self.kernel.state.inventories["shops"]["campus_market"]["quantities"]["bread_loaf"])

    def test_next_day_delivers_once_without_resetting_existing_stock(self):
        self.run_tick()
        self.kernel._state.inventories["shops"]["campus_market"]["quantities"]["bread_loaf"] = 70
        result = self.run_tick(day=2)
        self.assertEqual(1, result.payload["supply_deliveries"])
        self.assertEqual(220, self.kernel.state.inventories["shops"]["campus_market"]["quantities"]["bread_loaf"])
        self.run_tick(phase="afternoon")
        self.assertEqual(220, self.kernel.state.inventories["shops"]["campus_market"]["quantities"]["bread_loaf"])
        self.assertEqual({"bread_loaf": 150}, self.kernel.state.inventories["supply"]["imported_quantities"])
        self.assertEqual(2550, self.kernel.state.inventories["shops"]["campus_market"]["cash"])

    def test_closed_shop_cannot_order_or_receive(self):
        self.run_tick(phase="late_night")
        self.assertEqual({}, self.kernel.state.inventories["supply"]["orders"])
        self.run_tick(phase="morning")
        self.run_tick(day=2, phase="late_night")
        self.assertEqual({}, self.kernel.state.inventories["supply"]["imported_quantities"])
        self.run_tick(day=3, phase="morning")
        self.assertEqual({"bread_loaf": 150}, self.kernel.state.inventories["supply"]["imported_quantities"])

    def test_partial_affordable_order_preserves_shop_cash_reserve(self):
        self.kernel._state.inventories["shops"]["campus_market"]["cash"] = 215
        self.run_tick()
        order = next(iter(self.kernel.state.inventories["supply"]["orders"].values()))
        self.assertEqual(5, order["quantity"])
        self.assertEqual(200, self.kernel.state.inventories["shops"]["campus_market"]["cash"])

    def test_no_funds_no_debt_no_fake_order(self):
        self.kernel._state.inventories["shops"]["campus_market"]["cash"] = 201
        result = self.run_tick()
        self.assertEqual(0, result.payload["supply_orders"])
        self.assertEqual(0, self.kernel.state.inventories["supply"]["supplier_receipts"])
        self.assertEqual("insufficient_shop_funds", supply_view(self.kernel.state, "campus_market")["goods"]["bread_loaf"]["status"])

    def test_supply_pause_before_order_does_not_charge(self):
        self.kernel._state.inventories["supply"]["available"] = False
        self.run_tick()
        self.assertEqual({}, self.kernel.state.inventories["supply"]["orders"])
        self.assertEqual("supply_paused", supply_view(self.kernel.state, "campus_market")["goods"]["bread_loaf"]["status"])

    def test_supply_pause_after_payment_keeps_paid_order_and_recovers_once(self):
        self.run_tick()
        self.kernel._state.inventories["supply"]["available"] = False
        result = self.run_tick(day=2)
        self.assertEqual(1, sum(e.event_type == "CAMPUS_SUPPLY_DELAYED" for e in result.events))
        result = self.run_tick(phase="afternoon")
        self.assertEqual(0, len(result.events))
        self.assertEqual("delayed", supply_view(self.kernel.state, "campus_market")["goods"]["bread_loaf"]["status"])
        self.kernel._state.inventories["supply"]["available"] = True
        result = self.run_tick(day=3, phase="morning")
        self.assertEqual(1, result.payload["supply_deliveries"])
        self.assertEqual(450, self.kernel.state.inventories["supply"]["supplier_receipts"])
        self.assertEqual(200, self.kernel.state.inventories["shops"]["campus_market"]["quantities"]["bread_loaf"])

    def test_replayed_order_and_delivery_are_idempotent(self):
        for params in ({}, {"day": 2}):
            command = self.command(**params)
            self.kernel.execute(command)
            before = self.kernel.state.to_dict()
            self.assertTrue(self.kernel.execute(command).replayed)
            self.assertEqual(before, self.kernel.state.to_dict())

    def test_invariant_failure_rolls_back_order_cash_and_events(self):
        self.kernel.add_invariant(lambda state: ["injected test failure"] if state.inventories["supply"]["orders"] else [])
        before = self.kernel.state
        with self.assertRaises(ValueError):
            self.run_tick()
        self.assertEqual(before.to_dict(), self.kernel.state.to_dict())

    def test_invariant_failure_rolls_back_delivery(self):
        self.run_tick()
        self.kernel.add_invariant(lambda state: ["injected test failure"] if state.inventories["supply"]["imported_quantities"] else [])
        before = self.kernel.state
        with self.assertRaises(ValueError):
            self.run_tick(day=2)
        self.assertEqual(before.to_dict(), self.kernel.state.to_dict())

    def test_checkpoint_preserves_paid_order_and_does_not_recharge(self):
        self.run_tick()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "supply.json"
            save_kernel_checkpoint(path, self.kernel.state, DeterministicRngPool.from_snapshot(self.kernel.rng_snapshot))
            restored = load_kernel_checkpoint(path)
            self.assertEqual(json.loads(json.dumps(self.kernel.state.inventories)), restored.state.inventories)
            self.kernel = self.make_kernel(restored.state, restored.rng)
            self.run_tick(day=2)
            self.assertEqual(450, self.kernel.state.inventories["supply"]["supplier_receipts"])
            self.assertEqual(200, self.kernel.state.inventories["shops"]["campus_market"]["quantities"]["bread_loaf"])

    def test_corrupt_account_import_or_order_index_rejected(self):
        self.run_tick()
        for mutate in [
            lambda s: s["supply"].update(supplier_receipts=0),
            lambda s: s["supply"].update(imported_quantities={"bread_loaf": 150}),
            lambda s: s["supply"]["last_order_day"].clear(),
            lambda s: s["supply"]["orders"]["supply:1"].update(quantity=-1),
        ]:
            state = self.kernel.state
            mutate(state.inventories)
            self.assertTrue(list(campus_supply_invariant(state)))
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(CheckpointError):
                save_kernel_checkpoint(Path(directory) / "bad.json", state, DeterministicRngPool(42))

    def test_invalid_policy_rejected(self):
        for field, value in (("wholesale_percent", 0), ("reorder_percent", 100), ("cash_reserve", True), ("supplier_name", "")):
            policy = deepcopy(self.baseline.inventories["supply"]["policy"])
            policy[field] = value
            with self.assertRaises(ValueError):
                validate_supply_policy(policy)

    def test_public_projection_has_stock_eta_not_internal_supplier_account(self):
        self.run_tick()
        view = campus_inventory_view(self.kernel.state)
        shop = next(s for s in view["shops"] if s["id"] == "campus_market")
        self.assertEqual({"status": "in_transit", "in_transit": 150, "due_day": 2, "target_stock": 200}, shop["supply"]["goods"]["bread_loaf"])
        self.assertNotIn("supplier_receipts", shop["supply"])
        shop["supply"]["goods"]["bread_loaf"]["in_transit"] = 9999
        self.assertEqual(150, supply_view(self.kernel.state, "campus_market")["goods"]["bread_loaf"]["in_transit"])


if __name__ == "__main__":
    unittest.main()
