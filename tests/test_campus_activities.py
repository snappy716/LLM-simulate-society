from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simulation.api.server import SimulationBridge


class CampusActivityExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = tempfile.TemporaryDirectory()
        self.addCleanup(self.output.cleanup)
        self.bridge = SimulationBridge(Path(self.output.name))

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

    def test_phase_start_moves_every_npc_to_plan_and_executes_major_activity(self):
        initial = self.bridge.campus_snapshot()
        initial_player_location = initial["player"]["current_location_id"]
        result = self.advance("execute-afternoon")
        self.assertTrue(result["ok"])
        execution = result["result"]["payload"]["phase_execution"]
        self.assertEqual(200, execution["planned_actor_count"])
        self.assertEqual(200, execution["major_activity_count"])
        self.assertEqual(0, execution["free_activity_count"])
        self.assertEqual(0, execution["blocked_actor_count"])
        self.assertGreater(execution["moved_actor_count"], 0)
        self.assertGreater(execution["route_step_count"], execution["moved_actor_count"])

        state = self.bridge.campus.kernel.state
        self.assertEqual(initial_player_location, state.population["player"]["current_location_id"])
        self.assertNotIn("current_activity", state.population["player"])
        self.assertEqual(1, state.action_economy["actors"]["player"]["major_remaining"])
        for actor_id, actor in state.population.items():
            if actor_id == "player":
                continue
            activity = actor["current_activity"]
            self.assertEqual("completed", activity["status"], actor_id)
            self.assertEqual(actor["current_location_id"], activity["location_id"], actor_id)
            self.assertEqual(0, state.action_economy["actors"][actor_id]["major_remaining"])

        event_types = [event["event_type"] for event in result["result"]["events"]]
        self.assertEqual(execution["route_step_count"], event_types.count("ACTOR_LOCATION_CHANGED"))
        self.assertEqual(200, event_types.count("NPC_ACTIVITY_COMPLETED"))
        self.assertEqual(1, event_types.count("WORLD_PHASE_ADVANCED"))

    def test_late_night_rest_is_free_but_still_changes_real_locations(self):
        self.advance("to-afternoon")
        self.advance("to-evening")
        result = self.advance("to-late-night")
        execution = result["result"]["payload"]["phase_execution"]
        self.assertGreater(execution["free_activity_count"], execution["major_activity_count"])
        self.assertEqual(200, execution["free_activity_count"] + execution["major_activity_count"])
        self.assertEqual(0, execution["blocked_actor_count"])

        state = self.bridge.campus.kernel.state
        self.assertEqual("late_night", state.clock.phase)
        for actor_id, actor in state.population.items():
            if actor_id == "player":
                continue
            activity = actor["current_activity"]
            if activity["action_class"] == "free":
                self.assertEqual(actor["home_location_id"], actor["current_location_id"], actor_id)
                self.assertEqual("REST", activity["activity_id"], actor_id)
                self.assertEqual(1, state.action_economy["actors"][actor_id]["major_remaining"])
            else:
                self.assertEqual(0, state.action_economy["actors"][actor_id]["major_remaining"])

    def test_route_events_form_a_contiguous_path_for_each_moving_npc(self):
        result = self.advance("route-continuity")
        routes: dict[str, list[dict]] = {}
        for event in result["result"]["events"]:
            if event["event_type"] != "ACTOR_LOCATION_CHANGED":
                continue
            actor_id = event["actor_ids"][0]
            routes.setdefault(actor_id, []).append(event["payload"])
        self.assertTrue(routes)
        for actor_id, steps in routes.items():
            for previous, current in zip(steps, steps[1:]):
                self.assertEqual(previous["to_id"], current["from_id"], actor_id)
            self.assertEqual(
                self.bridge.campus.kernel.state.population[actor_id]["current_location_id"],
                steps[-1]["to_id"],
                actor_id,
            )


if __name__ == "__main__":
    unittest.main()
