from __future__ import annotations

import tempfile
import unittest

from simulation import runtime as sim


class IdentityItemActionTests(unittest.TestCase):
    def make_world(self):
        output=tempfile.TemporaryDirectory(); self.addCleanup(output.cleanup)
        world=sim.World(sim.Config(
            core_npcs=4,simple_npcs=4,llm_mode="rule",
            log_dir=output.name,verbose=False))
        world.player_scene="market"
        world.npcs["npc_003"].current_scene="market"
        return world

    @staticmethod
    def add(world,actor_id,item_id):
        if world.inventories[actor_id].quantity(item_id)==0:
            world.item_instances.add_new(world,actor_id,item_id,1)

    def test_makeup_requires_preparation_then_changes_check(self):
        world=self.make_world(); self.add(world,"player","makeup_kit")
        rejected=sim.execute_identity_action(
            world,actor_id="player",inspector_id="npc_003",item_id="makeup_kit",
            difficulty_override=1)
        self.assertEqual("disguise_not_prepared",rejected.code)
        self.assertIsNone(rejected.check)
        used=sim.execute_item_use(
            world,actor_id="player",item_id="makeup_kit",scene_id="market")
        self.assertTrue(used.success)
        checked=sim.execute_identity_action(
            world,actor_id="player",inspector_id="npc_003",item_id="makeup_kit",
            difficulty_override=1)
        self.assertTrue(checked.accepted)
        self.assertEqual(25,checked.check.modifiers["items"])

    def test_forged_papers_work_directly_but_exposure_leaves_evidence(self):
        world=self.make_world(); self.add(world,"player","forged_identity_papers")
        receipt=sim.execute_identity_action(
            world,actor_id="player",inspector_id="npc_003",
            item_id="forged_identity_papers",difficulty_override=200)
        self.assertFalse(receipt.accepted)
        self.assertEqual("critical_failure",receipt.check.outcome)
        self.assertEqual(40,receipt.check.modifiers["items"])
        self.assertGreater(receipt.consequences.legal_risk_delta,0)
        instance=world.item_instances.instances[receipt.instance_id]
        self.assertIn("exposed_forgery",instance.evidence_tags)
        self.assertEqual(1,len(receipt.consequences.trace_ids))
        trace=world.ritual_engine.traces[receipt.consequences.trace_ids[0]]
        self.assertEqual(instance.id,trace.payload["instance_id"])

    def test_badge_must_be_equipped_and_does_not_guarantee_success(self):
        world=self.make_world(); self.add(world,"player","blackthorn_badge")
        rejected=sim.execute_identity_action(
            world,actor_id="player",inspector_id="npc_003",item_id="blackthorn_badge")
        self.assertEqual("credential_not_equipped",rejected.code)
        equipped=sim.execute_equipment_action(
            world,action_id="EQUIP_ITEM",actor_id="player",item_id="blackthorn_badge")
        self.assertTrue(equipped.success)
        checked=sim.execute_identity_action(
            world,actor_id="player",inspector_id="npc_003",item_id="blackthorn_badge",
            difficulty_override=200)
        self.assertEqual(45,world.item_uses.definition("blackthorn_badge").grants_effects["official_identity_bonus"])
        self.assertEqual(40,checked.check.modifiers["items"])
        self.assertFalse(checked.accepted)

    def test_failed_npc_inspection_consumes_energy_and_raises_suspicion(self):
        world=self.make_world(); actor=world.npcs["npc_000"]; inspector=world.npcs["npc_003"]
        actor.current_scene="market"; self.add(world,actor.id,"forged_identity_papers")
        before=actor.states["energy"]
        result=world.action_registry.execute(
            "PRESENT_IDENTITY",npc=actor,
            context=sim.action_context(world,world.scenes["market"]),target=inspector,
            item_id="forged_identity_papers",difficulty_override=200)
        self.assertTrue(result.success)
        self.assertEqual("critical_failure",result.outcome)
        self.assertEqual(before-2,actor.states["energy"])
        self.assertGreater(inspector.relationships[actor.id].suspicion,0)


if __name__=="__main__":
    unittest.main()
