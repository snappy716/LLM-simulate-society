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
