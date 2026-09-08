"""Observed regional danger changes bounded choices, not hidden knowledge."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.domain.cognition import BoundedDecisionRequest, BoundedDialogueRequest
from simulation.systems.campus_cognition import bind_cognition_identity
from simulation.systems.campus_regional_choices import record_regional_notice, regional_awareness_invariant, situation_task_motivation
from simulation.systems.campus_night_tasks import _task_score
from simulation.systems import load_campus_location_graph
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_disputes import command
from tests.test_campus_contact_inquiries import as_npc


class RegionalChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        for _ in range(6):
            assert command(cls.bridge, "ADVANCE_PHASE", {})["ok"]
        cls.baseline, cls.rng = cls.bridge.kernel.capture_checkpoint()
        cls.graph = load_campus_location_graph(cls.bridge.registry)

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.state = self.bridge.kernel._state
        self.actor_id = next(n for n in self.state.situations["night_world"]["active_actor_ids"]
            if not self.state.population[n].get("active_forum_task_id"))
        self.task = next(t for t in self.state.tasks.values() if t.get("forum") == "night" and t.get("pressure_at_creation", 0) > 0
            and t["state"] in {"open", "viewed", "considering"})

    def test_unread_and_locked_notices_do_not_inform_scores(self):
        task = deepcopy(self.task)
        task["viewer_ids"] = []
        self.assertEqual(0, situation_task_motivation(self.state, self.actor_id, task)["adjustment"])
        task["viewer_ids"].append(self.actor_id)
        self.state.situations["night_world"]["actor_states"][self.actor_id]["night_forum_discovered"] = False
        self.assertEqual("", situation_task_motivation(self.state, self.actor_id, task)["reason"])

    def test_same_read_notice_changes_ranking_with_own_personality_and_condition(self):
        actor = self.state.population[self.actor_id]
        task = deepcopy(self.task)
        task["viewer_ids"] = [self.actor_id]
        task["pressure_at_creation"] = 8
        calm = {**task, "pressure_at_creation": 0}
        actor["personality"].update(altruism=100, conscientiousness=100, risk_tolerance=100)
        actor["needs"]["safety"] = 0
        actor["vitals"]["health"] = actor["vitals"]["max_health"]
        self.state.situations["night_world"]["actor_states"][self.actor_id]["pollution"] = 0
        self.assertGreater(_task_score(self.state, self.graph, self.actor_id, task), _task_score(self.state, self.graph, self.actor_id, calm))
        actor["personality"].update(altruism=0, conscientiousness=0, risk_tolerance=0)
        actor["needs"]["safety"] = 100
        actor["vitals"]["health"] = 1
        self.assertLess(_task_score(self.state, self.graph, self.actor_id, task), _task_score(self.state, self.graph, self.actor_id, calm))
        # A later invisible change is not retroactively known through this post.
        before = situation_task_motivation(self.state, self.actor_id, task)
        self.state.situations["campus_dynamics"]["regions"][task["execution_region_id"]]["pressure"] = 0
        self.assertEqual(before, situation_task_motivation(self.state, self.actor_id, task))

    def test_real_view_claim_reason_abandon_and_player_reclaim(self):
        task_id = self.task["task_id"]
        self.assertTrue(as_npc(self.bridge, self.actor_id, "VIEW_FORUM_TASK", {"task_id": task_id}).success)
        task = self.bridge.kernel._state.tasks[task_id]
        self.assertTrue(as_npc(self.bridge, self.actor_id, "CLAIM_FORUM_TASK", {"task_id": task_id, "expected_task_revision": task["lock_revision"]}).success)
        state = self.bridge.kernel._state
        choice = state.tasks[task_id]["situation_choice"]
        self.assertEqual(self.actor_id, choice["actor_id"])
        self.assertEqual({"actor_id", "pressure", "reason"}, set(choice))
        self.assertTrue(any(h["kind"] == "choice_reason" for h in state.tasks[task_id]["history"]))
        self.assertNotIn(task_id, self.bridge.snapshot()["tasks"])
        self.assertTrue(command(self.bridge, "ENTER_NIGHT_WORLD", {})["ok"])
        self.assertEqual(choice, self.bridge.snapshot()["tasks"][task_id]["situation_choice"])
        self.assertNotIn("regional_awareness", self.bridge.snapshot().get("cognition", {}))
        self.assertTrue(as_npc(self.bridge, self.actor_id, "ABANDON_FORUM_TASK", {"task_id": task_id}).success)
        task = self.bridge.kernel._state.tasks[task_id]
        self.assertNotIn("situation_choice", task)
        self.assertTrue(command(self.bridge, "CLAIM_FORUM_TASK", {"task_id": task_id, "expected_task_revision": task["lock_revision"]})["ok"])
        self.assertNotIn("situation_choice", self.bridge.kernel._state.tasks[task_id])

    def test_only_own_dated_notices_in_overnight_context_and_checkpoint(self):
        self.task["viewer_ids"] = list(set(self.task["viewer_ids"]) | {self.actor_id})
        record_regional_notice(self.state, self.actor_id, self.task)
        region = self.task["execution_region_id"]
        notice = deepcopy(self.state.cognition["regional_awareness"][self.actor_id][region])
        old = {**self.task, "created_day": self.task["created_day"] - 1, "pressure_at_creation": 12}
        record_regional_notice(self.state, self.actor_id, old)
        self.assertEqual(notice, self.state.cognition["regional_awareness"][self.actor_id][region])
        request = BoundedDecisionRequest(self.actor_id, 1, 2, "morning", {}, {}, "", (), ())
        own = bind_cognition_identity(self.state, request).state["own_read_regional_notices"]
        self.assertIn(notice, own)
        self.assertLessEqual(len(own), 6)
        dialogue = BoundedDialogueRequest(self.actor_id, "player", 1, 2, "morning", {}, {}, {}, (), "你好", (), "player", {})
        self.assertNotIn("own_read_regional_notices", bind_cognition_identity(self.state, dialogue).state)
        with TemporaryDirectory() as directory:
            target = Path(directory) / "regional.json"
            save_kernel_checkpoint(target, self.state, self.rng)
            restored = load_kernel_checkpoint(target).state
            self.assertEqual(self.state.cognition["regional_awareness"], restored.cognition["regional_awareness"])
            self.assertEqual([], regional_awareness_invariant(restored))
        self.state.cognition["regional_awareness"][self.actor_id][region]["pressure"] = 999
        self.assertTrue(regional_awareness_invariant(self.state))

    def test_old_save_without_new_optional_ledger_remains_valid(self):
        self.state.cognition.pop("regional_awareness", None)
        for task in self.state.tasks.values():
            task.pop("situation_choice", None)
        self.assertEqual([], regional_awareness_invariant(self.state))
        self.state.cognition["regional_awareness"] = {"unknown": {}}
        self.assertTrue(regional_awareness_invariant(self.state))


if __name__ == "__main__":
    unittest.main()
