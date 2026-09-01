from __future__ import annotations

import tempfile
import unittest

from simulation import runtime as sim


class EquipmentEffectSystemTests(unittest.TestCase):
    def make_world(self):
        output=tempfile.TemporaryDirectory(); self.addCleanup(output.cleanup)
        return sim.World(sim.Config(
            core_npcs=4,simple_npcs=4,llm_mode="rule",
            log_dir=output.name,verbose=False))

    @staticmethod
    def add(world,actor_id,item_id):
        if world.inventories[actor_id].quantity(item_id)==0:
            world.item_instances.add_new(world,actor_id,item_id,1)

    def test_equip_and_unequip_bind_effect_to_instance_and_slot(self):
        world=self.make_world(); self.add(world,"player","padded_coat")
        equipped=sim.execute_equipment_action(
            world,action_id="EQUIP_ITEM",actor_id="player",item_id="padded_coat")
        self.assertTrue(equipped.success)
        self.assertEqual(equipped.instance_id,world.player_equipment_slots["body"])
        self.assertEqual("body",world.item_instances.instances[equipped.instance_id].equipped_slot)
        self.assertEqual(10,world.player_item_effects["physical_defense"])
        self.assertTrue(world.player_item_effect_records[0].requires_equipped)
        removed=sim.execute_equipment_action(
            world,action_id="UNEQUIP_ITEM",actor_id="player",slot="body")
        self.assertTrue(removed.success)
        self.assertEqual({},world.player_equipment_slots)
        self.assertEqual({},world.player_item_effects)
        self.assertIsNone(world.item_instances.instances[equipped.instance_id].equipped_slot)

    def test_occupied_slot_rejects_without_mutation(self):
        world=self.make_world()
        for item_id in ("walking_cane","rusted_knife"):
            self.add(world,"player",item_id)
        first=sim.execute_equipment_action(
            world,action_id="EQUIP_ITEM",actor_id="player",item_id="walking_cane")
        before=(dict(world.player_equipment_slots),dict(world.player_item_effects))
        second=sim.execute_equipment_action(
            world,action_id="EQUIP_ITEM",actor_id="player",item_id="rusted_knife")
        self.assertEqual("slot_occupied",second.code)
        self.assertEqual(before,(world.player_equipment_slots,world.player_item_effects))
        self.assertEqual("main_hand",world.item_instances.instances[first.instance_id].equipped_slot)

    def test_use_item_directs_equipment_to_explicit_action(self):
        world=self.make_world(); npc=world.npcs["npc_003"]
        self.add(world,npc.id,"leather_gloves")
        receipt=sim.execute_item_use(
            world,actor_id=npc.id,item_id="leather_gloves",scene_id=npc.current_scene)
        self.assertEqual("requires_equip_action",receipt.code)
        self.assertEqual({},npc.equipment_slots)

    def test_temporary_effect_expires_at_configured_phase(self):
        world=self.make_world(); npc=world.npcs["npc_003"]
        self.add(world,npc.id,"makeup_kit")
        receipt=sim.execute_item_use(
            world,actor_id=npc.id,item_id="makeup_kit",scene_id=npc.current_scene)
        self.assertTrue(receipt.success)
        self.assertEqual(25,npc.item_effects["disguise_bonus"])
        self.assertEqual(4,npc.item_effect_records[0].expires_at)
        world.day=2; world.phase=sim.Phase.MORNING
        expired=world.item_effect_system.expire(world)
        self.assertEqual(1,len(expired))
        self.assertEqual({},npc.item_effects)

    def test_reusing_preparation_refreshes_instead_of_stacking(self):
        world=self.make_world(); npc=world.npcs["npc_003"]
        self.add(world,npc.id,"makeup_kit")
        for _ in range(2):
            receipt=sim.execute_item_use(
                world,actor_id=npc.id,item_id="makeup_kit",scene_id=npc.current_scene)
            self.assertTrue(receipt.success)
        records=[record for record in npc.item_effect_records if record.effect=="disguise_bonus"]
        self.assertEqual(1,len(records))
        self.assertEqual(25,npc.item_effects["disguise_bonus"])

    def test_npc_equipment_actions_consume_energy(self):
        world=self.make_world(); npc=world.npcs["npc_003"]
        self.add(world,npc.id,"walking_cane")
        before=npc.states["energy"]
        result=world.action_registry.execute(
            "EQUIP_ITEM",npc=npc,context=sim.action_context(world,world.scenes[npc.current_scene]),
            item_id="walking_cane")
        self.assertTrue(result.success)
        self.assertEqual(before-1,npc.states["energy"])


if __name__=="__main__":
    unittest.main()
