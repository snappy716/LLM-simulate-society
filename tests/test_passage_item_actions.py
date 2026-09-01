from __future__ import annotations

import tempfile
import unittest

from simulation import runtime as sim


class PassageItemActionTests(unittest.TestCase):
    def make_world(self):
        output=tempfile.TemporaryDirectory(); self.addCleanup(output.cleanup)
        return sim.World(sim.Config(
            core_npcs=4,simple_npcs=4,llm_mode="rule",
            log_dir=output.name,verbose=False))

    @staticmethod
    def add(world,actor_id,item_id):
        if world.inventories[actor_id].quantity(item_id)==0:
            world.item_instances.add_new(world,actor_id,item_id,1)

    def test_matching_key_opens_without_check_then_passage_can_be_traversed(self):
        world=self.make_world(); world.player_scene="warehouse_3"
        picked=sim.execute_item_transfer(
            world,action_id="PICK_UP_ITEM",actor_id="player",item_id="warehouse_3_key")
        self.assertTrue(picked.success)
        opened=sim.execute_passage_action(
            world,action_id="UNLOCK_WITH_KEY",actor_id="player",
            passage_id="warehouse_3_side_door")
        self.assertTrue(opened.success)
        self.assertIsNone(opened.check)
        self.assertEqual("open",world.passages.passages[opened.passage_id].state)
        moved=sim.execute_passage_action(
            world,action_id="TRAVERSE_PASSAGE",actor_id="player",
            passage_id="warehouse_3_side_door")
        self.assertTrue(moved.success)
        self.assertEqual("east_dock",world.player_scene)

    def test_lockpick_failure_leaves_lock_and_creates_marks_and_damage(self):
        world=self.make_world(); world.player_scene="east_dock"
        self.add(world,"player","lockpick_set")
        passage=world.passages.passages["warehouse_3_side_door"]
        passage.lock_difficulty=200
        instance=world.item_instances.instances_for("player","lockpick_set",world.day)[0]
        receipt=sim.execute_passage_action(
            world,action_id="PICK_LOCK",actor_id="player",passage_id=passage.id)
        self.assertFalse(receipt.success)
        self.assertEqual("critical_failure",receipt.check.outcome)
        self.assertEqual(25,receipt.check.modifiers["items"])
        self.assertEqual("locked",passage.state)
        self.assertEqual(70,instance.condition)
        self.assertEqual(1,len(receipt.consequences.trace_ids))

    def test_crowbar_is_reliable_but_always_noisy_and_leaves_damage(self):
        world=self.make_world(); world.player_scene="east_dock"
        self.add(world,"player","crowbar")
        passage=world.passages.passages["warehouse_3_side_door"]
        passage.force_difficulty=1
        receipt=sim.execute_passage_action(
            world,action_id="FORCE_OPEN",actor_id="player",passage_id=passage.id)
        self.assertTrue(receipt.success)
        self.assertIn(receipt.check.outcome,{"complete_success","success"})
        self.assertEqual(25,receipt.check.modifiers["items"])
        self.assertEqual("broken",passage.state)
        self.assertGreaterEqual(receipt.consequences.noise,43)
        self.assertEqual(1,len(receipt.consequences.trace_ids))

    def test_rope_enables_special_entry_but_still_checks_climbing(self):
        world=self.make_world(); world.player_scene="east_dock"
        passage=world.passages.passages["warehouse_3_roof_entry"]
        passage.climb_difficulty=1
        receipt=sim.execute_passage_action(
            world,action_id="CLIMB_WITH_ROPE",actor_id="player",passage_id=passage.id)
        self.assertTrue(receipt.success)
        self.assertEqual(20,receipt.check.modifiers["items"])
        self.assertTrue(receipt.moved)
        self.assertEqual("warehouse_3",world.player_scene)
        self.assertEqual("inaccessible",passage.state)

    def test_missing_tool_rejects_without_check_or_state_change(self):
        world=self.make_world(); world.player_scene="east_dock"
        passage=world.passages.passages["warehouse_3_side_door"]
        receipt=sim.execute_passage_action(
            world,action_id="PICK_LOCK",actor_id="player",passage_id=passage.id)
        self.assertEqual("tool_missing_or_broken",receipt.code)
        self.assertIsNone(receipt.check)
        self.assertEqual("locked",passage.state)

    def test_failed_checked_action_still_consumes_npc_action_energy(self):
        world=self.make_world(); npc=world.npcs["npc_003"]
        npc.current_scene="east_dock"; self.add(world,npc.id,"lockpick_set")
        world.passages.passages["warehouse_3_side_door"].lock_difficulty=200
        before=npc.states["energy"]
        result=world.action_registry.execute(
            "PICK_LOCK",npc=npc,context=sim.action_context(world,world.scenes["east_dock"]),
            passage_id="warehouse_3_side_door")
        self.assertTrue(result.success)  # The attempt completed even though the check failed.
        self.assertEqual("critical_failure",result.outcome)
        self.assertEqual(before-3,npc.states["energy"])


if __name__=="__main__":
    unittest.main()
