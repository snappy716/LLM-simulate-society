from __future__ import annotations

import json
import unittest
from pathlib import Path

from simulation.cognition.focus_slots import FocusCandidate, FocusSlotAllocator
from simulation.domain.campus import (
    BaseAttributes,
    CampusNPCProfile,
    PersonalityTraits,
    SimulationTier,
    derive_stats,
)
from simulation.domain.tasks import CampusTask, ForumKind, TaskState
from simulation.narrative.demo_calendar import DEMO_STAGES, day_role, stage_for_day
from simulation.systems.decision_scoring import DecisionFactors, score_action
from simulation.systems.task_board import TaskBoard, TaskConflictError


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class CampusDomainTests(unittest.TestCase):
    def test_base_attributes_and_derived_stats_follow_design_formulas(self):
        ordinary = BaseAttributes()
        stats = derive_stats(ordinary, identity_anchor_count=2)
        self.assertEqual(100, stats.max_health)
        self.assertEqual(70, stats.max_focus)
        self.assertEqual(70, stats.stability_threshold)
        self.assertEqual(15, stats.speed)
        self.assertEqual(15, stats.physical_power)
        self.assertEqual(15, stats.technique_power)
        self.assertEqual(15, stats.cognitive_power)
        self.assertEqual(15, stats.support_power)
        self.assertEqual(8.5, stats.defense)

    def test_attribute_and_personality_ranges_are_enforced(self):
        with self.assertRaises(ValueError):
            BaseAttributes(physique=11)
        with self.assertRaises(ValueError):
            PersonalityTraits(risk_tolerance=-1)

    def test_awakened_profile_must_be_focused(self):
        with self.assertRaises(ValueError):
            CampusNPCProfile(
                npc_id="npc_001",
                college_id="psychology",
                occupation_id="student",
                attributes=BaseAttributes(),
                personality=PersonalityTraits(),
                simulation_tier=SimulationTier.PERSISTENT,
                awakened_by_player=True,
            )


class DecisionScoringTests(unittest.TestCase):
    def test_risk_tolerance_changes_risky_action_score(self):
        factors = DecisionFactors(goal_progress=70, risk=80)
        cautious = score_action(PersonalityTraits(risk_tolerance=10), factors)
        daring = score_action(PersonalityTraits(risk_tolerance=90), factors)
        self.assertGreater(daring.total, cautious.total)
        self.assertLess(cautious.contributions["risk"], daring.contributions["risk"])

    def test_moral_conflict_is_not_erased_by_personality(self):
        factors = DecisionFactors(goal_progress=100, moral_conflict=100)
        score = score_action(PersonalityTraits(risk_tolerance=100, rule_alignment=0), factors)
        self.assertEqual(-150.0, score.contributions["moral_conflict"])


class TaskBoardTests(unittest.TestCase):
    def _task(self, task_id="task:001"):
        return CampusTask(
            task_id=task_id,
            forum=ForumKind.SURFACE,
            issuer_id="npc:issuer",
            title="寻找借阅记录",
            action_id="INVESTIGATE_RECORD",
            scene_id="library",
            created_day=1,
            expires_day=3,
        )

    def test_first_valid_claim_wins_atomically(self):
        board = TaskBoard([self._task()])
        revision = board.get("task:001").lock_revision
        claimed = board.claim("task:001", "player", expected_revision=revision)
        self.assertEqual(TaskState.LOCKED, claimed.state)
        self.assertEqual("player", claimed.assignee_id)
        with self.assertRaises(TaskConflictError):
            board.claim("task:001", "npc:rival", expected_revision=revision)

    def test_views_and_consideration_do_not_steal_or_invalidate_lock(self):
        board = TaskBoard([self._task()])
        revision = board.get("task:001").lock_revision
        board.view("task:001", "npc:first")
        board.consider("task:001", "npc:second")
        claimed = board.claim("task:001", "player", expected_revision=revision)
        self.assertEqual("player", claimed.assignee_id)
        self.assertEqual(["npc:first"], claimed.viewer_ids)
        self.assertEqual(["npc:second"], claimed.considering_ids)

    def test_abandon_can_release_lock_for_another_actor(self):
        board = TaskBoard([self._task()])
        first = board.claim("task:001", "npc:first", expected_revision=0)
        reopened = board.abandon("task:001", "npc:first", reopen=True)
        self.assertEqual(TaskState.OPEN, reopened.state)
        second = board.claim("task:001", "npc:second", expected_revision=reopened.lock_revision)
        self.assertEqual("npc:second", second.assignee_id)
        self.assertGreater(second.lock_revision, first.lock_revision)

    def test_public_copies_cannot_mutate_board(self):
        board = TaskBoard([self._task()])
        copy = board.get("task:001")
        copy.viewer_ids.append("intruder")
        self.assertNotIn("intruder", board.get("task:001").viewer_ids)

    def test_expiration_preserves_result_as_terminal_state(self):
        board = TaskBoard([self._task()])
        expired = board.expire(current_day=4)
        self.assertEqual([TaskState.EXPIRED], [task.state for task in expired])
        with self.assertRaises(TaskConflictError):
            board.claim("task:001", "player", expected_revision=1)


