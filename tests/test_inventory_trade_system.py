from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simulation import runtime as sim
from simulation.api.server import SimulationBridge


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class InventoryTradeSystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.world = sim.World(sim.Config(
            core_npcs=4, simple_npcs=4, llm_mode="rule",
            log_dir=self.tmp.name, verbose=False,
        ))

    def tearDown(self):
        self.tmp.cleanup()

    def test_catalog_matches_demo_scope_and_content_is_valid(self):
        self.assertGreaterEqual(len(self.world.item_catalog), 30)
        self.assertLessEqual(len(self.world.item_catalog), 50)
        categories = {item.category for item in self.world.item_catalog.values()}
        self.assertTrue({"food", "medicine", "key", "weapon", "ritual_material",
                         "potion", "sealed_artifact"}.issubset(categories))
        self.assertEqual([], self.world.economy.validate_invariants(self.world))

    def test_successful_buy_is_atomic_and_creates_event(self):
        stock = self.world.inventories["shop:market_general_store"]
        player = self.world.inventories["player"]
        before = (self.world.player_wealth, stock.quantity("bread_loaf"),
                  player.quantity("bread_loaf"))
        receipt = sim.execute_trade(
            self.world, actor_id="player", shop_id="market_general_store",
            item_id="bread_loaf", quantity=2, direction="buy",
        )
        self.assertTrue(receipt.success)
        self.assertEqual(before[0] - receipt.total_price, self.world.player_wealth)
        self.assertEqual(before[1] - 2, stock.quantity("bread_loaf"))
        self.assertEqual(before[2] + 2, player.quantity("bread_loaf"))
        self.assertEqual("ITEM_TRADED", self.world.events_by_day[1][-1].event_type)
        self.assertEqual(receipt.event_id, self.world.events_by_day[1][-1].event_id)

    def test_failed_buy_does_not_mutate_money_or_inventory(self):
        self.world.player_wealth = 0
        stock = self.world.inventories["shop:market_general_store"]
        player = self.world.inventories["player"]
        before = (self.world.player_wealth, stock.quantity("crowbar"),
                  player.quantity("crowbar"))
        receipt = sim.execute_trade(
            self.world, actor_id="player", shop_id="market_general_store",
            item_id="crowbar", quantity=1, direction="buy",
        )
        self.assertFalse(receipt.success)
        self.assertEqual("insufficient_funds", receipt.code)
        self.assertEqual(before, (self.world.player_wealth, stock.quantity("crowbar"),
                                  player.quantity("crowbar")))

    def test_capacity_failure_does_not_mutate_transaction(self):
        player = self.world.inventories["player"]
        player.max_weight = player.total_weight(self.world.item_catalog) + 0.1
        before_money = self.world.player_wealth
        before_stock = self.world.inventories["shop:market_general_store"].quantity("crowbar")
        receipt = self.world.economy.trade(
            self.world, actor_id="player", shop_id="market_general_store",
            item_id="crowbar", quantity=1, direction="buy",
        )
        self.assertEqual("inventory_full", receipt.code)
        self.assertEqual(before_money, self.world.player_wealth)
        self.assertEqual(before_stock, self.world.inventories["shop:market_general_store"].quantity("crowbar"))

    def test_sell_transfers_item_and_shop_cash(self):
        player = self.world.inventories["player"]
        shop = self.world.shops["market_general_store"]
        before = (self.world.player_wealth, shop.cash, player.quantity("hemp_rope"))
        receipt = sim.execute_trade(
            self.world, actor_id="player", shop_id=shop.id,
            item_id="hemp_rope", quantity=1, direction="sell",
        )
        self.assertTrue(receipt.success)
        self.assertEqual(before[0] + receipt.total_price, self.world.player_wealth)
        self.assertEqual(before[1] - receipt.total_price, shop.cash)
        self.assertEqual(before[2] - 1, player.quantity("hemp_rope"))

    def test_opening_hours_and_legality_are_enforced(self):
        closed = self.world.economy.trade(
            self.world, actor_id="player", shop_id="red_moon_tavern_counter",
            item_id="beer_bottle", quantity=1, direction="buy",
        )
        self.assertEqual("shop_closed", closed.code)
        lockpick = self.world.item_catalog["lockpick_set"]
        self.world.inventories["player"].add(lockpick, 1, self.world.item_catalog)
        rejected = self.world.economy.trade(
            self.world, actor_id="player", shop_id="market_general_store",
            item_id="lockpick_set", quantity=1, direction="sell",
        )
        self.assertEqual("legality_rejected", rejected.code)
        category_rejected = self.world.economy.trade(
            self.world, actor_id="player", shop_id="hospital_apothecary",
            item_id="hemp_rope", quantity=1, direction="sell",
        )
        self.assertEqual("category_rejected", category_rejected.code)

    def test_unique_item_cannot_have_two_owners(self):
        key = self.world.item_catalog["warehouse_3_key"]
        self.world.inventories["player"].add(key, 1, self.world.item_catalog)
        self.world.inventories["npc_000"].quantities[key.id] = 1
        self.assertIn("unique item has multiple owners: warehouse_3_key",
                      self.world.economy.validate_invariants(self.world))

    def test_npc_and_player_use_same_trade_service(self):
        npc = self.world.npcs["npc_003"]
        npc.current_scene = "market"
        before = self.world.inventories[npc.id].quantity("bread_loaf")
        before_energy = npc.states["energy"]
        result = self.world.action_registry.execute(
            "BUY_ITEM", npc=npc,
            context=sim.action_context(self.world, self.world.scenes["market"]),
            shop_id="market_general_store", item_id="bread_loaf", quantity=1,
        )
        self.assertTrue(result.success)
        self.assertEqual(before + 1, self.world.inventories[npc.id].quantity("bread_loaf"))
        self.assertEqual(before_energy - 1, npc.states["energy"])

    def test_npc_shop_trade_requires_colocation(self):
        npc = self.world.npcs["npc_003"]
        npc.current_scene = npc.home_scene
        before = (npc.wealth,
                  self.world.inventories[npc.id].quantity("bread_loaf"),
                  self.world.inventories["shop:market_general_store"].quantity("bread_loaf"))
        receipt = self.world.economy.trade(
            self.world, actor_id=npc.id, shop_id="market_general_store",
            item_id="bread_loaf", quantity=1, direction="buy",
        )
        self.assertEqual("location_mismatch", receipt.code)
        self.assertEqual(before, (
            npc.wealth,
            self.world.inventories[npc.id].quantity("bread_loaf"),
            self.world.inventories["shop:market_general_store"].quantity("bread_loaf"),
        ))

    def test_shop_behavior_uses_new_trade_and_consumes_one_phase_action(self):
        npc = self.world.npcs["npc_003"]
        self.world.phase = sim.Phase.AFTERNOON
        npc.current_scene = "market"
        npc.states["satiety"] = 15
        npc.wealth = 40
        before_energy = npc.states["energy"]
        before_stock = self.world.inventories["shop:market_general_store"].quantity("bread_loaf")
        sim.execute_behavior(
            self.world, npc, self.world.scenes["market"],
            sim.PhasePlan("market", "购买食物", behavior="SHOP"),
        )
        event_types = [event.event_type for event in self.world.events_by_day[1]]
        self.assertIn("ITEM_TRADED", event_types)
        self.assertIn("ITEM_USED", event_types)
        self.assertNotIn("ITEM_BOUGHT_AND_USED", event_types)
        self.assertEqual(before_stock - 1,
                         self.world.inventories["shop:market_general_store"].quantity("bread_loaf"))
        self.assertEqual(before_energy - 1, npc.states["energy"])
        self.assertGreater(npc.states["satiety"], 15)

    def test_peer_offer_acceptance_is_atomic(self):
        seller = self.world.npcs["npc_003"]
        buyer = self.world.npcs["npc_004"]
        seller.current_scene = buyer.current_scene = "market"
        bread = self.world.item_catalog["bread_loaf"]
        self.world.inventories[seller.id].add(bread, 2, self.world.item_catalog)
        buyer.wealth = 50
        before = (seller.wealth, buyer.wealth,
                  self.world.inventories[seller.id].quantity(bread.id),
                  self.world.inventories[buyer.id].quantity(bread.id))
        offer, error, _ = sim.create_peer_trade_offer(
            self.world, seller_id=seller.id, buyer_id=buyer.id,
            item_id=bread.id, quantity=1, unit_price=5,
        )
        self.assertIsNone(error)
        receipt, _ = sim.respond_peer_trade_offer(
            self.world, offer_id=offer.id, responder_id=buyer.id,
            accept=True, reason="需要食物",
        )
        self.assertTrue(receipt.success)
        self.assertEqual("accepted", offer.status)
        self.assertEqual((before[0] + 5, before[1] - 5, before[2] - 1, before[3] + 1), (
            seller.wealth, buyer.wealth,
            self.world.inventories[seller.id].quantity(bread.id),
            self.world.inventories[buyer.id].quantity(bread.id),
        ))
        self.assertEqual([], self.world.economy.validate_invariants(self.world))

    def test_peer_offer_rejection_and_failed_acceptance_do_not_mutate(self):
        seller = self.world.npcs["npc_003"]
        buyer = self.world.npcs["npc_004"]
        seller.current_scene = buyer.current_scene = "market"
        bread = self.world.item_catalog["bread_loaf"]
        self.world.inventories[seller.id].add(bread, 1, self.world.item_catalog)
        before = (seller.wealth, buyer.wealth,
                  self.world.inventories[seller.id].quantity(bread.id),
                  self.world.inventories[buyer.id].quantity(bread.id))
        rejected, error = self.world.economy.create_peer_offer(
            self.world, seller_id=seller.id, buyer_id=buyer.id,
            item_id=bread.id, quantity=1, unit_price=5,
        )
        self.assertIsNone(error)
        receipt = self.world.economy.respond_peer_offer(
            self.world, offer_id=rejected.id, responder_id=buyer.id,
            accept=False, reason="价格太高",
        )
        self.assertEqual("rejected", receipt.code)
        self.assertEqual("rejected", rejected.status)
        self.assertEqual(before, (seller.wealth, buyer.wealth,
                                  self.world.inventories[seller.id].quantity(bread.id),
                                  self.world.inventories[buyer.id].quantity(bread.id)))

        buyer.wealth = 0
        pending, error = self.world.economy.create_peer_offer(
            self.world, seller_id=seller.id, buyer_id=buyer.id,
            item_id=bread.id, quantity=1, unit_price=5,
        )
        self.assertIsNone(error)
        before_failed = (seller.wealth, buyer.wealth,
                         self.world.inventories[seller.id].quantity(bread.id),
                         self.world.inventories[buyer.id].quantity(bread.id))
        failed = self.world.economy.respond_peer_offer(
            self.world, offer_id=pending.id, responder_id=buyer.id, accept=True,
        )
        self.assertEqual("insufficient_funds", failed.code)
        self.assertEqual("pending", pending.status)
        self.assertEqual(before_failed, (seller.wealth, buyer.wealth,
                                         self.world.inventories[seller.id].quantity(bread.id),
                                         self.world.inventories[buyer.id].quantity(bread.id)))

    def test_nonmerchant_npcs_autonomously_quote_and_settle(self):
        keeper_ids = {shop.keeper_id for shop in self.world.shops.values()}
        participants = [npc for npc in self.world.npcs.values() if npc.id not in keeper_ids]
        buyer, seller = participants[:2]
        self.world.phase = sim.Phase.AFTERNOON
        buyer.current_scene = seller.current_scene = "market"
        buyer.states["satiety"] = 20
        buyer.wealth = 60
        seller.states["satiety"] = 90
        seller.needs["financial_pressure"] = 80
        bread = self.world.item_catalog["bread_loaf"]
        self.world.inventories[seller.id].add(bread, 1, self.world.item_catalog)
        seller_before = seller.wealth
        buyer_energy = buyer.states["energy"]
        sim.execute_behavior(
            self.world, buyer, self.world.scenes["market"],
            sim.PhasePlan("market", "向附近居民购买食物", behavior="SHOP"),
        )
        event_types = [event.event_type for event in self.world.events_by_day[1]]
        self.assertIn("PEER_TRADE_OFFERED", event_types)
        self.assertIn("PEER_TRADE_ACCEPTED", event_types)
        self.assertNotIn("ITEM_TRADED", event_types)
        self.assertGreater(seller.wealth, seller_before)
        self.assertEqual(buyer_energy - 1, buyer.states["energy"])

    def test_dynamic_story_npc_gets_inventory_lazily(self):
        npc = self.world.npcs["npc_003"]
        self.world.inventories.pop(npc.id)
        self.assertEqual([], self.world.economy.public_inventory(npc.id))
        self.assertIn(npc.id, self.world.inventories)
        self.assertEqual(25.0, self.world.inventories[npc.id].max_weight)

    def test_ordinary_peer_trade_has_stable_two_to_four_day_cooldown(self):
        seller=self.world.npcs["npc_003"]; buyer=self.world.npcs["npc_004"]
        seller.current_scene=buyer.current_scene="market"
        bread=self.world.item_catalog["bread_loaf"]
        self.world.inventories[seller.id].add(bread,3,self.world.item_catalog)
        offer,error=self.world.economy.create_peer_offer(
            self.world,seller_id=seller.id,buyer_id=buyer.id,item_id=bread.id,
            quantity=1,unit_price=4)
        self.assertIsNone(error)
        self.assertTrue(self.world.economy.respond_peer_offer(
            self.world,offer_id=offer.id,responder_id=buyer.id,accept=True).success)
        cooldown=self.world.economy.peer_trade_cooldown_days(buyer.id,bread.id)
        self.assertIn(cooldown,{2,3,4})
        blocked,error=self.world.economy.create_peer_offer(
            self.world,seller_id=seller.id,buyer_id=buyer.id,item_id=bread.id,
            quantity=1,unit_price=4)
        self.assertIsNone(blocked)
        self.assertEqual("trade_cooldown",error.code)
        self.world.day+=cooldown
        allowed,error=self.world.economy.create_peer_offer(
            self.world,seller_id=seller.id,buyer_id=buyer.id,item_id=bread.id,
            quantity=1,unit_price=4)
        self.assertIsNotNone(allowed)
        self.assertIsNone(error)

    def test_professional_trader_can_turn_over_same_item_multiple_times(self):
        seller=self.world.npcs["npc_003"]
        seller.occupation="杂货商"; seller.current_scene="market"
        bread=self.world.item_catalog["bread_loaf"]
        self.world.inventories[seller.id].add(bread,5,self.world.item_catalog)
        buyers=[self.world.npcs[f"npc_{index:03d}"] for index in (4,5,6,7)]
        for buyer in buyers:
            buyer.current_scene="market"; buyer.wealth=50
        for buyer in buyers[:3]:
            offer,error=self.world.economy.create_peer_offer(
                self.world,seller_id=seller.id,buyer_id=buyer.id,item_id=bread.id,
                quantity=1,unit_price=4)
            self.assertIsNone(error)
            self.assertTrue(self.world.economy.respond_peer_offer(
                self.world,offer_id=offer.id,responder_id=buyer.id,accept=True).success)
        blocked,error=self.world.economy.create_peer_offer(
            self.world,seller_id=seller.id,buyer_id=buyers[3].id,item_id=bread.id,
            quantity=1,unit_price=4)
        self.assertIsNone(blocked)
        self.assertEqual("trade_cooldown",error.code)

    def test_profession_tool_reserve_and_trade_price_memory(self):
        doctor=self.world.npcs["npc_003"]; buyer=self.world.npcs["npc_004"]
        doctor.occupation="医生"; doctor.current_scene=buyer.current_scene="market"
        buyer.health=50; buyer.wealth=100
        bandage=self.world.item_catalog["bandage_roll"]
        self.world.inventories[doctor.id].quantities={bandage.id:1}
        self.world.inventories[buyer.id].quantities={}
        self.assertIsNone(sim.choose_peer_trade_candidate(
            self.world,buyer,self.world.scenes["market"]))

        self.world.inventories[doctor.id].add(bandage,1,self.world.item_catalog)
        doctor.needs["financial_pressure"]=80
        doctor.relationships[buyer.id]=sim.Relationship(trust=10,suspicion=100)
        self.assertIsNone(sim.choose_peer_trade_candidate(
            self.world,buyer,self.world.scenes["market"]))
        doctor.relationships[buyer.id]=sim.Relationship(trust=90,suspicion=0)
        candidate=sim.choose_peer_trade_candidate(self.world,buyer,self.world.scenes["market"])
        self.assertIsNotNone(candidate)
        self.assertEqual(bandage.id,candidate[1])
        offer,error=self.world.economy.create_peer_offer(
            self.world,seller_id=doctor.id,buyer_id=buyer.id,item_id=bandage.id,
            quantity=1,unit_price=13)
        self.assertIsNone(error)
        receipt=self.world.economy.respond_peer_offer(
            self.world,offer_id=offer.id,responder_id=buyer.id,accept=True)
        self.assertTrue(receipt.success)
        self.assertEqual(13,self.world.economy.recent_accepted_unit_price(buyer.id,bandage.id))
        statuses=[memory.status for memory in self.world.economy.recent_memories(buyer.id)]
        self.assertEqual(["accepted","offered"],statuses[:2])

    def test_bridge_snapshot_and_trade_response_are_text_ready(self):
        output = tempfile.TemporaryDirectory()
        self.addCleanup(output.cleanup)
        bridge = SimulationBridge(Path(output.name))
        snapshot = bridge.snapshot()
        self.assertEqual(36, len(snapshot["items"]))
        self.assertEqual(5, len(snapshot["shops"]))
        self.assertTrue(all(shop["keeper_id"] for shop in snapshot["shops"].values()))
        self.assertEqual(120, snapshot["player"]["wealth"])
        response = bridge.trade({
            "actor_id": "player", "shop_id": "market_general_store",
            "item_id": "bread_loaf", "quantity": 1, "direction": "buy",
        })
        self.assertTrue(response["ok"])
        self.assertIn("黑麦面包", response["trade"]["message"])
        self.assertEqual(snapshot["revision"] + 1, response["snapshot"]["revision"])
        persisted = json.loads((Path(output.name) / "current_world.json").read_text(encoding="utf-8"))
        self.assertEqual(response["snapshot"]["player"], persisted["player"])

    def test_trade_contract_is_strict(self):
        schema = json.loads((REPOSITORY_DIR / "contracts" / "trade_request.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(["buy", "sell"], schema["properties"]["direction"]["enum"])
        self.assertEqual(1, schema["properties"]["quantity"]["minimum"])
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
