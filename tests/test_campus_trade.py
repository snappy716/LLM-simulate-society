from collections import Counter
from pathlib import Path
import tempfile
import unittest
import json

from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems.campus_inventory import CAMPUS_ITEM_ACTIONS, make_campus_inventory_handler, campus_inventory_invariant, campus_inventory_view
from simulation.systems.campus_trade import (
    TRADE_ACTIONS, make_campus_trade_handler, valuation, advance_campus_trade,
    make_procurement_selector, professional, tick,
)
from simulation.systems.transactions import WorldKernel, TransactionContext
from simulation.systems.randomness import DeterministicRngPool


class CampusTradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.baseline = cls.bridge.kernel.state

    def setUp(self):
        state = self.baseline.clone()
        self.npc = "campus_student_001"
        self.other = "campus_student_002"
        for actor in ("player", self.npc, self.other):
            state.population[actor]["current_location_id"] = "supermarket_sales_floor"
        self.kernel = self.build_kernel(state)
        self.sequence = 0

    @staticmethod
    def build_kernel(state, rng=None):
        kernel = WorldKernel(state, rng=rng)
        kernel.add_invariant(campus_inventory_invariant)
        for action in TRADE_ACTIONS:
            kernel.register_handler(action, make_campus_trade_handler())
        for action in CAMPUS_ITEM_ACTIONS:
            kernel.register_handler(action, make_campus_inventory_handler())
        return kernel

    def command(self, action, actor="player", **parameters):
        self.sequence += 1
        state = self.kernel.state
        return SimulationCommand(f"trade-test-{self.sequence}", actor, action, state.revision,
                                 parameters=parameters, issued_day=state.clock.day,
                                 issued_phase=state.clock.phase, source="player" if actor == "player" else "rule")

    def run_action(self, action, actor="player", **params):
        return self.kernel.execute(self.command(action, actor, **params))

    def quote(self, **params):
        return self.run_action("OFFER_TRADE", **{"target_id": self.npc, "item_id": "bread_loaf", "unit_price": 4, "quantity": 1, **params})

    def respond(self, result):
        return self.run_action("REQUEST_TRADE_RESPONSE", offer_id=result.payload["offer"]["offer_id"])

    @staticmethod
    def totals(state):
        money = sum(a["wealth"] for a in state.population.values()) + sum(s["cash"] for s in state.inventories["shops"].values())
        stock = Counter()
        for section in ("actors", "shops", "ground"):
            for container in state.inventories[section].values():
                stock.update(container["quantities"])
        return money, stock

    def test_quote_is_not_settlement_and_response_is_atomic(self):
        before = self.kernel.state
        offered = self.quote()
        self.assertEqual("offered", offered.code)
        self.assertEqual(before.population, self.kernel.state.population)
        self.assertEqual(before.inventories["actors"], self.kernel.state.inventories["actors"])
        self.assertEqual("settled", self.respond(offered).code)
        after = self.kernel.state
        self.assertEqual(self.totals(before), self.totals(after))
        self.assertEqual(496, after.population["player"]["wealth"])
        self.assertEqual(1, after.inventories["actors"][self.npc]["quantities"]["bread_loaf"])
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(before.action_economy, after.action_economy)

    def test_replay_and_second_accept_do_not_pay_twice(self):
        offered = self.quote()
        command = self.command("REQUEST_TRADE_RESPONSE", offer_id=offered.payload["offer"]["offer_id"])
        self.assertEqual("settled", self.kernel.execute(command).code)
        before = self.kernel.state.to_dict()
        self.assertTrue(self.kernel.execute(command).replayed)
        self.assertEqual(before, self.kernel.state.to_dict())
        self.assertEqual("offer_closed", self.respond(offered).code)

    def test_failed_accept_revalidates_money_stock_location_capacity_layer_battle(self):
        mutations = [
            ("insufficient_funds", lambda s: s.population["player"].update(wealth=0)),
            ("item_protected", lambda s: s.inventories["actors"][self.npc]["quantities"].update(bread_loaf=1)),
            ("location_mismatch", lambda s: s.population[self.npc].update(current_location_id="campus_gate_region")),
            ("inventory_full", lambda s: s.inventories["actors"]["player"].update(max_weight=1.1)),
            ("location_mismatch", lambda s: s.situations["night_world"]["actor_states"][self.npc].update(layer="night")),
            ("battle_locked", lambda s: s.metadata["campus_combat"]["active_battle_by_actor"].update({self.npc: "test-battle"})),
        ]
        for code, mutate in mutations:
            with self.subTest(code=code):
                self.setUp()
                offered = self.quote()
                mutate(self.kernel._state)
                before = self.kernel.state
                result = self.respond(offered)
                self.assertEqual(code, result.code)
                self.assertFalse(result.success)
                self.assertEqual(before.inventories, self.kernel.state.inventories)
                self.assertEqual(before.population, self.kernel.state.population)

    def test_reject_and_cancel_do_not_transfer_assets(self):
        for action, actor, expected in [("CANCEL_TRADE", "player", "cancelled"), ("REJECT_TRADE", self.npc, "rejected")]:
            offered = self.quote()
            before = self.totals(self.kernel.state)
            result = self.run_action(action, actor, offer_id=offered.payload["offer"]["offer_id"])
            self.assertEqual(expected, result.code)
            self.assertEqual(before, self.totals(self.kernel.state))

    def test_no_forced_player_accept_or_third_party_response(self):
        offered = self.quote()
        self.assertEqual("actor_not_authorized", self.run_action("ACCEPT_TRADE", offer_id=offered.payload["offer"]["offer_id"]).code)
        self.assertEqual("actor_not_authorized", self.run_action("ACCEPT_TRADE", self.other, offer_id=offered.payload["offer"]["offer_id"]).code)
        command = self.command("ACCEPT_TRADE", self.npc, offer_id=offered.payload["offer"]["offer_id"])
        from dataclasses import replace
        self.assertEqual("actor_not_authorized", self.kernel.execute(replace(command, source="player")).code)

    def test_incoming_player_offer_stays_pending_until_player_accepts(self):
        result = self.run_action("OFFER_TRADE", self.npc, target_id="player", item_id="bread_loaf", quantity=1, unit_price=4, side="sell")
        context = TransactionContext(self.kernel._state, DeterministicRngPool(42), self.command("ADVANCE_PHASE"))
        advance_campus_trade(context)
        offer_id = result.payload["offer"]["offer_id"]
        self.assertEqual("pending", self.kernel.state.inventories["trade"]["offers"][offer_id]["status"])
        self.assertEqual("settled", self.run_action("ACCEPT_TRADE", offer_id=offer_id).code)

    def test_same_pair_pending_and_offer_expiration(self):
        offer = self.quote()
        self.assertEqual("pending_offer", self.quote().code)
        self.kernel._state.clock.phase = "evening"
        self.assertEqual("expired", self.respond(offer).code)

    def test_invalid_quote_inputs_do_not_mutate_ledger(self):
        for params in [{"unit_price": -1}, {"unit_price": True}, {"unit_price": "4"}, {"quantity": 0}, {"quantity": []}, {"quantity": 100}, {"target_id": []}, {"item_id": {}}, {"side": []}]:
            before = self.kernel.state.inventories
            self.assertFalse(self.quote(**params).success)
            self.assertEqual(before, self.kernel.state.inventories)

    def test_no_need_and_bad_price_are_real_npc_rejections(self):
        no_need = self.quote(side="sell")
        self.assertEqual("rejected", self.respond(no_need).code)
        too_low = self.quote(unit_price=1)
        self.assertEqual("rejected", self.respond(too_low).code)
        self.assertEqual(500, self.kernel.state.population["player"]["wealth"])

    def test_life_reserve_and_medical_tools(self):
        self.assertEqual("item_protected", self.quote(quantity=2).code)
        doctor = next(a for a, r in self.kernel.state.population.items() if r.get("occupation_id") == "medical_staff")
        self.kernel._state.population[doctor]["current_location_id"] = "supermarket_sales_floor"
        self.assertEqual("item_protected", self.quote(target_id=doctor, item_id="bandage_roll", quantity=2, unit_price=10).code)
        self.assertTrue(self.quote(target_id=doctor, item_id="bandage_roll", unit_price=10).success)

    def test_relationship_suspicion_personality_pressure_change_values(self):
        state = self.kernel._state
        baseline = valuation(state, self.npc, "player", "padded_coat", buying=True)
        state.relationships[self.npc]["player"] = {"trust": 50, "suspicion": 80, "conflict": 0, "closeness": 0}
        suspicious = valuation(state, self.npc, "player", "padded_coat", buying=True)
        self.assertLess(suspicious, baseline)
        state.relationships[self.npc] = {}
        state.population[self.npc]["personality"]["agreeableness"] = 100
        friendly = valuation(state, self.npc, "player", "padded_coat", buying=True)
        self.assertGreater(friendly, baseline)
        state.population[self.npc]["wealth"] = 1
        self.assertLess(valuation(state, self.npc, "player", "padded_coat", buying=True), friendly)

    def test_settled_price_and_quote_memory_are_separate(self):
        self.assertEqual("settled", self.respond(self.quote()).code)
        entries = self.kernel.state.inventories["trade"]["memories"][self.npc]
        self.assertEqual(["pending", "settled"], [e["status"] for e in entries])
        self.assertEqual(4, entries[-1]["unit_price"])

    def test_npc_two_to_four_day_cooldown_and_newly_acquired_item_lock(self):
        self.assertEqual("settled", self.respond(self.quote()).code)
        state = self.kernel._state
        next_tick = state.inventories["trade"]["next_private_tick"][self.npc]
        self.assertIn(next_tick, (8, 12, 16))
        self.assertEqual("trade_cooldown", self.quote(item_id="blank_notebook").code)
        self.run_action("BUY_ITEM", self.other, item_id="bread_loaf", shop_id="campus_market")
        self.assertEqual("item_cooldown", self.quote(target_id=self.other).code)

    def test_trading_profession_can_serve_multiple_people_but_not_flip_immediately(self):
        state = self.kernel._state
        seller = next(a for a in state.population if professional(state, a))
        state.population[seller]["current_location_id"] = "supermarket_sales_floor"
        state.inventories["actors"][seller]["quantities"]["bread_loaf"] = 5
        for buyer in ("player", self.npc, self.other):
            result = self.run_action("OFFER_TRADE", buyer, target_id=seller, item_id="bread_loaf", quantity=1, unit_price=4)
            self.assertTrue(result.success, result)
            accepted = self.run_action("ACCEPT_TRADE", seller, offer_id=result.payload["offer"]["offer_id"])
            self.assertEqual("settled", accepted.code)
        self.assertEqual(2, self.kernel.state.inventories["actors"][seller]["quantities"]["bread_loaf"])

    def test_checkpoint_preserves_quotes_price_memories_and_cooldowns(self):
        offer = self.quote()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trade.json"
            save_kernel_checkpoint(path, self.kernel.state, DeterministicRngPool.from_snapshot(self.kernel.rng_snapshot))
            restored = load_kernel_checkpoint(path)
            self.assertEqual(json.loads(json.dumps(self.kernel.state.inventories)), restored.state.inventories)
            self.kernel = self.build_kernel(restored.state, restored.rng)
            self.assertEqual("settled", self.respond(offer).code)

    def test_private_view_does_not_expose_unrelated_npc_quotes(self):
        self.run_action("OFFER_TRADE", self.npc, target_id=self.other, item_id="bread_loaf", quantity=1, unit_price=4)
        self.assertEqual([], campus_inventory_view(self.kernel.state)["private_trade"]["offers"])

    def test_competing_quotes_cannot_sell_last_surplus_twice(self):
        first = self.quote()
        second = self.run_action("OFFER_TRADE", self.other, target_id=self.npc, item_id="bread_loaf", quantity=1, unit_price=4)
        self.assertTrue(second.success)
        self.assertEqual("settled", self.respond(first).code)
        before = self.totals(self.kernel.state)
        result = self.run_action("ACCEPT_TRADE", self.npc, offer_id=second.payload["offer"]["offer_id"])
        self.assertEqual("trade_cooldown", result.code)
        self.assertEqual(before, self.totals(self.kernel.state))

    def test_corrupt_cooldown_or_memory_rejected_by_invariant(self):
        for field, value in [("next_private_tick", {self.npc: -1}),
                             ("acquired", {self.npc: {"bread_loaf": "yesterday"}}),
                             ("memories", {self.npc: [{"item_id": "bread_loaf", "unit_price": -1, "tick": 0}]})]:
            state = self.kernel.state
            state.inventories["trade"][field] = value
            self.assertTrue(list(campus_inventory_invariant(state)))

    def test_autonomous_peers_act_without_player_and_without_creating_resources(self):
        state = self.kernel._state
        state.clock.day = 4
        state.population[self.npc]["needs"]["food"] = 60
        state.inventories["actors"][self.npc]["quantities"].pop("bread_loaf")
        before = self.totals(state)
        context = TransactionContext(state, DeterministicRngPool(42), self.command("ADVANCE_PHASE"))
        summary = advance_campus_trade(context)
        self.assertGreater(summary["private_trade_settled"], 0)
        self.assertEqual(before, self.totals(state))
        self.assertEqual(0, advance_campus_trade(context)["private_trade_settled"])
        self.assertTrue(any(e.event_type == "CAMPUS_TRADE_SETTLED" for e in context.event_drafts))

    def test_carried_food_does_not_also_charge_abstract_meal(self):
        from simulation.systems.campus_activity_effects import advance_campus_phase_upkeep
        state = self.kernel._state
        state.population[self.npc]["needs"]["food"] = 95
        wealth = state.population[self.npc]["wealth"]
        context = TransactionContext(state, DeterministicRngPool(42), self.command("ADVANCE_PHASE"))
        advance_campus_phase_upkeep(context)
        self.assertEqual(75, state.population[self.npc]["needs"]["food"])
        self.assertEqual(wealth, state.population[self.npc]["wealth"])
        self.assertEqual(1, state.inventories["actors"][self.npc]["quantities"]["bread_loaf"])

    def test_procurement_plans_route_not_teleport_and_respects_commitments(self):
        state = self.kernel._state
        state.inventories["actors"][self.npc]["quantities"].pop("bread_loaf")
        state.population[self.npc]["needs"]["food"] = 60
        state.population[self.npc]["current_location_id"] = "south_gate_region"
        context = TransactionContext(state, DeterministicRngPool(42), self.command("ADVANCE_PHASE"))
        from simulation.systems.campus_locations import load_campus_location_graph
        from simulation.systems.content_registry import ContentRegistry
        graph = load_campus_location_graph(ContentRegistry.load_default(Path(__file__).parents[1] / "content"))
        selector = make_procurement_selector(lambda *args: {"fallback": True}, graph, 80)
        plan = selector(context, self.npc, {"priority": 0}, Counter())
        self.assertEqual("BUY_ITEM", plan["activity_id"])
        self.assertEqual("south_gate_region", state.population[self.npc]["current_location_id"])
        self.assertEqual({"fallback": True}, selector(context, self.npc, {"priority": 100}, Counter()))
        state.population[self.npc]["wealth"] = 0
        self.assertEqual({"fallback": True}, selector(context, self.npc, {"priority": 0}, Counter()))

    def test_procurement_uses_alternative_food_when_bread_sold_out(self):
        from simulation.systems.campus_locations import load_campus_location_graph
        from simulation.systems.content_registry import ContentRegistry
        graph = load_campus_location_graph(ContentRegistry.load_default(Path(__file__).parents[1] / "content"))
        state = self.kernel._state
        state.population[self.npc]["needs"]["food"] = 60
        state.inventories["actors"][self.npc]["quantities"].pop("bread_loaf")
        state.inventories["shops"]["campus_market"]["quantities"].pop("bread_loaf")
        context = TransactionContext(state, DeterministicRngPool(42), self.command("ADVANCE_PHASE"))
        selector = make_procurement_selector(lambda *args: {}, graph, 80)
        plan = selector(context, self.npc, {"priority": 0}, Counter())
        self.assertEqual("BUY_ITEM", plan["activity_id"])
        self.assertIn(plan["parameters"]["item_id"], ("restaurant_meal", "dried_meat"))


if __name__ == "__main__":
    unittest.main()
