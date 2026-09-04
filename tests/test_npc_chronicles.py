from __future__ import annotations

import unittest

from simulation.actions import SimulationCommand
from simulation.api import npc_chronicle_view
from simulation.api.server import CampusKernelBridge
from simulation.domain import NpcChronicleEntry, WorldState
from simulation.systems import (
    TransactionOutcome,
    WorldKernel,
    chronicle_invariant,
    install_chronicles,
    project_chronicle_events,
    validate_all_chronicles,
)


class FailingSink:
    def append_batch(self, _events) -> None:
        raise OSError("ledger unavailable")


def command(command_id: str = "chronicle-command") -> SimulationCommand:
    return SimulationCommand(
        command_id=command_id,
        actor_id="npc_a",
        action_id="TEST_ACTIVITY",
        expected_world_revision=1,
    )


def activity_handler(context, _command):
    context.state.population["npc_a"]["current_location_id"] = "library"
    context.emit(
        "ACTOR_LOCATION_CHANGED",
        "前往图书馆。",
        actor_ids=["npc_a"],
        scene_id="library",
        payload={"from_id": "dorm", "to_id": "library"},
        visibility="private",
        knowledge_tags=["location"],
    )
    context.emit(
        "CAMPUS_ACTIVITY_EFFECT_APPLIED",
        "完成自习。",
        actor_ids=["npc_a"],
        scene_id="library",
        payload={"activity_id": "SELF_STUDY", "effects": {"knowledge": {"gain": 2}}},
        visibility="private",
        knowledge_tags=["campus_activity", "study"],
    )
    context.emit(
        "NPC_ACTIVITY_COMPLETED",
        "在图书馆完成自习。",
        actor_ids=["npc_a"],
        scene_id="library",
        payload={"activity_id": "SELF_STUDY", "location_id": "library"},
        visibility="private",
        knowledge_tags=["schedule", "activity"],
    )
    return TransactionOutcome(True, True, "success", "done", commit=True)


class ChronicleDomainTests(unittest.TestCase):
    def test_entry_rejects_unknown_category_and_invalid_importance(self):
        base = dict(
            entry_id="chron:evt:1:npc_a", actor_id="npc_a", day=1,
            phase="morning", minute=0, category="routine",
            event_type="TEST", scene_id="library",
            source_event_ids=("evt:1",),
        )
        with self.assertRaisesRegex(ValueError, "category"):
            NpcChronicleEntry(**{**base, "category": "debug"})
        with self.assertRaisesRegex(ValueError, "importance"):
            NpcChronicleEntry(**{**base, "importance": 6})
        with self.assertRaisesRegex(ValueError, "phase"):
            NpcChronicleEntry(**{**base, "phase": "lunch"})

    def test_world_state_round_trip_preserves_chronicles(self):
        state = WorldState(population={"npc_a": {}})
        install_chronicles(state)
        restored = WorldState.from_dict(state.to_dict())
        self.assertEqual(state.chronicles, restored.chronicles)

    def test_deep_validation_catches_historical_entry_corruption(self):
        state = WorldState(population={"npc_a": {}})
        install_chronicles(state)
        state.chronicles["entries"]["broken"] = {"entry_id": "broken"}
        state.chronicles["by_actor"]["npc_a"].append("broken")
        state.chronicles["entry_count"] = 1
        self.assertTrue(list(validate_all_chronicles(state)))


class ChronicleProjectionTests(unittest.TestCase):
    def make_kernel(self, *, sink=None) -> WorldKernel:
        state = WorldState(population={
            "player": {"current_location_id": "library"},
            "npc_a": {"display_name": "测试人物", "current_location_id": "dorm"},
        })
        install_chronicles(state)
        kernel = WorldKernel(state, event_sink=sink)
        kernel.add_event_projector(project_chronicle_events)
        kernel.add_invariant(chronicle_invariant)
        kernel.register_handler("TEST_ACTIVITY", activity_handler)
        return kernel

    def test_movement_effect_and_completion_become_one_activity_entry(self):
        kernel = self.make_kernel()
        result = kernel.execute(command())
        state = kernel.state
        entry_ids = state.chronicles["by_actor"]["npc_a"]
        self.assertEqual(1, len(entry_ids))
        entry = state.chronicles["entries"][entry_ids[0]]
        self.assertEqual("activity_completed", entry["summary_key"])
        self.assertEqual("SELF_STUDY", entry["parameters"]["activity_id"])
        self.assertEqual("dorm", entry["parameters"]["from_id"])
        self.assertEqual("library", entry["parameters"]["to_id"])
        self.assertEqual(3, len(entry["source_event_ids"]))
        self.assertEqual(3, len(result.events))
        self.assertNotIn("NPC_DECISION_MADE", {entry["event_type"]})

    def test_projector_runs_before_invariants(self):
        kernel = self.make_kernel()
        kernel.add_invariant(
            lambda state: [] if state.chronicles["by_actor"]["npc_a"]
            else ["chronicle projection missing"]
        )
        kernel.execute(command())

    def test_event_sink_failure_rolls_back_state_event_sequence_and_chronicle(self):
        kernel = self.make_kernel(sink=FailingSink())
        with self.assertRaisesRegex(OSError, "ledger unavailable"):
            kernel.execute(command("failed-command"))
        state = kernel.state
        self.assertEqual("dorm", state.population["npc_a"]["current_location_id"])
        self.assertEqual(0, state.event_sequence)
        self.assertEqual([], state.chronicles["by_actor"]["npc_a"])
        self.assertEqual({}, state.chronicles["entries"])

    def test_intentions_and_global_clock_events_do_not_enter_personal_history(self):
        state = WorldState(population={"npc_a": {}})
        install_chronicles(state)
        kernel = WorldKernel(state)
        kernel.add_event_projector(project_chronicle_events)
        kernel.add_invariant(chronicle_invariant)

        def decide_only(context, _request):
            context.emit("NPC_DECISION_MADE", "准备学习。", actor_ids=["npc_a"])
            context.emit("WORLD_PHASE_ADVANCED", "时间推进。", actor_ids=["npc_a"])
            return TransactionOutcome(True, True, "success", "done", commit=True)

        kernel.register_handler("TEST_ACTIVITY", decide_only)
        kernel.execute(command())
        self.assertEqual([], kernel.state.chronicles["by_actor"]["npc_a"])


