from __future__ import annotations

import unittest
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.systems import ContentRegistry, load_campus_location_graph


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


def execute(bridge: CampusKernelBridge, action_id: str, parameters=None, command_id=None):
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": command_id or f"test-{action_id}-{snapshot['revision']}",
        "actor_id": "player",
        "action_id": action_id,
        "target_ids": [],
        "parameters": parameters or {},
        "expected_world_revision": snapshot["revision"],
        "issued_day": clock["day"],
        "issued_phase": clock["phase"],
        "issued_minute": clock["minute"],
        "source": "player",
    })


class CampusForumTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        cls.graph = load_campus_location_graph(registry)

    def test_initial_surface_board_is_public_but_private_scheduling_does_not_leak(self):
        bridge = CampusKernelBridge(42)
        snapshot = bridge.snapshot()
        self.assertEqual(21, snapshot["view_version"])
        self.assertEqual(12, snapshot["task_summary"]["total"])
        self.assertEqual(12, snapshot["task_summary"]["available"])
        self.assertTrue(snapshot["forums"]["surface"]["enabled"])
        self.assertFalse(snapshot["forums"]["night"]["enabled"])
        for task in snapshot["tasks"].values():
            self.assertIn("description", task)
            self.assertIn("objective", task)
            self.assertEqual(0, task["viewer_count"])
            self.assertNotIn("viewer_ids", task)
            self.assertNotIn("npc_claim_phase_index", task)

    def test_player_view_claim_conflict_and_complete_at_location(self):
        bridge = CampusKernelBridge(8)
        initial = bridge.snapshot()
        task = next(
            value for value in initial["tasks"].values()
            if value["activity_id"] not in {
                "CLUB_OR_PERSONAL_ACTIVITY", "CLUB_OR_SELF_STUDY"
            }
        )
        task_id = task["task_id"]
        viewed = execute(bridge, "VIEW_FORUM_TASK", {"task_id": task_id})
        self.assertTrue(viewed["ok"])
        viewed_task = bridge.snapshot()["tasks"][task_id]
        self.assertTrue(viewed_task["viewed_by_player"])

        claimed = execute(
            bridge,
            "CLAIM_FORUM_TASK",
            {"task_id": task_id, "expected_task_revision": viewed_task["lock_revision"]},
        )
        self.assertTrue(claimed["ok"])
        self.assertTrue(bridge.snapshot()["tasks"][task_id]["owned_by_player"])

        other_task = next(
            value for value in bridge.snapshot()["tasks"].values()
            if value["task_id"] != task_id
        )
        blocked = execute(
            bridge,
            "CLAIM_FORUM_TASK",
            {
                "task_id": other_task["task_id"],
                "expected_task_revision": other_task["lock_revision"],
            },
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual("actor_has_active_task", blocked["result"]["code"])

        wrong_place = execute(bridge, "COMPLETE_FORUM_TASK", {"task_id": task_id})
        if wrong_place["ok"]:
            self.assertEqual(task["scene_id"], initial["player"]["current_location_id"])
        else:
            self.assertEqual("task_wrong_location", wrong_place["result"]["code"])
            for index, step in enumerate(
                self.graph.shortest_route(
                    bridge.snapshot()["player"]["current_location_id"],
                    task["scene_id"],
                    phase="morning",
                    access_tags=bridge.kernel.state.population["player"]["access_tags"],
                ).steps
            ):
                moved = execute(
                    bridge,
                    "TRAVERSE_LOCATION_PASSAGE",
                    {"passage_id": step.passage_id},
                    command_id=f"move-to-task-{index}",
                )
                self.assertTrue(moved["ok"])
            wealth_before = bridge.snapshot()["player"]["wealth"]
            completed = execute(bridge, "COMPLETE_FORUM_TASK", {"task_id": task_id})
            self.assertTrue(completed["ok"], completed)
            final = bridge.snapshot()
            self.assertEqual("completed", final["tasks"][task_id]["state"])
            activity_wealth_delta = int(
                final["player"]["last_activity_effects"]["wealth"]["delta"]
            )
            self.assertEqual(
                wealth_before
                + activity_wealth_delta
                + int(task["reward"].get("wealth", 0)),
                final["player"]["wealth"],
            )

    def test_player_can_complete_in_current_art_region_before_room_scene_exists(self):
        bridge = CampusKernelBridge(42)
        task = next(
            value for value in bridge.snapshot()["tasks"].values()
            if value["scene_id"] == "canteen_dining_hall"
        )
        execute(bridge, "VIEW_FORUM_TASK", {"task_id": task["task_id"]})
        current = bridge.snapshot()["tasks"][task["task_id"]]
        claimed = execute(
            bridge,
            "CLAIM_FORUM_TASK",
            {
                "task_id": task["task_id"],
                "expected_task_revision": current["lock_revision"],
            },
        )
        self.assertTrue(claimed["ok"])
        travelled = execute(
            bridge,
            "FAST_TRAVEL_CAMPUS",
            {"destination_id": "student_life_region"},
        )
        self.assertTrue(travelled["ok"])
        self.assertEqual(
            "student_life_region",
            bridge.snapshot()["tasks"][task["task_id"]]["execution_region_id"],
        )
        completed = execute(
            bridge,
            "COMPLETE_FORUM_TASK",
            {"task_id": task["task_id"]},
        )
        self.assertTrue(completed["ok"], completed)
        self.assertEqual(
            "completed", bridge.snapshot()["tasks"][task["task_id"]]["state"]
        )

    def test_npc_views_claims_and_completions_are_gradual_and_deterministic(self):
        def trace(seed: int):
            bridge = CampusKernelBridge(seed)
            rows = []
            for _ in range(8):
                result = execute(bridge, "ADVANCE_PHASE")
                self.assertTrue(result["ok"])
                execution = result["result"]["payload"]["phase_execution"]
                snapshot = bridge.snapshot()
                rows.append((
                    execution["forum_new_view_count"],
                    execution["forum_npc_claim_count"],
                    execution["task_completed_count"],
                    snapshot["task_summary"]["available"],
                    tuple(sorted(snapshot["task_summary"]["by_state"].items())),
                ))
            return rows

        first = trace(42)
        second = trace(42)
        self.assertEqual(first, second)
        self.assertGreater(sum(row[0] for row in first), 0)
        self.assertGreater(sum(row[1] for row in first), 0)
        self.assertGreater(sum(row[2] for row in first), 0)
        self.assertGreater(first[0][3], 0, "all tasks were taken immediately")


if __name__ == "__main__":
    unittest.main()
