from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from simulation.api.server import SimulationBridge
from simulation.systems import (
    ContentRegistry,
    load_campus_activity_definitions,
    load_campus_location_graph,
)


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class CampusActivityEffectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = tempfile.TemporaryDirectory()
        self.addCleanup(self.output.cleanup)
        self.bridge = SimulationBridge(Path(self.output.name))
        registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        self.graph = load_campus_location_graph(registry)

    def command(self, command_id: str, activity_id: str, location_id: str) -> dict:
        snapshot = self.bridge.campus_snapshot()
        clock = snapshot["clock"]
        return {
            "command_id": command_id,
            "actor_id": "player",
            "action_id": activity_id,
            "target_ids": [],
            "parameters": {"location_id": location_id},
            "expected_world_revision": snapshot["revision"],
            "issued_day": clock["day"],
            "issued_phase": clock["phase"],
            "issued_minute": clock["minute"],
            "source": "player",
        }

    def advance(self, command_id: str) -> dict:
        snapshot = self.bridge.campus_snapshot()
        clock = snapshot["clock"]
        return self.bridge.campus_command({
            "command_id": command_id,
            "actor_id": "player",
            "action_id": "ADVANCE_PHASE",
            "target_ids": [],
            "parameters": {},
            "expected_world_revision": snapshot["revision"],
            "issued_day": clock["day"],
            "issued_phase": clock["phase"],
            "issued_minute": clock["minute"],
            "source": "player",
        })

    def move_player_to(self, destination_id: str) -> None:
        current = self.bridge.campus_snapshot()["player"]["current_location_id"]
        route = self.graph.shortest_route(
            current,
            destination_id,
            phase=self.bridge.campus_snapshot()["clock"]["phase"],
            access_tags=self.bridge.campus_snapshot()["player"]["access_tags"],
        )
        self.assertIsNotNone(route)
        for index, step in enumerate(route.steps):
            snapshot = self.bridge.campus_snapshot()
            clock = snapshot["clock"]
            moved = self.bridge.campus_command({
                "command_id": f"player-route-{index}",
                "actor_id": "player",
                "action_id": "TRAVERSE_LOCATION_PASSAGE",
                "target_ids": [],
                "parameters": {"passage_id": step.passage_id},
                "expected_world_revision": snapshot["revision"],
                "issued_day": clock["day"],
                "issued_phase": clock["phase"],
                "issued_minute": clock["minute"],
                "source": "player",
            })
            self.assertTrue(moved["ok"], step.passage_id)

    def test_all_schedule_activities_have_valid_data_driven_effects(self):
        registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        definitions = load_campus_activity_definitions(registry)
        self.assertEqual(33, len(definitions))
        self.assertEqual("free", definitions["REST"].action_class)
        self.assertEqual("study", definitions["ATTEND_CLASS"].category)
        self.assertEqual("work", definitions["MEDICAL_SHIFT"].category)

    def test_player_activity_requires_location_and_spends_budget_atomically(self):
        plan = self.bridge.campus_snapshot()["player"]["current_plan"]
        location_id = plan["location_id"]
        wrong = self.bridge.campus_command(
            self.command("wrong-location", plan["activity_id"], location_id)
        )
        self.assertFalse(wrong["ok"])
        self.assertEqual("activity_wrong_location", wrong["result"]["code"])
        self.assertEqual(1, wrong["snapshot"]["revision"])

        self.move_player_to(location_id)
        before_needs = deepcopy(
            self.bridge.campus.kernel.state.population["player"]["needs"]
        )
        player_command = self.command("player-class", plan["activity_id"], location_id)
        completed = self.bridge.campus_command(player_command)
        self.assertTrue(completed["ok"])
        self.assertEqual(0, completed["snapshot"]["player"]["action_budget"]["major_remaining"])
        player = self.bridge.campus.kernel.state.population["player"]
        self.assertNotEqual(before_needs, player["needs"])
        self.assertEqual(1, player["activity_progress"]["total"])
        self.assertGreater(
            self.bridge.campus.kernel.state.knowledge["actors"]["player"]["total_progress"],
            0,
        )

        replay = self.bridge.campus_command(player_command)
        self.assertTrue(replay["result"]["replayed"])
        self.assertEqual(1, player["activity_progress"]["total"])

        blocked = self.bridge.campus_command(
            self.command("second-class", plan["activity_id"], location_id)
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual("major_action_exhausted", blocked["result"]["code"])
        self.assertEqual(completed["snapshot"]["revision"], blocked["snapshot"]["revision"])
        self.assertEqual(1, player["activity_progress"]["total"])

    def test_phase_execution_applies_effects_to_every_scheduled_npc(self):
        before = deepcopy(
            self.bridge.campus.kernel.state.population["campus_student_001"]["needs"]
        )
        result = self.advance("effects-afternoon")
        self.assertTrue(result["ok"])
        effect_events = [
            event for event in result["result"]["events"]
            if event["event_type"] == "CAMPUS_ACTIVITY_EFFECT_APPLIED"
        ]
        self.assertEqual(200, len(effect_events))
        self.assertEqual(
            201,
            result["result"]["payload"]["phase_execution"]["need_tick_count"],
        )
        state = self.bridge.campus.kernel.state
        self.assertEqual(200, len(state.knowledge["actors"]))
        actor = state.population["campus_student_001"]
        self.assertNotEqual(before, actor["needs"])
        self.assertEqual(1, actor["activity_progress"]["total"])
        self.assertTrue(actor["current_activity"]["effects"])
        self.assertEqual(0, state.action_economy["actors"]["campus_student_001"]["major_remaining"])

    def test_rest_is_free_and_clamps_dynamic_meters(self):
        for index in range(2):
            self.advance(f"to-rest-{index}")
        state = self.bridge.campus.kernel.state
        rest_candidates = [
            (actor["needs"]["rest"], actor_id)
            for actor_id, actor in state.population.items()
            if actor_id != "player"
            and actor.get("occupation_id") not in {"medical_staff", "campus_security"}
        ]
        rest_before, actor_id = min(rest_candidates)
        result = self.advance("to-late-night-rest")
        self.assertTrue(result["ok"])
        actor = self.bridge.campus.kernel.state.population[actor_id]
        self.assertEqual(max(0, rest_before - 28), actor["needs"]["rest"])
        self.assertEqual("REST", actor["current_activity"]["activity_id"])
        self.assertEqual(
            1,
            self.bridge.campus.kernel.state.action_economy["actors"]["campus_student_001"]["major_remaining"],
        )


if __name__ == "__main__":
    unittest.main()
