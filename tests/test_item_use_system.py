from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simulation import runtime as sim
from simulation.api.legacy_bridge import SimulationBridge  # Explicit retired-runtime fixture only.


class ItemUseSystemTests(unittest.TestCase):
    def make_world(self):
        output=tempfile.TemporaryDirectory()
        self.addCleanup(output.cleanup)
        return sim.World(sim.Config(
            core_npcs=4,simple_npcs=4,llm_mode="rule",
            log_dir=output.name,verbose=False))

    @staticmethod
    def give_item(world,actor_id,item_id):
        inventory=world.economy.actor_inventory(actor_id)
        if inventory.quantity(item_id)==0:
            item=world.item_catalog[item_id]
            if item.unique:
                source_id=next((inventory_id for inventory_id,candidate in world.inventories.items()
                                if candidate.quantity(item_id)>0),None)
                if source_id:
                    world.item_instances.transfer(world,source_id,actor_id,item_id,1)
                    return
            inventory.add(item,1,world.item_catalog)
            world.item_instances.reconcile_inventory(actor_id,world.day)

    def test_every_catalog_item_has_an_executable_or_explicitly_blocked_rule(self):
        world=self.make_world()
        self.assertEqual(set(world.item_catalog),set(world.item_uses.definitions))
        for item_id,definition in world.item_uses.definitions.items():
            with self.subTest(item_id=item_id,mode=definition.mode):
                npc=world.npcs["npc_003"]
                npc.current_scene=definition.required_scenes[0] if definition.required_scenes else "market"
                world.economy.actor_inventory(npc.id).quantities={}
                self.give_item(world,npc.id,item_id)
                before=world.economy.actor_inventory(npc.id).quantity(item_id)
                if definition.mode=="equip":
                    receipt=sim.execute_equipment_action(
                        world,action_id="EQUIP_ITEM",actor_id=npc.id,
                        item_id=item_id,scene_id=npc.current_scene)
                    self.assertTrue(receipt.success,receipt.message)
                    self.assertEqual(before,world.economy.actor_inventory(npc.id).quantity(item_id))
                    self.assertIn(item_id,npc.equipped_item_ids)
                    removed=sim.execute_equipment_action(
                        world,action_id="UNEQUIP_ITEM",actor_id=npc.id,
                        instance_id=receipt.instance_id,scene_id=npc.current_scene)
                    self.assertTrue(removed.success)
                    continue
                receipt=sim.execute_item_use(
                    world,actor_id=npc.id,item_id=item_id,scene_id=npc.current_scene)
                if definition.mode=="blocked":
                    self.assertFalse(receipt.success)
                    self.assertEqual("requires_other_system",receipt.code)
                    self.assertEqual(before,world.economy.actor_inventory(npc.id).quantity(item_id))
                else:
                    self.assertTrue(receipt.success,receipt.message)
                    expected=before-1 if definition.consumes else before
                    self.assertEqual(expected,world.economy.actor_inventory(npc.id).quantity(item_id))

    def test_consumable_equip_read_contextual_and_dangerous_modes(self):
        world=self.make_world(); npc=world.npcs["npc_003"]
        npc.current_scene="market"; npc.states["satiety"]=30
        self.give_item(world,npc.id,"bread_loaf")
        bread=sim.execute_item_use(world,actor_id=npc.id,item_id="bread_loaf",scene_id="market")
        self.assertTrue(bread.consumed)
        self.assertEqual(65,npc.states["satiety"])

        self.give_item(world,npc.id,"padded_coat")
        coat=sim.execute_equipment_action(
            world,action_id="EQUIP_ITEM",actor_id=npc.id,item_id="padded_coat",scene_id="market")
        self.assertTrue(coat.success)
        self.assertEqual(10,npc.item_effects["physical_defense"])

        self.give_item(world,npc.id,"mystery_letter")
        letter=sim.execute_item_use(world,actor_id=npc.id,item_id="mystery_letter",scene_id="market")
        self.assertIn(letter.knowledge_added,npc.knowledge)

        self.give_item(world,npc.id,"warehouse_3_key")
        wrong=sim.execute_item_use(world,actor_id=npc.id,item_id="warehouse_3_key",scene_id="market")
        self.assertEqual("wrong_scene",wrong.code)
        npc.current_scene="warehouse_3"
        key=sim.execute_item_use(world,actor_id=npc.id,item_id="warehouse_3_key",scene_id="warehouse_3")
        self.assertTrue(key.success)
        self.assertEqual(100,npc.item_effects["warehouse_3_access"])

        self.give_item(world,npc.id,"sealed_music_box")
        sanity=npc.sanity
        box=sim.execute_item_use(world,actor_id=npc.id,item_id="sealed_music_box",scene_id="warehouse_3")
        self.assertTrue(box.success)
        self.assertEqual(sanity-20,npc.sanity)
        self.assertEqual("DANGEROUS_ITEM_USED",world.events_by_day[1][-1].event_type)

    def test_registered_use_item_spends_one_action_energy(self):
        world=self.make_world(); npc=world.npcs["npc_003"]
        npc.current_scene="market"; npc.states["satiety"]=30
        self.give_item(world,npc.id,"bread_loaf")
        energy=npc.states["energy"]
        result=world.action_registry.execute(
            "USE_ITEM",npc=npc,context=sim.action_context(world,world.scenes["market"]),
            item_id="bread_loaf")
        self.assertTrue(result.success)
        self.assertEqual(energy-1,npc.states["energy"])

    def test_player_uses_same_service_through_bridge(self):
        output=tempfile.TemporaryDirectory(); self.addCleanup(output.cleanup)
        bridge=SimulationBridge(output_dir=Path(output.name))
        bridge.world.player_states["satiety"]=40
        before=bridge.world.inventories["player"].quantity("bread_loaf")
        response=bridge.use_item({"actor_id":"player","item_id":"bread_loaf"})
        self.assertTrue(response["ok"])
        self.assertEqual(before-1,bridge.world.inventories["player"].quantity("bread_loaf"))
        self.assertEqual(75,response["snapshot"]["player"]["states"]["satiety"])

    def test_prepared_and_equipped_items_modify_existing_checks(self):
        base=self.make_world(); boosted=self.make_world()
        for world in (base,boosted):
            world.npcs["npc_003"].current_scene="market"
            world.npcs["npc_004"].current_scene="market"
        actor=boosted.npcs["npc_003"]
        self.give_item(boosted,actor.id,"makeup_kit")
        sim.execute_item_use(boosted,actor_id=actor.id,item_id="makeup_kit",scene_id="market")
        before=sim.resolve_opposed_check(
            base,"伪装",base.npcs["npc_003"],base.npcs["npc_004"],
            "deception","observation",scene_id="market")
        after=sim.resolve_opposed_check(
            boosted,"伪装",boosted.npcs["npc_003"],boosted.npcs["npc_004"],
            "deception","observation",scene_id="market")
        self.assertEqual(before.actor_roll,after.actor_roll)
        self.assertEqual(25,after.actor_modifiers["items"])
        self.assertEqual(before.actor_total+25,after.actor_total)


if __name__ == "__main__":
    unittest.main()
