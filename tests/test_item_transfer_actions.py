from __future__ import annotations

import tempfile
import unittest

from simulation import runtime as sim


class ItemTransferActionTests(unittest.TestCase):
    def make_world(self):
        output=tempfile.TemporaryDirectory(); self.addCleanup(output.cleanup)
        return sim.World(sim.Config(
            core_npcs=4,simple_npcs=4,llm_mode="rule",
            log_dir=output.name,verbose=False))

    def test_drop_and_pick_up_preserve_instance_owner_and_identity(self):
        world=self.make_world()
        instance=world.item_instances.instances_for("player","hemp_rope",world.day)[0]
        dropped=sim.execute_item_transfer(
            world,action_id="DROP_ITEM",actor_id="player",item_id="hemp_rope")
        self.assertTrue(dropped.success)
        self.assertEqual(instance.id,dropped.instance_ids[0])
        self.assertEqual("player",world.item_instances.instances[instance.id].legal_owner_id)
        picked=sim.execute_item_transfer(
            world,action_id="PICK_UP_ITEM",actor_id="player",item_id="hemp_rope")
        self.assertTrue(picked.success)
        self.assertEqual(0,picked.legal_risk_delta)
        self.assertEqual(instance.id,picked.instance_ids[0])
        self.assertEqual([],world.economy.validate_invariants(world))

    def test_give_changes_legal_owner_and_requires_colocation(self):
        world=self.make_world(); target=world.npcs["npc_003"]
        target.current_scene=world.player_scene
        receipt=sim.execute_item_transfer(
            world,action_id="GIVE_ITEM",actor_id="player",target_id=target.id,
            item_id="hemp_rope")
        self.assertTrue(receipt.success)
        instance=world.item_instances.instances[receipt.instance_ids[0]]
        self.assertEqual(target.id,instance.inventory_id)
        self.assertEqual(target.id,instance.legal_owner_id)
        target.current_scene="market"
        failed=sim.execute_item_transfer(
            world,action_id="GIVE_ITEM",actor_id=target.id,target_id="player",
            item_id="hemp_rope")
        self.assertEqual("target_absent",failed.code)
        self.assertEqual(1,world.inventories[target.id].quantity("hemp_rope"))

    def test_pick_up_owned_and_restricted_item_adds_legal_risk(self):
        world=self.make_world(); world.player_scene="warehouse_3"
        before=world.player_states["legal_risk"]
        receipt=sim.execute_item_transfer(
            world,action_id="PICK_UP_ITEM",actor_id="player",item_id="warehouse_3_key")
        self.assertTrue(receipt.success)
        self.assertEqual(8,receipt.legal_risk_delta)
        self.assertEqual(before+8,world.player_states["legal_risk"])
        self.assertEqual("aurora_order_tingen",
                         world.item_instances.instances[receipt.instance_ids[0]].legal_owner_id)

    def test_capacity_failure_is_atomic(self):
        world=self.make_world(); world.player_scene="red_moon_street"
        player=world.inventories["player"]
        player.max_weight=player.total_weight(world.item_catalog)
        source=world.inventories["scene:red_moon_street"]
        before=(source.quantity("rusted_knife"),player.quantity("rusted_knife"),
                dict(source.instance_ids),dict(player.instance_ids))
        receipt=sim.execute_item_transfer(
            world,action_id="PICK_UP_ITEM",actor_id="player",item_id="rusted_knife")
        self.assertEqual("inventory_full",receipt.code)
        self.assertEqual(before,(source.quantity("rusted_knife"),player.quantity("rusted_knife"),
                                 dict(source.instance_ids),dict(player.instance_ids)))

    def test_container_pickup_and_npc_action_energy(self):
        world=self.make_world(); npc=world.npcs["npc_003"]
        npc.current_scene="police_station"
        container_id="container:object:evidence_bag"
        world.item_instances.add_new(world,container_id,"bread_loaf",1)
        before_energy=npc.states["energy"]
        result=world.action_registry.execute(
            "PICK_UP_ITEM",npc=npc,
            context=sim.action_context(world,world.scenes["police_station"]),
            item_id="bread_loaf",container_id="object:evidence_bag")
        self.assertTrue(result.success)
        self.assertEqual(before_energy-1,npc.states["energy"])
        self.assertEqual(1,world.inventories[npc.id].quantity("bread_loaf"))

    def test_equipped_item_must_be_unequipped_before_transfer(self):
        world=self.make_world()
        world.player_equipped_item_ids.append("hemp_rope")
        receipt=sim.execute_item_transfer(
            world,action_id="DROP_ITEM",actor_id="player",item_id="hemp_rope")
        self.assertEqual("item_equipped",receipt.code)
        self.assertEqual(1,world.inventories["player"].quantity("hemp_rope"))


if __name__=="__main__":
    unittest.main()
