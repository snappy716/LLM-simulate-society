from __future__ import annotations

import unittest

from simulation.actions import CommandResult
from simulation.api import (
    CommandParseError,
    command_result_view,
    campus_world_view,
    kernel_status_view,
    parse_simulation_command,
)
from simulation.domain import ClockState, WorldState


def valid_payload() -> dict:
    return {
        "command_id": "cmd-1",
        "actor_id": "player",
        "action_id": "MOVE",
        "target_ids": ["library"],
        "parameters": {"route_id": "north"},
        "expected_world_revision": 1,
        "issued_day": 1,
        "issued_phase": "morning",
        "issued_minute": 15,
        "source": "player",
    }


class KernelApiContractTests(unittest.TestCase):
    def test_command_parser_accepts_complete_strict_payload(self):
        request = parse_simulation_command(valid_payload())
        self.assertEqual("MOVE", request.action_id)
        self.assertEqual(("library",), request.target_ids)
        self.assertEqual("north", request.parameters["route_id"])

    def test_command_parser_rejects_unknown_and_missing_fields(self):
        unknown = valid_payload()
        unknown["direct_wealth_change"] = 999
        with self.assertRaises(CommandParseError) as error:
            parse_simulation_command(unknown)
        self.assertEqual("unknown_fields", error.exception.code)

        missing = valid_payload()
        del missing["expected_world_revision"]
        with self.assertRaises(CommandParseError) as error:
            parse_simulation_command(missing)
        self.assertEqual("missing_fields", error.exception.code)

    def test_command_parser_enforces_phase_and_unique_targets(self):
        invalid = valid_payload()
        invalid["issued_phase"] = "lunch"
        with self.assertRaises(CommandParseError):
            parse_simulation_command(invalid)
        invalid = valid_payload()
        invalid["target_ids"] = ["library", "library"]
        with self.assertRaises(CommandParseError):
            parse_simulation_command(invalid)

    def test_result_and_status_views_are_stable_read_only_shapes(self):
        result = command_result_view(CommandResult(
            command_id="cmd-1",
            accepted=True,
            performed=True,
            success=True,
            code="success",
            message="done",
            world_revision=2,
        ))
        self.assertEqual(1, result["contract_version"])
        self.assertEqual([], result["events"])

        state = WorldState(
            revision=7,
            clock=ClockState(day=3, phase="evening", minute=42),
            content_version="abc123",
        )
        view = kernel_status_view(state, busy=True)
        self.assertEqual(7, view["revision"])
        self.assertEqual({"day": 3, "phase": "evening", "minute": 42}, view["clock"])
        self.assertTrue(view["busy"])

    def test_campus_view_exposes_navigation_without_internal_command_history(self):
        state = WorldState(
            revision=3,
            content_version="content",
            population={
                "player": {"npc_id": "player", "current_location_id": "region_a"},
                "npc_1": {
                    "npc_id": "npc_1", "display_name": "测试人物", "role_kind": "student",
                    "college_id": "psychology", "occupation_id": "student",
                    "current_location_id": "region_a", "home_location_id": "dorm",
                    "home_room_key": "E01-101", "simulation_tier": "persistent",
                    "night_access": "unaware", "appearance_seed": 7,
                },
            },
            places={"region_a": {"node_type": "region"}},
            processed_commands={"secret": {"fingerprint": "x", "result": {}}},
            metadata={
                "campus_passages": {"road": {"from_id": "region_a", "to_id": "region_b"}},
                "interior_templates": {"lobby": {"presentation_key": "interior_lobby"}},
                "campus_population": {"campus_total": 6000},
            },
        )
        view = campus_world_view(state)
        self.assertEqual(12, view["view_version"])
        self.assertEqual("region_a", view["player"]["current_location_id"])
        self.assertIn("road", view["passages"])
        self.assertIn("lobby", view["interior_templates"])
        self.assertNotIn("processed_commands", view)
        self.assertNotIn("chronicles", view)


if __name__ == "__main__":
    unittest.main()
