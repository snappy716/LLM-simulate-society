import unittest

from emergent_town.models import TraceEvidence
from town_demo import (Config, Phase, PhasePlan, World, execute_behavior,
                       professional_duty_plan, resolve_end_of_day, special_need_plan)


class SpecialNeedTests(unittest.TestCase):
    def setUp(self):
        self.world = World(Config(core_npcs=20, simple_npcs=180, llm_mode="rule",
                                  log_dir="runs/test_special_needs", verbose=False))

    def test_criminal_need_produces_a_concrete_crime_plan(self):
        criminal = next(n for n in self.world.npcs.values()
                        if n.sequence_pathway == "罪犯")
        criminal.special_needs["crime_control"] = 10
        plan = special_need_plan(self.world, criminal, Phase.EVENING)
        self.assertIn(plan.behavior,
                      {"COMMIT_BURGLARY", "COMMIT_PICKPOCKET", "COMMIT_ASSAULT"})
        self.assertIn(plan.scene_id, self.world.scenes)

    def test_crime_attempt_leaves_trace_and_consumes_need(self):
        criminal = next(n for n in self.world.npcs.values()
                        if n.sequence_pathway == "罪犯")
        victim = next(n for n in self.world.npcs.values() if n.id != criminal.id)
        criminal.special_needs["crime_control"] = 10
        scene = self.world.scenes[victim.home_scene]
        before = len(self.world.ritual_engine.traces)
        event = execute_behavior(self.world, criminal, scene,
                                 PhasePlan(scene.id, "测试入室盗窃", victim.id, 90,
                                           "COMMIT_BURGLARY"))
        self.assertIn(event.event_type, {"CRIME_COMMITTED", "CRIME_ATTEMPT_EXPOSED"})
        self.assertGreater(len(self.world.ritual_engine.traces), before)
        self.assertGreater(criminal.special_needs["crime_control"], 10)

    def test_official_duty_creates_patrol_plan_without_case(self):
        self.world.cases.clear()
        official = next(n for n in self.world.npcs.values()
                        if n.layer == "official_beyonder")
        self.world.day = next(weekday for weekday in range(7)
                              if weekday in official.work_days) + 1
        phase = Phase(official.work_phases[0])
        plan = professional_duty_plan(self.world, official, phase)
        self.assertEqual("PATROL_SCENE", plan.behavior)
        self.assertNotIn("official_duty", official.special_needs)

    def test_patrol_trace_discovery_opens_case(self):
        self.world.cases.clear()
        official = next(n for n in self.world.npcs.values()
                        if n.layer == "official_beyonder")
        trace = TraceEvidence("trace_test_crime", "burglary", "market", 1, "morning",
                              "COMMIT_BURGLARY", ["npc_015"], 100, False)
        self.world.ritual_engine.traces[trace.id] = trace
        execute_behavior(self.world, official, self.world.scenes["market"],
                         PhasePlan("market", "测试巡逻", priority=90,
                                   behavior="PATROL_SCENE"))
        self.assertIn(official.id, trace.discovered_by)
        self.assertTrue(any(trace.id in case.evidence_ids
                            for case in self.world.cases.values()))

    def test_secret_supplicant_need_creates_illegal_ritual_plan(self):
        supplicant = next(n for n in self.world.npcs.values()
                          if n.sequence_pathway == "秘祈人"
                          and n.layer == "hostile_beyonder")
        supplicant.special_needs["ritual_stability"] = 10
        supplicant.states["legal_risk"] = 0
        plan = special_need_plan(self.world, supplicant, Phase.LATE_NIGHT)
        self.assertEqual("PERFORM_INDEPENDENT_RITUAL", plan.behavior)

    def test_arrested_and_hospitalized_characters_freeze_special_needs(self):
        criminal = next(n for n in self.world.npcs.values()
                        if "crime_control" in n.special_needs)
        criminal.special_needs["crime_control"] = 50
        criminal.disposition_status = "arrested"
        supplicant = next(n for n in self.world.npcs.values()
                          if "ritual_stability" in n.special_needs)
        supplicant.special_needs["ritual_stability"] = 50
        supplicant.health = 20
        resolve_end_of_day(self.world)
        self.assertEqual(50,criminal.special_needs["crime_control"])
        self.assertEqual(50,supplicant.special_needs["ritual_stability"])


if __name__ == "__main__":
    unittest.main()
