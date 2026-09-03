from __future__ import annotations

import unittest
from pathlib import Path

from simulation.domain import WorldState
from simulation.systems import (
    CampusPopulationGenerator,
    ContentRegistry,
    DeterministicRngPool,
    campus_schedule_invariant,
    current_schedule_slot,
    install_campus_places,
    install_campus_population,
    install_campus_schedules,
    load_campus_location_graph,
    load_campus_schedule_templates,
)


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class CampusScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        cls.graph = load_campus_location_graph(cls.registry)
        cls.templates = load_campus_schedule_templates(cls.registry, cls.graph)

    def make_state(self, seed: int = 42) -> WorldState:
        state = WorldState(content_version=self.registry.content_version, master_seed=seed)
        install_campus_places(state, self.graph)
        records = CampusPopulationGenerator(
            self.registry, self.graph, DeterministicRngPool(seed)
        ).generate()
        install_campus_population(state, records)
        install_campus_schedules(state, self.graph, self.templates)
        return state

    def test_all_configured_templates_exist_and_cover_every_phase(self):
        self.assertEqual(12, len(self.templates))
        configured = self.registry.get("configuration", "campus_population")["schedules"]
        self.assertTrue(set(configured.values()).issubset(self.templates))
        for template in self.templates.values():
            self.assertEqual(4, len(template.weekday))
            self.assertEqual(4, len(template.weekend))

    def test_every_actor_gets_repeating_seven_day_schedule(self):
        state = self.make_state()
        self.assertEqual(201, state.metadata["campus_schedule"]["actor_count"])
        self.assertEqual(5628, state.metadata["campus_schedule"]["slot_count"])
        self.assertEqual(0, state.metadata["campus_schedule"]["capacity_redirect_count"])
        self.assertEqual([], list(campus_schedule_invariant(state)))
        for actor in state.population.values():
            self.assertEqual({str(day) for day in range(7)}, set(actor["weekly_schedule"]))
            self.assertTrue(all(
                set(day) == {"morning", "afternoon", "evening", "late_night"}
                for day in actor["weekly_schedule"].values()
            ))

    def test_player_plan_changes_by_phase_without_moving_or_spending_actions(self):
        state = self.make_state()
        self.assertEqual("south_gate_region", state.population["player"]["current_location_id"])
        morning = current_schedule_slot(state, "player")
        self.assertEqual("ORIENTATION_OR_CLASS", morning["activity_id"])
        self.assertEqual("humanities_classroom_pool", morning["location_id"])
        state.clock.phase = "afternoon"
        afternoon = current_schedule_slot(state, "player")
        self.assertEqual("CAMPUS_EXPLORATION", afternoon["activity_id"])
        self.assertEqual("mirror_lake_square", afternoon["location_id"])
        self.assertEqual({}, state.action_economy)

    def test_generated_schedule_is_deterministic_for_same_seed(self):
        first = self.make_state(91)
        second = self.make_state(91)
        self.assertEqual(
            first.metadata["campus_schedule"], second.metadata["campus_schedule"]
        )
        self.assertEqual(
            first.population["campus_student_001"]["weekly_schedule"],
            second.population["campus_student_001"]["weekly_schedule"],
        )

    def test_planned_direct_occupancy_never_exceeds_location_capacity(self):
        state = self.make_state()
        occupancy = state.metadata["campus_schedule"]["planned_occupancy"]
        for day in occupancy.values():
            for phase in day.values():
                for location_id, count in phase.items():
                    location = self.graph.locations.get(location_id)
                    if location is not None:
                        self.assertLessEqual(count, location.capacity, location_id)

    def test_capacity_overflow_uses_legal_fallback_instead_of_overbooking(self):
        state = WorldState(content_version=self.registry.content_version, master_seed=7)
        install_campus_places(state, self.graph)
        state.population = {
            f"npc:{index}": {
                "npc_id": f"npc:{index}",
                "schedule_id": "counselor_day_shift",
                "home_location_id": "east_dorm_room_pool",
                "primary_location_id": "psychology_support_room",
                "college_id": "psychology",
                "club_ids": [],
                "access_tags": [
                    "campus_member", "east_dorm_access", "psychology_lab_access"
                ],
            }
            for index in range(10)
        }
        install_campus_schedules(state, self.graph, self.templates)
        morning = state.metadata["campus_schedule"]["planned_occupancy"]["0"]["morning"]
        self.assertEqual(8, morning["psychology_support_room"])
        self.assertEqual(2, sum(
            actor["weekly_schedule"]["0"]["morning"]["capacity_redirected"]
            for actor in state.population.values()
        ))
        self.assertEqual([], list(campus_schedule_invariant(state)))


if __name__ == "__main__":
    unittest.main()
