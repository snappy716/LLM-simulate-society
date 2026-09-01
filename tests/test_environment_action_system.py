from __future__ import annotations

import tempfile
import unittest

from simulation import runtime as sim
from simulation.systems.action_resolution import outcome_for_margin


class EnvironmentActionSystemTests(unittest.TestCase):
    def make_world(self):
        output=tempfile.TemporaryDirectory(); self.addCleanup(output.cleanup)
        return sim.World(sim.Config(
            core_npcs=4,simple_npcs=4,llm_mode="rule",
            log_dir=output.name,verbose=False))

    @staticmethod
    def add(world,actor_id,item_id):
        if world.inventories[actor_id].quantity(item_id)==0:
            world.item_instances.add_new(world,actor_id,item_id,1)

    def test_margin_maps_to_five_outcome_tiers(self):
        self.assertEqual("complete_success",outcome_for_margin(40))
        self.assertEqual("success",outcome_for_margin(15))
        self.assertEqual("partial",outcome_for_margin(0))
        self.assertEqual("failure",outcome_for_margin(-15))
        self.assertEqual("critical_failure",outcome_for_margin(-40))

    def test_prepared_item_changes_check_but_does_not_guarantee_success(self):
        base=self.make_world(); boosted=self.make_world()
        for world in (base,boosted):
            world.npcs["npc_003"].current_scene="market"
        actor=boosted.npcs["npc_003"]; self.add(boosted,actor.id,"lockpick_set")
        prepared=sim.execute_item_use(
            boosted,actor_id=actor.id,item_id="lockpick_set",scene_id="market")
        self.assertTrue(prepared.success)
        before=base.environment_checks.resolve(
            base,actor_id="npc_003",check_type="技巧开锁",skill="lockpicking",
            difficulty=100,item_effect_names=["lockpicking_bonus"])
        after=boosted.environment_checks.resolve(
            boosted,actor_id="npc_003",check_type="技巧开锁",skill="lockpicking",
            difficulty=100,item_effect_names=["lockpicking_bonus"])
        self.assertEqual(before.roll,after.roll)
        self.assertEqual(25,after.modifiers["items"])
        self.assertEqual(before.total+25,after.total)

    def test_failure_generates_scaled_risk_trace_noise_and_tool_damage(self):
        world=self.make_world(); actor=world.npcs["npc_003"]
        actor.current_scene="market"; self.add(world,actor.id,"lockpick_set")
        instance=world.item_instances.instances_for(actor.id,"lockpick_set",world.day)[0]
        sim.execute_item_use(world,actor_id=actor.id,item_id="lockpick_set",scene_id="market")
        check,consequences,event=sim.resolve_environment_action(
            world,actor_id=actor.id,scene_id="market",target_id="test_lock",
            check_type="非法开锁",skill="lockpicking",difficulty=200,
            item_effect_names=["lockpicking_bonus"],base_legal_risk=10,
            base_noise=40,trace_type="tool_marks",trace_discoverability=55,
            tool_instance_id=instance.id)
        self.assertEqual("critical_failure",check.outcome)
        self.assertEqual(20,consequences.legal_risk_delta)
        self.assertEqual(100,consequences.noise)
        self.assertEqual(-30,consequences.item_condition_delta)
        self.assertEqual(70,instance.condition)
        self.assertEqual(1,len(consequences.trace_ids))
        self.assertIn(consequences.trace_ids[0],world.ritual_engine.traces)
        self.assertTrue(consequences.detected)
        self.assertEqual(event.event_id,world.events_by_day[1][-1].event_id)
        # The prepared tool grants one attempt and is consumed as an effect charge.
        self.assertNotIn("lockpicking_bonus",actor.item_effects)

    def test_player_and_npc_use_the_same_fixed_difficulty_service(self):
        world=self.make_world(); world.player_scene="market"
        player=world.environment_checks.resolve(
            world,actor_id="player",check_type="攀爬",skill="climbing",difficulty=70)
        self.assertEqual(world.player_skills["climbing"],player.modifiers["skill"])
        self.assertEqual("player",player.actor_id)


if __name__=="__main__":
    unittest.main()
