import unittest
from unittest.mock import patch

from town_demo import (Config, Phase, PhasePlan, World, execute_behavior,
                       generate_harm_and_report_reactions, handle_incident_report,
                       arrest_suspect, resolve_phase_plan, submit_incident_report)


class IncidentResponseTests(unittest.TestCase):
    def setUp(self):
        self.world = World(Config(core_npcs=20, simple_npcs=180, llm_mode="rule",
                                  log_dir="runs/test_incident_response", verbose=False))

    def _fatal_assault(self):
        attacker = next(n for n in self.world.npcs.values()
                        if n.sequence_pathway == "罪犯")
        victim = next(n for n in self.world.npcs.values()
                      if n.id != attacker.id and any(
                          "朋友" in relation.kinds or "爱人" in relation.kinds
                          for relation in n.relationships.values()))
        victim.health = 40
        victim.current_scene = victim.home_scene
        attacker.current_scene = victim.home_scene
        attacker.special_needs["crime_control"] = 0
        scene = self.world.scenes[victim.home_scene]
        with patch.object(self.world.rng, "randint", side_effect=lambda low, high: high):
            event = execute_behavior(
                self.world, attacker, scene,
                PhasePlan(scene.id, "测试致命袭击", victim.id, 100, "COMMIT_ASSAULT"))
        return attacker, victim, event

    def test_assault_can_kill_and_friends_prepare_detailed_reports(self):
        attacker, victim, event = self._fatal_assault()
        self.assertEqual("dead", victim.disposition_status)
        self.assertTrue(any(e.event_type == "DEATH_FROM_ASSAULT"
                            for e in self.world.events_by_day[self.world.day]))
        generate_harm_and_report_reactions(self.world, [event])
        reports = list(self.world.incident_reports.values())
        self.assertTrue(reports)
        self.assertEqual(1, len(reports))
        self.assertNotEqual(attacker.id, reports[0].reporter_id)
        self.assertNotIn(attacker.id, reports[0].supplementary_reporter_ids)
        self.assertTrue(any(report.reporter_id != victim.id for report in reports))
        for report in reports:
            self.assertEqual(victim.home_scene, report.scene_id)
            self.assertIn(self.world.scenes[victim.home_scene].name, report.full_account)
            self.assertIn(event.description, report.full_account)
            self.assertIn(attacker.id, report.suspect_ids)

    def test_report_is_assigned_then_police_handle_original_scene(self):
        _, victim, event = self._fatal_assault()
        generate_harm_and_report_reactions(self.world, [event])
        report = next(iter(self.world.incident_reports.values()))
        reporter = self.world.npcs[report.reporter_id]
        submit_incident_report(self.world, reporter, self.world.scenes["police_station"])
        self.assertEqual("assigned", report.status)
        self.assertTrue(report.assigned_officer_ids)
        officer = self.world.npcs[report.assigned_officer_ids[0]]
        self.assertTrue(any(d.behavior == "HANDLE_INCIDENT_REPORT"
                            and d.scene_id == victim.home_scene
                            for d in officer.response_drives))
        handled = handle_incident_report(self.world, officer,
                                         self.world.scenes[victim.home_scene])
        self.assertEqual("INCIDENT_SCENE_HANDLED", handled.event_type)
        self.assertEqual("handled", report.status)
        self.assertIn(report.full_account, handled.description)

    def test_fatal_case_authorizes_and_executes_arrest(self):
        attacker, victim, event = self._fatal_assault()
        generate_harm_and_report_reactions(self.world, [event])
        report = next(iter(self.world.incident_reports.values()))
        reporter = self.world.npcs[report.reporter_id]
        submit_incident_report(self.world, reporter, self.world.scenes["police_station"])
        officer = self.world.npcs[report.assigned_officer_ids[0]]
        handle_incident_report(self.world, officer, self.world.scenes[victim.home_scene])
        case = self.world.cases[report.case_id]
        self.assertEqual("arrest_authorized", case.stage)
        officer.skills["combat"] = 100
        attacker.skills["stealth"] = 0
        with patch.object(self.world.rng, "randint", return_value=50):
            result = arrest_suspect(
                self.world, officer, self.world.scenes[attacker.current_scene],
                PhasePlan(attacker.current_scene, "执行逮捕", attacker.id, 108,
                          "ARREST_SUSPECT"))
        self.assertEqual("SUSPECT_ARRESTED", result.event_type)
        self.assertEqual("arrested", attacker.disposition_status)
        self.assertEqual("resolved", case.status)

    def test_critical_injury_overrides_work_with_hospital_treatment(self):
        npc = next(n for n in self.world.npcs.values() if n.occupation != "警察")
        npc.health = 10
        plan = resolve_phase_plan(self.world, npc, Phase.MORNING)
        self.assertEqual("SEEK_HELP", plan.behavior)
        self.assertEqual("hospital", plan.scene_id)


if __name__ == "__main__":
    unittest.main()
