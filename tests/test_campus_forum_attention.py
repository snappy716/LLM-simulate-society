"""Real staged attention, atomic competition and no implicit clock advance."""
from copy import deepcopy
import unittest
from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_forum_attention import attention_invariant
from simulation.systems.campus_schedules import current_schedule_slot


class ForumAttentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.initial, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.sequence = 0

    def act(self, action="ADVANCE_SOCIAL_PULSE", params=None, actor="player", phase=None):
        self.sequence += 1
        state = self.bridge.kernel.state
        self.last_command = SimulationCommand(f"attention-test:{self.sequence}", actor, action, state.revision,
            parameters=params or {}, issued_day=state.clock.day, issued_phase=phase or state.clock.phase)
        return self.bridge.kernel.execute(self.last_command)

    def test_same_phase_shows_views_then_consideration_then_staggered_claims(self):
        before = self.bridge.kernel.state
        counts = []
        for _ in range(10):
            result = self.act()
            self.assertTrue(result.success, result.code)
            counts.append(result.payload)
        after = self.bridge.kernel.state
        self.assertGreater(counts[0]["attention_view_count"], 0)
        self.assertEqual(0, counts[0]["attention_consider_count"])
        self.assertEqual(0, counts[0]["attention_claim_count"])
        claim_beats = [index for index, count in enumerate(counts) if count["attention_claim_count"]]
        self.assertGreater(len(claim_beats), 1)
        self.assertGreaterEqual(min(claim_beats), 2)
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(before.action_economy, after.action_economy)
        self.assertEqual(before.inventories, after.inventories)
        self.assertEqual(before.population["player"], after.population["player"])
        self.assertEqual([], attention_invariant(after))

    def test_duplicate_pulse_replays_without_new_attention(self):
        self.assertTrue(self.act().success)
        before, rng = self.bridge.kernel.capture_checkpoint()
        replay = self.bridge.kernel.execute(self.last_command)
        self.assertTrue(replay.replayed)
        after, current = self.bridge.kernel.capture_checkpoint()
        self.assertEqual(before.cognition, after.cognition)
        self.assertEqual(before.tasks, after.tasks)
        self.assertEqual(rng.snapshot(), current.snapshot())

    def test_player_can_claim_while_npc_is_considering_without_being_overwritten(self):
        for _ in range(2):
            self.assertTrue(self.act().success)
        state = self.bridge.kernel.state
        target = next(task for task in state.tasks.values() if task.get("considering_ids") and task["state"] == "considering")
        result = self.act("CLAIM_FORUM_TASK", {"task_id": target["task_id"], "expected_task_revision": target["lock_revision"]})
        self.assertTrue(result.success, result.code)
        for _ in range(6):
            self.assertTrue(self.act().success)
        task = self.bridge.kernel.state.tasks[target["task_id"]]
        self.assertEqual("player", task["assignee_id"])
        self.assertEqual([], task["considering_ids"])

    def test_npc_can_claim_before_player_and_stale_claim_is_rejected(self):
        initial = self.bridge.kernel.state
        for _ in range(6):
            self.assertTrue(self.act().success)
        state = self.bridge.kernel.state
        task = next(task for task in state.tasks.values() if task.get("assignee_id"))
        result = self.act("CLAIM_FORUM_TASK", {"task_id": task["task_id"],
                          "expected_task_revision": initial.tasks[task["task_id"]]["lock_revision"]})
        self.assertFalse(result.success)
        self.assertEqual("task_revision_conflict", result.code)
        self.assertEqual(task["assignee_id"], self.bridge.kernel.state.tasks[task["task_id"]]["assignee_id"])
        self.assertNotEqual("player", task["assignee_id"])

    def test_stale_clock_and_targeted_requests_do_not_mutate_world(self):
        self.assertEqual("command_clock_mismatch", self.act(phase="late_night").code)
        self.assertEqual("invalid_attention_request", self.act(params={"task_id": "forced"}).code)
        self.assertEqual("invalid_attention_request", self.act(actor="campus_student_001").code)
        state = self.bridge.kernel.state
        self.assertEqual(self.initial.tasks, state.tasks)
        self.assertEqual(self.initial.clock, state.clock)
        self.assertNotIn("forum_attention", state.cognition)

    def test_protected_duties_do_not_browse_or_claim(self):
        protected = {actor for actor in self.initial.population if actor != "player"
                     and current_schedule_slot(self.initial, actor).get("priority", 0) >= 90}
        self.assertTrue(protected)
        for _ in range(10):
            self.assertTrue(self.act().success)
        for task in self.bridge.kernel.state.tasks.values():
            self.assertFalse(protected & set(task["viewer_ids"]))
            self.assertNotIn(task.get("assignee_id"), protected)

    def test_checkpoint_restores_pending_consideration_and_rng(self):
        for _ in range(2):
            self.act()
        saved, rng = self.bridge.kernel.capture_checkpoint()
        counter = self.sequence
        for _ in range(6):
            self.act()
        expected, expected_rng = self.bridge.kernel.capture_checkpoint()
        self.bridge.kernel.restore_checkpoint(saved, rng, expected_revision=expected.revision)
        self.sequence = counter
        for _ in range(6):
            self.act()
        actual, actual_rng = self.bridge.kernel.capture_checkpoint()
        self.assertEqual(expected.tasks, actual.tasks)
        self.assertEqual(expected.cognition, actual.cognition)
        self.assertEqual(expected_rng.snapshot(), actual_rng.snapshot())

    def test_private_attention_records_are_not_exposed_by_snapshot(self):
        for _ in range(3):
            self.act()
        snapshot = self.bridge.snapshot()
        self.assertNotIn("forum_attention", snapshot.get("cognition", {}))
        for task in snapshot["tasks"].values():
            self.assertNotIn("viewer_ids", task)
            self.assertNotIn("considering_ids", task)
            self.assertNotIn("npc_claim_phase_index", task)
        self.assertFalse(snapshot["forums"]["night"]["enabled"])

    def test_invalid_pending_record_is_rejected(self):
        self.act()
        state = self.bridge.kernel.state
        actor = next(iter(state.cognition["forum_attention"]["actors"]))
        state.cognition["forum_attention"]["actors"][actor]["stage"] = 9
        self.assertTrue(attention_invariant(state))
        state = self.bridge.kernel.state
        state.cognition["forum_attention"]["phase"] = [9, "morning"]
        self.assertTrue(attention_invariant(state))

    def test_phase_changes_flush_work_without_a_running_godot_client(self):
        for _ in range(3):
            result = self.act("ADVANCE_PHASE")
            self.assertTrue(result.success, result.code)
        state = self.bridge.kernel.state
        self.assertEqual((1, "late_night"), (state.clock.day, state.clock.phase))
        self.assertTrue(any(task.get("execution_receipts") for task in state.tasks.values()))
        self.assertTrue(all("player" not in battle["participant_ids"] for battle in state.battles.values()))
        late_claims = [event for event in result.events if event.event_type == "FORUM_TASK_CLAIMED" and event.payload.get("forum") == "night"]
        self.assertTrue(late_claims)
        self.assertTrue(all(event.phase == "evening" for event in late_claims))
        self.assertTrue(all(event.phase == "late_night" for event in result.events if event.event_type == "NPC_NIGHT_TASK_EXECUTED"))
        self.assertEqual([], attention_invariant(state))


if __name__ == "__main__":
    unittest.main()
