from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simulation.api.server import SimulationBridge


class CampusKernelBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = tempfile.TemporaryDirectory()
        self.addCleanup(self.output.cleanup)
        self.bridge = SimulationBridge(Path(self.output.name))

    def command(self, command_id: str, passage_id: str, revision: int = 1) -> dict:
        snapshot = self.bridge.campus_snapshot()
        clock = snapshot["clock"]
        return {
            "command_id": command_id,
            "actor_id": "player",
            "action_id": "TRAVERSE_LOCATION_PASSAGE",
            "target_ids": [],
            "parameters": {"passage_id": passage_id},
            "expected_world_revision": revision,
            "issued_day": clock["day"],
            "issued_phase": clock["phase"],
            "issued_minute": clock["minute"],
            "source": "player",
        }

    def advance_command(self, command_id: str, revision: int) -> dict:
        snapshot = self.bridge.campus_snapshot()
        clock = snapshot["clock"]
        return {
            "command_id": command_id,
            "actor_id": "player",
            "action_id": "ADVANCE_PHASE",
            "target_ids": [],
            "parameters": {},
            "expected_world_revision": revision,
            "issued_day": clock["day"],
            "issued_phase": clock["phase"],
            "issued_minute": clock["minute"],
            "source": "player",
        }

    def fast_travel_command(self, command_id: str, destination_id: str, revision: int = 1) -> dict:
        snapshot = self.bridge.campus_snapshot()
        clock = snapshot["clock"]
        return {
            "command_id": command_id,
            "actor_id": "player",
            "action_id": "FAST_TRAVEL_CAMPUS",
            "target_ids": [],
            "parameters": {"destination_id": destination_id},
            "expected_world_revision": revision,
            "issued_day": clock["day"],
            "issued_phase": clock["phase"],
            "issued_minute": clock["minute"],
            "source": "player",
        }

    def test_side_by_side_snapshot_has_campus_places_and_persistent_cast(self):
        campus = self.bridge.campus_snapshot()
        legacy = self.bridge.snapshot()
        self.assertEqual(13, campus["view_version"])
        self.assertEqual(200, len(campus["population"]))
        self.assertEqual(6000, campus["population_summary"]["campus_total"])
        self.assertEqual("south_gate_region", campus["player"]["current_location_id"])
        self.assertEqual(1, campus["player"]["action_budget"]["major_remaining"])
        self.assertEqual(1, campus["action_economy"]["player"]["major_remaining"])
        self.assertEqual("ORIENTATION_OR_CLASS", campus["player"]["current_plan"]["activity_id"])
        self.assertEqual(201, sum(campus["schedule"]["current_planned_occupancy"].values()))
        self.assertEqual(2, legacy["schema_version"])

    def test_strict_kernel_command_crosses_continuous_region_boundary(self):
        command = self.command("godot-road-1", "road_gate_to_student_life")
        result = self.bridge.campus_command(command)
        self.assertTrue(result["ok"])
        self.assertEqual(2, result["result"]["world_revision"])
        self.assertFalse(result["result"]["payload"]["requires_scene_change"])
        self.assertEqual(
            "student_life_region", result["snapshot"]["player"]["current_location_id"]
        )
        replay = self.bridge.campus_command(command)
        self.assertTrue(replay["result"]["replayed"])
        self.assertEqual(2, replay["snapshot"]["revision"])

    def test_free_movement_preserves_budget_and_phase_can_advance(self):
        moved = self.bridge.campus_command(
            self.command("free-road", "road_gate_to_student_life")
        )
        self.assertEqual(0, moved["snapshot"]["clock"]["minute"])
        self.assertEqual(1, moved["snapshot"]["player"]["action_budget"]["major_remaining"])
        advanced = self.bridge.campus_command(self.advance_command("next-phase", 2))
        self.assertTrue(advanced["ok"])
        self.assertEqual("afternoon", advanced["snapshot"]["clock"]["phase"])
        self.assertEqual(1, advanced["snapshot"]["player"]["action_budget"]["major_remaining"])
        self.assertEqual(
            "CAMPUS_EXPLORATION", advanced["snapshot"]["player"]["current_plan"]["activity_id"]
        )
        execution = advanced["result"]["payload"]["phase_execution"]
        self.assertEqual(200, execution["planned_actor_count"])
        self.assertGreater(execution["moved_actor_count"], 0)
        self.assertEqual(200, execution["major_activity_count"])
        self.assertEqual(0, execution["blocked_actor_count"])

    def test_campus_map_fast_travel_preserves_time_and_action_budget(self):
        result = self.bridge.campus_command(
            self.fast_travel_command("map-travel", "east_dorm_region")
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["result"]["payload"]["free_movement"])
        self.assertEqual("east_dorm_region", result["snapshot"]["player"]["current_location_id"])
        self.assertEqual(0, result["snapshot"]["clock"]["minute"])
        self.assertEqual(1, result["snapshot"]["player"]["action_budget"]["major_remaining"])

    def test_remote_entrance_is_rejected_without_revision_change(self):
        result = self.bridge.campus_command(
            self.command("godot-remote-1", "parent:humanities_psychology_building")
        )
        self.assertFalse(result["ok"])
        self.assertEqual("passage_absent", result["result"]["code"])
        self.assertEqual(1, result["snapshot"]["revision"])


if __name__ == "__main__":
    unittest.main()
