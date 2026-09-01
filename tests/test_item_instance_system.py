from __future__ import annotations

import tempfile
import unittest

from simulation import runtime as sim


class ItemInstanceSystemTests(unittest.TestCase):
    def make_world(self):
        output=tempfile.TemporaryDirectory(); self.addCleanup(output.cleanup)
        return sim.World(sim.Config(
            core_npcs=4,simple_npcs=4,llm_mode="rule",
            log_dir=output.name,verbose=False))

    def test_every_scene_and_world_container_has_an_inventory(self):
        world=self.make_world()
        for scene_id in world.scenes:
            self.assertIn(f"scene:{scene_id}",world.inventories)
        for object_id,obj in world.objects.items():
            if obj.object_type=="container":
                self.assertIn(f"container:{object_id}",world.inventories)
        self.assertEqual(1,world.inventories["scene:warehouse_3"].quantity("warehouse_3_key"))
        self.assertEqual([],world.item_instances.validate())

    def test_durable_trade_preserves_the_same_instance(self):
        world=self.make_world()
        shop_id="shop:market_general_store"
        before=world.item_instances.instances_for(shop_id,"crowbar",world.day)[0].id
        receipt=sim.execute_trade(
            world,actor_id="player",shop_id="market_general_store",
            item_id="crowbar",quantity=1,direction="buy")
        self.assertTrue(receipt.success)
        after=world.item_instances.instances_for("player","crowbar",world.day)[0].id
        self.assertEqual(before,after)
        self.assertEqual("player",world.item_instances.instances[after].inventory_id)
        self.assertEqual([],world.economy.validate_invariants(world))

    def test_legacy_quantity_edits_are_reconciled_without_duplicate_instances(self):
        world=self.make_world(); inventory=world.inventories["npc_003"]
        inventory.quantities["lockpick_set"]=1
        self.assertEqual([],world.economy.validate_invariants(world))
        instance_ids=list(inventory.instance_ids["lockpick_set"])
        self.assertEqual(1,len(instance_ids))
        inventory.quantities.pop("lockpick_set")
        self.assertEqual([],world.economy.validate_invariants(world))
        self.assertNotIn(instance_ids[0],world.item_instances.instances)

    def test_shop_restock_creates_instances_for_durable_stock(self):
        world=self.make_world(); shop_inventory=world.inventories["shop:market_general_store"]
        shop_inventory.quantities.pop("crowbar",None)
        world.item_instances.reconcile_inventory(shop_inventory.owner_id,world.day)
        world.economy.restock_shops(world)
        self.assertGreater(shop_inventory.quantity("crowbar"),0)
        self.assertEqual(shop_inventory.quantity("crowbar"),
                         len(shop_inventory.instance_ids["crowbar"]))
        self.assertEqual([],world.economy.validate_invariants(world))


if __name__=="__main__":
    unittest.main()