class FocusAndCalendarTests(unittest.TestCase):
    def test_awakened_slots_are_permanent_and_dynamic_slots_are_ranked(self):
        allocator = FocusSlotAllocator(total_slots=4, permanent_player_slots=2)
        allocator.awaken("npc:chosen")
        selected = allocator.allocate([
            FocusCandidate("npc:low", world_relevance_score=2),
            FocusCandidate("npc:night", night_action_score=50),
            FocusCandidate("npc:task", active_task_score=80),
            FocusCandidate("npc:chosen"),
        ])
        self.assertEqual("npc:chosen", selected[0])
        self.assertEqual(["npc:task", "npc:night", "npc:low"], selected[1:])

    def test_focus_slot_limit_is_enforced(self):
        allocator = FocusSlotAllocator(total_slots=2, permanent_player_slots=1)
        allocator.awaken("npc:first")
        with self.assertRaises(ValueError):
            allocator.awaken("npc:second")

    def test_demo_calendar_has_four_contiguous_seven_day_stages(self):
        self.assertEqual(4, len(DEMO_STAGES))
        self.assertEqual([(1, 7), (8, 14), (15, 21), (22, 28)], [
            (stage.start_day, stage.end_day) for stage in DEMO_STAGES
        ])
        self.assertEqual("misnaming", stage_for_day(1).stage_id)
        self.assertEqual("who_remembers", stage_for_day(28).stage_id)
        self.assertEqual("midpoint", day_role(18))
        self.assertEqual("deadline", day_role(28))


class CampusContentTests(unittest.TestCase):
    def _read(self, relative_path: str):
        return json.loads((REPOSITORY_DIR / relative_path).read_text(encoding="utf-8"))

    def test_eight_colleges_have_four_common_skills_and_three_specializations(self):
        colleges = self._read("content/actions/college_skills.json")["colleges"]
        self.assertEqual(8, len(colleges))
        self.assertEqual(8, len({college["id"] for college in colleges}))
        for college in colleges:
            self.assertEqual(4, len(college["common_skills"]), college["id"])
            self.assertEqual(3, len(college["specializations"]), college["id"])

    def test_twelve_core_clubs_have_unique_skills(self):
        clubs = self._read("content/organizations/clubs.json")["clubs"]
        self.assertEqual(12, len(clubs))
        self.assertEqual(12, len({club["id"] for club in clubs}))
        self.assertTrue(all(club["surface_skill"] and club["night_skill"] for club in clubs))

    def test_population_and_story_content_match_demo_scope(self):
        rules = self._read("content/npcs/generation_rules.json")
        calendar = self._read("content/main_story/demo_calendar.json")
        self.assertEqual(6000, rules["student_population"] + rules["staff_population"])
        self.assertEqual(200, rules["persistent_population"])
        self.assertEqual(20, rules["focused_slots"])
        self.assertEqual(6, rules["player_awakened_slots"])
        self.assertEqual(28, calendar["total_days"])
        self.assertEqual(4, len(calendar["stages"]))

    def test_enemy_archetypes_are_unique(self):
        enemies = self._read("content/situations/enemy_archetypes.json")["archetypes"]
        self.assertEqual(8, len(enemies))
        self.assertEqual(8, len({enemy["id"] for enemy in enemies}))

    def test_action_economy_is_coarse_and_only_major_actions_are_limited(self):
        economy = self._read("content/actions/action_economy.json")
        phases = economy["phases"]
        self.assertEqual(
            ["morning", "afternoon", "evening", "late_night"],
            [phase["id"] for phase in phases],
        )
        self.assertTrue(all(phase["major_actions"] == 1 for phase in phases))
        self.assertTrue(phases[-1]["optional"])
        self.assertTrue(all(
            economy["action_classes"][action] == "free"
            for action in ("travel", "chat", "shopping", "meal")
        ))


if __name__ == "__main__":
    unittest.main()
