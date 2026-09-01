from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from simulation import runtime as sim


class RitualMaterialSystemTests(unittest.TestCase):
    def make_world(self):
        output=tempfile.TemporaryDirectory(); self.addCleanup(output.cleanup)
        return sim.World(sim.Config(
            core_npcs=4,simple_npcs=4,llm_mode="rule",
            log_dir=output.name,verbose=False))

    @staticmethod
    def add(world,actor_id,item_id,quantity=1):
        world.item_instances.add_new(world,actor_id,item_id,quantity)

    def test_materials_cannot_be_consumed_separately(self):
        world=self.make_world(); self.add(world,"player","ritual_chalk")
        before=world.inventories["player"].quantity("ritual_chalk")
        receipt=sim.execute_item_use(
            world,actor_id="player",item_id="ritual_chalk",scene_id=world.player_scene)
        self.assertEqual("requires_other_system",receipt.code)
        self.assertEqual(before,world.inventories["player"].quantity("ritual_chalk"))

    def test_missing_secret_recipe_consumes_nothing(self):
        world=self.make_world(); self.add(world,"player","ritual_chalk")
        before=dict(world.inventories["player"].quantities)
        receipt=sim.execute_item_ritual(world,actor_id="player",illegal=True)
        self.assertEqual("missing_materials",receipt.code)
        self.assertEqual({"gray_ritual_powder":1},receipt.missing_items)
        self.assertEqual(before,world.inventories["player"].quantities)
        self.assertEqual("RITUAL_BLOCKED_MISSING_MATERIAL",
                         world.events_by_day[world.day][-1].event_type)

    def test_secret_recipe_is_atomic_and_changes_check_and_side_effects(self):
        world=self.make_world()
        self.add(world,"player","ritual_chalk"); self.add(world,"player","gray_ritual_powder")
        sanity=world.player_sanity; risk=world.player_states["legal_risk"]
        receipt=sim.execute_item_ritual(
            world,actor_id="player",illegal=True,difficulty_override=200)
        self.assertTrue(receipt.success)  # The ritual was attempted; its check may fail.
        self.assertEqual(27,receipt.material_bonus)
        self.assertEqual(27,receipt.check.modifiers["items"])
        self.assertEqual(0,world.inventories["player"].quantity("ritual_chalk"))
        self.assertEqual(0,world.inventories["player"].quantity("gray_ritual_powder"))
        self.assertEqual(sanity-3,world.player_sanity)
        self.assertGreater(world.player_states["legal_risk"],risk)
        self.assertEqual({"ritual_chalk":1,"gray_ritual_powder":1},receipt.consumed_items)

    def test_legal_ritual_only_consumes_chalk(self):
        world=self.make_world()
        self.add(world,"player","ritual_chalk"); self.add(world,"player","gray_ritual_powder")
        receipt=sim.execute_item_ritual(
            world,actor_id="player",illegal=False,difficulty_override=1)
        self.assertTrue(receipt.ritual_succeeded)
        self.assertEqual(10,receipt.material_bonus)
        self.assertEqual(0,world.inventories["player"].quantity("ritual_chalk"))
        self.assertEqual(1,world.inventories["player"].quantity("gray_ritual_powder"))

    def test_seeded_hostile_ritualist_has_finite_recipe_and_operation_consumes_it(self):
        world=self.make_world(); leader=world.npcs["npc_002"]
        self.assertEqual(1,world.inventories[leader.id].quantity("ritual_chalk"))
        self.assertEqual(1,world.inventories[leader.id].quantity("gray_ritual_powder"))
        operation=next(iter(world.ritual_engine.operations.values()))
        operation.current_stage_index=3
        world.day=operation.scheduled_day; world.phase=sim.Phase.LATE_NIGHT
        with patch.object(world.rng,"randint",side_effect=lambda low,high:high):
            sim.advance_illegal_operations(world,sim.Phase.LATE_NIGHT)
        self.assertEqual(0,world.inventories[leader.id].quantity("ritual_chalk"))
        self.assertEqual(0,world.inventories[leader.id].quantity("gray_ritual_powder"))
        event=next(event for event in world.events_by_day[world.day]
                   if event.event_type=="ILLEGAL_OPERATION_STAGE")
        self.assertIn("ritual_chalk",event.object_ids)
        trace=world.ritual_engine.traces[event.object_ids[0]]
        self.assertEqual(27,trace.payload["material_bonus"])

    def test_special_need_is_not_satisfied_when_materials_are_missing(self):
        world=self.make_world(); actor=world.npcs["npc_002"]
        actor.current_scene="underground_market"; actor.special_needs["ritual_stability"]=10
        world.inventories[actor.id].quantities.pop("ritual_chalk",None)
        world.inventories[actor.id].quantities.pop("gray_ritual_powder",None)
        event=sim.execute_special_need_behavior(
            world,actor,world.scenes["underground_market"],
            sim.PhasePlan("underground_market","测试缺少材料",None,90,
                          "PERFORM_INDEPENDENT_RITUAL"))
        self.assertEqual("RITUAL_BLOCKED_MISSING_MATERIAL",event.event_type)
        self.assertEqual(10,actor.special_needs["ritual_stability"])

    def test_failed_registered_ritual_attempt_still_costs_energy(self):
        world=self.make_world(); actor=world.npcs["npc_003"]
        self.add(world,actor.id,"ritual_chalk"); self.add(world,actor.id,"gray_ritual_powder")
        before=actor.states["energy"]
        result=world.action_registry.execute(
            "PERFORM_SECRET_RITUAL",npc=actor,
            context=sim.action_context(world,world.scenes[actor.current_scene]),
            difficulty_override=200)
        self.assertTrue(result.success)
        self.assertEqual("critical_failure",result.outcome)
        self.assertEqual(before-12,actor.states["energy"])


if __name__=="__main__":
    unittest.main()
