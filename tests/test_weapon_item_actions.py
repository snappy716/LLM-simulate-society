from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from simulation import runtime as sim


class WeaponItemActionTests(unittest.TestCase):
    def make_world(self):
        output=tempfile.TemporaryDirectory(); self.addCleanup(output.cleanup)
        world=sim.World(sim.Config(
            core_npcs=4,simple_npcs=4,llm_mode="rule",
            log_dir=output.name,verbose=False))
        world.player_scene="market"
        world.npcs["npc_003"].current_scene="market"
        return world

    @staticmethod
    def equip(world,actor_id,item_id="rusted_knife"):
        if world.inventories[actor_id].quantity(item_id)==0:
            world.item_instances.add_new(world,actor_id,item_id,1)
        receipt=sim.execute_equipment_action(
            world,action_id="EQUIP_ITEM",actor_id=actor_id,item_id=item_id)
        return receipt

    def test_threat_requires_equipped_weapon(self):
        world=self.make_world()
        world.item_instances.add_new(world,"player","rusted_knife",1)
        receipt=sim.execute_weapon_threat(
            world,actor_id="player",target_id="npc_003",difficulty_override=1)
        self.assertEqual("weapon_not_equipped",receipt.code)
        self.assertIsNone(receipt.check)

    def test_equipped_weapon_modifies_check_but_does_not_guarantee_success(self):
        world=self.make_world(); equipped=self.equip(world,"player")
        receipt=sim.execute_weapon_threat(
            world,actor_id="player",target_id="npc_003",difficulty_override=200)
        self.assertFalse(receipt.target_yielded)
        self.assertEqual(12,receipt.check.modifiers["items"])
        self.assertEqual(equipped.instance_id,receipt.instance_id)
        self.assertGreater(receipt.fear_delta,0)

    def test_brandishing_marks_exact_instance_and_trace(self):
        world=self.make_world(); equipped=self.equip(world,"player")
        receipt=sim.execute_weapon_threat(
            world,actor_id="player",target_id="npc_003",difficulty_override=1)
        self.assertTrue(receipt.target_yielded)
        instance=world.item_instances.instances[equipped.instance_id]
        self.assertIn("brandished_day_1",instance.evidence_tags)
        self.assertIn(receipt.event_id,instance.provenance_event_ids)
        trace=world.ritual_engine.traces[receipt.consequences.trace_ids[0]]
        self.assertEqual(instance.id,trace.payload["instance_id"])
        self.assertIn(instance.id,
                      world.events_by_day[world.day][-1].object_ids)

    def test_failed_npc_threat_is_completed_action_and_costs_energy(self):
        world=self.make_world(); actor=world.npcs["npc_000"]
        actor.current_scene="market"; self.equip(world,actor.id)
        before=actor.states["energy"]
        result=world.action_registry.execute(
            "THREATEN_WITH_WEAPON",npc=actor,
            context=sim.action_context(world,world.scenes["market"]),
            target=world.npcs["npc_003"],difficulty_override=200)
        self.assertTrue(result.success)
        self.assertEqual("critical_failure",result.outcome)
        self.assertEqual(before-4,actor.states["energy"])

    def test_existing_assault_records_equipped_weapon_instance(self):
        world=self.make_world(); attacker=world.npcs["npc_000"]
        attacker.current_scene="market"; attacker.special_needs["crime_control"]=0
        equipped=self.equip(world,attacker.id)
        with patch.object(world.rng,"randint",side_effect=lambda low,high:high):
            event=sim.execute_special_need_behavior(
                world,attacker,world.scenes["market"],
                sim.PhasePlan("market","测试持械袭击","npc_003",100,"COMMIT_ASSAULT"))
        instance=world.item_instances.instances[equipped.instance_id]
        self.assertIn(instance.id,event.object_ids)
        trace=world.ritual_engine.traces[event.object_ids[0]]
        self.assertEqual(instance.id,trace.payload["instance_id"])
        self.assertIn("assault_day_1",instance.evidence_tags)
        self.assertIn(event.event_id,instance.provenance_event_ids)


if __name__=="__main__":
    unittest.main()