class ChronicleVisibilityAndPagingTests(unittest.TestCase):
    def make_kernel(self, *, player_location: str = "dorm") -> WorldKernel:
        state = WorldState(
            population={
                "player": {"display_name": "玩家", "current_location_id": player_location},
                "npc_a": {"display_name": "测试人物", "current_location_id": "library"},
            },
            places={
                "dorm": {"name": "宿舍", "tags": ["private"]},
                "library": {"name": "图书馆", "tags": ["study"]},
                "secret_room": {"name": "秘密房间", "tags": ["private", "restricted"]},
            },
        )
        install_chronicles(state)
        kernel = WorldKernel(state)
        kernel.add_event_projector(project_chronicle_events)
        kernel.add_invariant(chronicle_invariant)
        return kernel

    def test_public_campus_routine_is_reported_but_secret_event_is_hidden(self):
        kernel = self.make_kernel()

        def emit_events(context, _request):
            context.emit(
                "CAMPUS_ACTIVITY_EFFECT_APPLIED", "完成自习。",
                actor_ids=["npc_a"], scene_id="library",
                payload={"activity_id": "SELF_STUDY"}, visibility="private",
            )
            context.emit(
                "NIGHT_SECRET_FOUND", "发现秘密。",
                actor_ids=["npc_a"], scene_id="secret_room",
                visibility="secret", knowledge_tags=["night", "discovery"],
            )
            return TransactionOutcome(True, True, "success", "done", commit=True)

        kernel.register_handler("TEST_ACTIVITY", emit_events)
        kernel.execute(command())
        view = npc_chronicle_view(kernel.state, "npc_a")
        self.assertEqual(1, len(view["items"]))
        self.assertEqual("campus_record", view["items"][0]["source"])
        self.assertEqual("reported", view["items"][0]["certainty"])

    def test_colocated_player_gets_reliable_witness_record(self):
        kernel = self.make_kernel(player_location="library")
        kernel.register_handler("TEST_ACTIVITY", activity_handler)
        kernel.execute(command())
        item = npc_chronicle_view(kernel.state, "npc_a")["items"][0]
        self.assertEqual("witnessed", item["source"])
        self.assertEqual("reliable", item["certainty"])

    def test_pages_are_newest_first_and_cursor_is_bound_to_query(self):
        kernel = self.make_kernel()

        def publish(context, _request):
            for number in range(3):
                context.emit(
                    "FORUM_TASK_COMPLETED", f"完成任务 {number}。",
                    actor_ids=["npc_a"], scene_id="library",
                    payload={"task_id": f"task_{number}"}, visibility="public",
                    knowledge_tags=["forum", "task", "completed"],
                )
            return TransactionOutcome(True, True, "success", "done", commit=True)

        kernel.register_handler("TEST_ACTIVITY", publish)
        kernel.execute(command())
        first = npc_chronicle_view(kernel.state, "npc_a", limit=2, filter_name="all")
        self.assertTrue(first["has_more"])
        self.assertEqual(["task_2", "task_1"], [item["parameters"]["task_id"] for item in first["items"]])
        second = npc_chronicle_view(
            kernel.state, "npc_a", limit=2, filter_name="all", cursor=first["next_cursor"]
        )
        self.assertFalse(second["has_more"])
        self.assertEqual("task_0", second["items"][0]["parameters"]["task_id"])
        with self.assertRaisesRegex(ValueError, "does not match"):
            npc_chronicle_view(
                kernel.state, "npc_a", cursor=first["next_cursor"], filter_name="important"
            )


class CampusChronicleIntegrationTests(unittest.TestCase):
    def test_phase_execution_populates_logs_without_embedding_them_in_snapshot(self):
        bridge = CampusKernelBridge(42)
        before = bridge.snapshot()
        clock = before["clock"]
        response = bridge.execute({
            "command_id": "chronicle-phase-1",
            "actor_id": "player",
            "action_id": "ADVANCE_PHASE",
            "target_ids": [],
            "parameters": {},
            "expected_world_revision": before["revision"],
            "issued_day": clock["day"],
            "issued_phase": clock["phase"],
            "issued_minute": clock["minute"],
            "source": "player",
        })
        self.assertTrue(response["ok"])
        state = bridge.kernel.state
        npc_ids = [actor_id for actor_id in state.population if actor_id != "player"]
        self.assertTrue(all(state.chronicles["by_actor"][actor_id] for actor_id in npc_ids))
        self.assertNotIn("chronicles", response["snapshot"])
        visible_pages = [bridge.chronicle(actor_id, filter_name="all") for actor_id in npc_ids]
        self.assertTrue(any(page["items"] for page in visible_pages))


if __name__ == "__main__":
    unittest.main()
