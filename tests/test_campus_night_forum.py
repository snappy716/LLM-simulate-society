from __future__ import annotations

import unittest

from simulation.api.server import CampusKernelBridge
from simulation.systems import campus_night_task_invariant, campus_night_world_invariant


def execute(bridge: CampusKernelBridge, action_id: str, parameters=None, marker="command") -> dict:
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"night-forum-{marker}-{snapshot['revision']}",
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


def advance_to_evening(bridge: CampusKernelBridge) -> dict:
    execute(bridge, "ADVANCE_PHASE", marker="afternoon")
    return execute(bridge, "ADVANCE_PHASE", marker="evening")


class CampusNightForumTests(unittest.TestCase):
    def test_evening_publishes_twenty_hidden_tasks_and_sends_six_to_twelve_npcs(self):
        bridge = CampusKernelBridge(42)
        evening = advance_to_evening(bridge)
        execution = evening["result"]["payload"]["phase_execution"]
        self.assertEqual(20, execution["night_task_published_count"])
        self.assertTrue(6 <= execution["night_npc_enter_count"] <= 12)
        self.assertEqual(execution["night_npc_enter_count"], execution["night_npc_claim_count"])
        self.assertGreater(execution["night_task_view_count"], execution["night_npc_enter_count"])
        public = bridge.snapshot()
        self.assertFalse(public["forums"]["night"]["enabled"])
        self.assertEqual(0, public["task_summary"]["by_forum"]["night"]["total"])
        state = bridge.kernel._state
        night_tasks = [task for task in state.tasks.values() if task.get("forum") == "night"]
        self.assertEqual(20, len(night_tasks))
        active_ids = state.situations["night_world"]["active_actor_ids"]
        self.assertTrue(6 <= len(active_ids) <= 12)
        self.assertTrue(all(
            state.situations["night_world"]["actor_states"][actor_id]["layer"] == "night"
            for actor_id in active_ids
        ))
        self.assertEqual(len(active_ids), sum(task.get("state") == "locked" for task in night_tasks))
        late = execute(bridge, "ADVANCE_PHASE", marker="late")
        self.assertGreaterEqual(
            late["result"]["payload"]["phase_execution"]["task_completed_count"],
            len(active_ids),
        )
        self.assertEqual(
            len(active_ids),
            sum(task.get("state") == "completed" for task in bridge.kernel._state.tasks.values() if task.get("forum") == "night"),
        )

    def test_first_player_entry_unlocks_readable_forum_and_allows_one_real_task(self):
        bridge = CampusKernelBridge(42)
        advance_to_evening(bridge)
        hidden_task = next(
            task for task in bridge.kernel._state.tasks.values()
            if task.get("forum") == "night" and task.get("state") in {"open", "viewed", "considering"}
        )
        blocked = execute(
            bridge,
            "CLAIM_FORUM_TASK",
            {
                "task_id": hidden_task["task_id"],
                "expected_task_revision": hidden_task["lock_revision"],
            },
            marker="blocked",
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual("night_layer_required", blocked["result"]["code"])
        entered = execute(bridge, "ENTER_NIGHT_WORLD", marker="enter")
        self.assertTrue(entered["ok"])
        snapshot = bridge.snapshot()
        self.assertTrue(snapshot["night_world"]["night_forum_unlocked"])
        self.assertTrue(snapshot["night_world"]["night_forum_accessible"])
        self.assertTrue(snapshot["forums"]["night"]["enabled"])
        self.assertEqual(20, snapshot["task_summary"]["by_forum"]["night"]["total"])
        task = snapshot["tasks"][hidden_task["task_id"]]
        claimed = execute(
            bridge,
            "CLAIM_FORUM_TASK",
            {"task_id": task["task_id"], "expected_task_revision": task["lock_revision"]},
            marker="claim",
        )
        self.assertTrue(claimed["ok"], claimed)
        travelled = execute(
            bridge,
            "FAST_TRAVEL_CAMPUS",
            {"destination_id": task["execution_region_id"]},
            marker="travel",
        )
        self.assertTrue(travelled["ok"], travelled)
        completed = execute(
            bridge,
            "COMPLETE_FORUM_TASK",
            {"task_id": task["task_id"]},
            marker="complete",
        )
        self.assertTrue(completed["ok"], completed)
        final_task = bridge.snapshot()["tasks"][task["task_id"]]
        self.assertEqual("completed", final_task["state"])
        self.assertGreater(
            bridge.kernel._state.knowledge["actors"]["player"]["total_progress"], 0
        )

    def test_night_participation_and_task_results_are_deterministic(self):
        def trace(seed: int):
            bridge = CampusKernelBridge(seed)
            evening = advance_to_evening(bridge)
            execute(bridge, "ADVANCE_PHASE", marker="late")
            state = bridge.kernel._state
            return (
                tuple(state.situations["night_world"]["active_actor_ids"]),
                tuple(sorted(
                    (task["task_id"], task["state"], task.get("assignee_id"))
                    for task in state.tasks.values() if task.get("forum") == "night"
                )),
                evening["result"]["payload"]["phase_execution"]["night_task_view_count"],
            )

        self.assertEqual(trace(77), trace(77))

    def test_morning_expires_unfinished_work_and_records_the_previous_team_size(self):
        bridge = CampusKernelBridge(91)
        advance_to_evening(bridge)
        active_count = len(bridge.kernel._state.situations["night_world"]["active_actor_ids"])
        execute(bridge, "ADVANCE_PHASE", marker="late")
        morning = execute(bridge, "ADVANCE_PHASE", marker="morning")
        execution = morning["result"]["payload"]["phase_execution"]
        state = bridge.kernel._state
        self.assertEqual(active_count, execution["night_auto_exit_count"])
        self.assertGreaterEqual(execution["night_task_expired_count"], 0)
        self.assertEqual([], state.situations["night_world"]["active_actor_ids"])
        self.assertEqual(active_count, state.situations["night_world"]["last_night_actor_count"])
        self.assertFalse(any(
            task.get("forum") == "night" and task.get("state") in {"locked", "in_progress"}
            for task in state.tasks.values()
        ))

    def test_night_task_events_project_into_actor_chronicles_and_invariants_hold(self):
        bridge = CampusKernelBridge(123)
        advance_to_evening(bridge)
        execute(bridge, "ADVANCE_PHASE", marker="late")
        state = bridge.kernel._state
        completed = next(
            task for task in state.tasks.values()
            if task.get("forum") == "night" and task.get("state") == "completed"
        )
        actor_id = completed["assignee_id"]
        entries = [
            state.chronicles["entries"][entry_id]
            for entry_id in state.chronicles["by_actor"][actor_id]
        ]
        self.assertTrue(any(
            entry.get("category") == "task"
            and "night" in entry.get("knowledge_tags", ())
            and entry.get("parameters", {}).get("task_id") == completed["task_id"]
            for entry in entries
        ))
        self.assertEqual([], list(campus_night_world_invariant(state)))
        self.assertEqual([], list(campus_night_task_invariant(state)))


if __name__ == "__main__":
    unittest.main()
