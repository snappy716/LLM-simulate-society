from __future__ import annotations

import tempfile
import unittest

from simulation import runtime as sim


class NotebookIntelligenceSystemTests(unittest.TestCase):
    def make_world(self):
        output=tempfile.TemporaryDirectory(); self.addCleanup(output.cleanup)
        return sim.World(sim.Config(
            core_npcs=4,simple_npcs=4,llm_mode="rule",
            log_dir=output.name,verbose=False))

    @staticmethod
    def fact(world,actor_id,confidence=.8,distortion=.2):
        return world.intelligence.create(
            subject_id="npc_002",predicate="visited",object_id="warehouse_3",
            day=1,phase="evening",source_type="witness",source_id=actor_id,
            confidence=confidence,secrecy=40,distortion=distortion,
            known_by=[actor_id],summary="有人进入三号仓库。")

    @staticmethod
    def add_notebook(world,actor_id):
        world.item_instances.add_new(world,actor_id,"blank_notebook",1)

    def test_cannot_record_unknown_fact_or_without_notebook(self):
        world=self.make_world(); fact=self.fact(world,"npc_000")
        missing=sim.execute_intelligence_record(
            world,actor_id="npc_000",fact_id=fact.id)
        self.assertEqual("notebook_missing",missing.code)
        self.add_notebook(world,"npc_001")
        unknown=sim.execute_intelligence_record(
            world,actor_id="npc_001",fact_id=fact.id)
        self.assertEqual("unknown_information",unknown.code)

    def test_recording_binds_fact_to_notebook_and_improves_recall(self):
        world=self.make_world(); fact=self.fact(world,"npc_000",.7,.3)
        self.add_notebook(world,"npc_000")
        receipt=sim.execute_intelligence_record(
            world,actor_id="npc_000",fact_id=fact.id)
        self.assertTrue(receipt.success)
        self.assertIn("npc_000",fact.recorded_by)
        self.assertEqual(receipt.instance_id,fact.record_source_instance_ids["npc_000"])
        self.assertGreater(fact.recall_confidence["npc_000"],receipt.confidence_before)
        self.assertLess(fact.recall_distortion["npc_000"],receipt.distortion_before)
        self.assertIn(receipt.event_id,
                      world.item_instances.instances[receipt.instance_id].provenance_event_ids)

    def test_recorded_fact_decays_much_slower_than_memory_only(self):
        world=self.make_world()
        recorded=self.fact(world,"npc_000",.8,.1)
        unrecorded=self.fact(world,"npc_001",.8,.1)
        self.add_notebook(world,"npc_000")
        world.intelligence.record(world,actor_id="npc_000",fact_id=recorded.id)
        for day in range(2,12):
            world.intelligence.decay_day(day)
        self.assertGreater(recorded.recall_confidence["npc_000"],
                           unrecorded.recall_confidence["npc_001"]+.15)
        self.assertLess(recorded.recall_distortion["npc_000"],
                        unrecorded.recall_distortion["npc_001"]-.08)

    def test_recorded_source_transmits_more_accurately(self):
        world=self.make_world(); speaker=world.npcs["npc_000"]
        listener_a=world.npcs["npc_001"]; listener_b=world.npcs["npc_003"]
        recorded=self.fact(world,speaker.id,.8,.1)
        unrecorded=self.fact(world,speaker.id,.8,.1)
        self.add_notebook(world,speaker.id)
        world.intelligence.record(world,actor_id=speaker.id,fact_id=recorded.id)
        world.intelligence.share(recorded.id,speaker,listener_a,truthful=True)
        world.intelligence.share(unrecorded.id,speaker,listener_b,truthful=True)
        self.assertGreater(recorded.recall_confidence[listener_a.id],
                           unrecorded.recall_confidence[listener_b.id])
        self.assertLess(recorded.recall_distortion[listener_a.id],
                        unrecorded.recall_distortion[listener_b.id])

    def test_npc_record_action_consumes_one_energy(self):
        world=self.make_world(); actor=world.npcs["npc_000"]
        fact=self.fact(world,actor.id); self.add_notebook(world,actor.id)
        before=actor.states["energy"]
        result=world.action_registry.execute(
            "RECORD_INTELLIGENCE",npc=actor,
            context=sim.action_context(world,world.scenes[actor.current_scene]),fact_id=fact.id)
        self.assertTrue(result.success)
        self.assertEqual(before-1,actor.states["energy"])


if __name__=="__main__":
    unittest.main()
