"""Shared, physical recon evidence; never a reskinned automatic combat reward."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems.campus_fieldwork import fieldwork_invariant, report_claim_ids
from simulation.systems.campus_tasks import complete_assigned_task
from simulation.systems.transactions import TransactionContext
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_combat_deployment import execute, travel_to_location


class FieldworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        for index in range(2):
            result = execute(cls.bridge, "ADVANCE_PHASE", marker=f"field-init-{index}")
            assert result["ok"], result["result"]["code"]
        cls.baseline, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.baseline, self.rng, expected_revision=self.bridge.kernel.state.revision)
        self.counter = 0
        self.task = next(t for t in self.bridge.kernel.state.tasks.values() if t.get("resolution_kind") == "field_recon"
                         and t["state"] in {"open", "viewed", "considering"})

    def act(self, action, params=None, actor="player", source="player", marker=None):
        self.counter += 1
        state = self.bridge.kernel.state
        return self.bridge.execute({"command_id": marker or f"field:{self.counter}:{state.revision}:{action}",
            "actor_id": actor, "source": source, "action_id": action, "parameters": params or {}, "target_ids": [],
            "expected_world_revision": state.revision, "issued_day": state.clock.day, "issued_phase": state.clock.phase,
            "issued_minute": state.clock.minute})

    def prepare_player(self):
        self.assertTrue(self.act("ENTER_NIGHT_WORLD")["ok"])
        self.assertTrue(self.act("CLAIM_FORUM_TASK", {"task_id": self.task["task_id"], "expected_task_revision": self.task["lock_revision"]})["ok"])
        travel_to_location(self.bridge, self.task["scene_id"])

    def submit(self, **extra):
        task = self.bridge.kernel.state.tasks[self.task["task_id"]]
        return self.act("SUBMIT_FIELD_REPORT", {"task_id": task["task_id"], "expected_task_revision": task["lock_revision"], **extra})

    def test_real_search_then_report_costs_one_action_and_preserves_clock(self):
        self.prepare_player()
        before = self.bridge.kernel.state
        self.assertEqual("field_evidence_required", self.submit()["result"]["code"])
        result = self.act("SEARCH_SCENE")
        self.assertTrue(result["ok"], result)
        after_search = self.bridge.kernel.state
        keys = report_claim_ids(after_search, "player", self.task)
        self.assertEqual(2, len(keys))
        for key in keys:
            self.assertEqual(self.task["field_site_id"], after_search.knowledge["claims"][key]["object_id"])
        self.assertEqual(before.action_economy["actors"]["player"]["major_remaining"] - 1,
                         after_search.action_economy["actors"]["player"]["major_remaining"])
        result = self.submit()
        self.assertTrue(result["ok"], result)
        after = self.bridge.kernel.state
        self.assertEqual(before.clock, after.clock)
        self.assertEqual(after_search.action_economy, after.action_economy)
        self.assertEqual(before.population["player"]["wealth"] + self.task["reward"]["wealth"], after.population["player"]["wealth"])
        self.assertEqual({}, after.battles)
        self.assertEqual("field_report", after.tasks[self.task["task_id"]]["completion_evidence"]["kind"])
        self.assertEqual([], fieldwork_invariant(after))

    def test_notice_cannot_replace_physical_evidence_and_fake_report_is_atomic(self):
        self.prepare_player()
        self.assertTrue(self.act("OBSERVE_SCENE")["ok"])
        self.assertEqual("field_evidence_required", self.submit()["result"]["code"])
        before = self.bridge.kernel.state
        self.assertEqual("invalid_field_report", self.submit(summary="我已经查清幕后黑手", claim_ids=["fake"])["result"]["code"])
        after = self.bridge.kernel.state
        for field in ("population", "knowledge", "action_economy", "tasks", "revision"):
            self.assertEqual(getattr(before, field), getattr(after, field))

    def test_actual_npc_traversal_search_and_completion_without_player(self):
        result = self.act("ADVANCE_PHASE")
        self.assertTrue(result["ok"], result["result"]["code"])
        state = self.bridge.kernel.state
        reports = [t for t in state.tasks.values() if t.get("field_report")]
        self.assertTrue(reports)
        for task in reports:
            npc = task["assignee_id"]
            self.assertNotEqual("player", npc)
            self.assertEqual(task["scene_id"], state.population[npc]["current_location_id"])
            self.assertEqual("completed", task["state"])
            self.assertEqual(0, state.action_economy["actors"][npc]["major_remaining"])
            self.assertEqual(2, len(report_claim_ids(state, npc, task)))
            self.assertFalse(any(b["situation_id"] == task["task_id"] for b in state.battles.values()))
        events = result["result"]["events"]
        self.assertTrue(any(e["event_type"] == "CAMPUS_INVESTIGATION_COMPLETED" and e["payload"]["action_id"] == "SEARCH_SCENE" for e in events))
        self.assertTrue(any(e["event_type"] == "FIELD_REPORT_SUBMITTED" for e in events))
        self.assertFalse(state.knowledge.get("investigation", {}).get("notes_by_actor", {}).get("player"))

    def test_no_budget_no_readings_and_no_reward(self):
        self.prepare_player()
        self.bridge.kernel._state.action_economy["actors"]["player"]["major_remaining"] = 0
        before = self.bridge.kernel.state
        self.assertEqual("major_action_exhausted", self.act("SEARCH_SCENE")["result"]["code"])
        self.assertEqual(before.knowledge, self.bridge.kernel.state.knowledge)
        self.assertEqual("field_evidence_required", self.submit()["result"]["code"])

    def test_report_requires_current_integer_task_revision(self):
        self.prepare_player()
        self.assertTrue(self.act("SEARCH_SCENE")["ok"])
        before = self.bridge.kernel.state
        for revision in (True, "1", -1, 999):
            result = self.submit(expected_task_revision=revision)
            self.assertEqual("task_revision_conflict", result["result"]["code"])
            self.assertEqual(before.tasks, self.bridge.kernel.state.tasks)
            self.assertEqual(before.population, self.bridge.kernel.state.population)

    def test_shared_rumor_requires_independent_verification(self):
        self.prepare_player()
        self.assertTrue(self.act("SEARCH_SCENE")["ok"])
        state = self.bridge.kernel._state
        ids = report_claim_ids(state, "player", self.task)
        for key in ids:
            state.knowledge["beliefs_by_actor"]["player"][key].update(source_kind="hearsay", source_actor_id=self.task["issuer_id"], transmission_count=1)
        self.assertEqual([], report_claim_ids(state, "player", self.task))
        self.assertEqual("field_evidence_required", self.submit()["result"]["code"])
        # Explicit restored budget boundary; the verification still uses common search.
        state.action_economy["actors"]["player"]["major_remaining"] = 1
        self.assertTrue(self.act("SEARCH_SCENE")["ok"])
        self.assertTrue(self.submit()["ok"])

    def test_physical_values_and_npc_evidence_are_not_in_public_snapshot(self):
        snapshot = self.bridge.snapshot()
        self.assertFalse(snapshot["forums"]["night"]["enabled"])
        self.assertNotIn("field_sites", snapshot)
        self.prepare_player()
        snapshot = self.bridge.snapshot()
        task = snapshot["tasks"][self.task["task_id"]]
        self.assertFalse(task["fieldwork"]["ready_to_report"])
        self.assertNotIn("measurements", task)
        self.assertNotIn("field_report", task)
        self.assertNotIn(self.task["field_site_id"], str(snapshot["investigation"]["entries"]))

    def test_report_duplicate_and_disk_checkpoint_preserve_reads_and_reward(self):
        self.prepare_player()
        self.assertTrue(self.act("SEARCH_SCENE")["ok"])
        state, rng = self.bridge.kernel.capture_checkpoint()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "field.json"
            save_kernel_checkpoint(path, state, rng, content_manifest=self.bridge.registry.manifest)
            loaded = load_kernel_checkpoint(path, expected_content_version=self.bridge.registry.content_version)
            self.bridge.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=state.revision)
        self.assertTrue(self.submit()["ok"])
        wealth = self.bridge.kernel.state.population["player"]["wealth"]
        self.assertEqual("task_not_owned", self.submit()["result"]["code"])
        self.assertEqual(wealth, self.bridge.kernel.state.population["player"]["wealth"])
        self.assertEqual(state.situations["field_sites"], self.bridge.kernel.state.situations["field_sites"])

    def test_combat_or_free_activity_cannot_complete_a_recon_contract(self):
        self.prepare_player()
        self.assertFalse(self.act("START_BATTLE_PREPARATION", {"task_id": self.task["task_id"]})["ok"])
        self.assertFalse(self.act("COMPLETE_FORUM_TASK", {"task_id": self.task["task_id"]})["ok"])
        state, rng = self.bridge.kernel.capture_checkpoint()
        command = SimulationCommand(command_id="fake-result", actor_id="player", action_id="COMPLETE_FORUM_TASK", expected_world_revision=state.revision)
        self.assertFalse(complete_assigned_task(TransactionContext(state, rng, command), "player", {"task_id": self.task["task_id"], "battle_id": "fake"}))

    def test_wrong_site_and_wrong_layer_do_not_reveal_records(self):
        self.prepare_player()
        result = self.act("FAST_TRAVEL_CAMPUS", {"destination_id": "south_gate_region" if self.task["scene_id"] != "south_gate_region" else "central_region"})
        self.assertTrue(result["ok"], result)
        self.assertEqual("task_location_required", self.submit()["result"]["code"])
        self.assertTrue(self.act("EXIT_NIGHT_WORLD")["ok"])
        self.assertEqual("task_not_owned", self.submit()["result"]["code"])
        task = self.bridge.kernel.state.tasks[self.task["task_id"]]
        self.assertIsNone(task["assignee_id"])
        self.assertEqual("open", task["state"])

    def test_invalid_site_and_forged_report_fail_invariant(self):
        state = self.bridge.kernel.state
        state.situations["field_sites"]["sites"][self.task["field_site_id"]]["measurements"][0]["value"] = "fake"
        self.assertTrue(fieldwork_invariant(state))
        self.prepare_player()
        self.assertTrue(self.act("SEARCH_SCENE")["ok"])
        self.assertTrue(self.submit()["ok"])
        state = self.bridge.kernel.state
        state.tasks[self.task["task_id"]]["field_report"]["claim_ids"] = ["fake", "fake"]
        self.assertTrue(fieldwork_invariant(state))

    def test_duplicate_report_command_replays_without_second_reward(self):
        self.prepare_player()
        self.assertTrue(self.act("SEARCH_SCENE")["ok"])
        state = self.bridge.kernel.state
        task = state.tasks[self.task["task_id"]]
        payload = {"command_id": "one-field-report", "actor_id": "player", "source": "player", "action_id": "SUBMIT_FIELD_REPORT",
                   "parameters": {"task_id": task["task_id"], "expected_task_revision": task["lock_revision"]}, "target_ids": [],
                   "expected_world_revision": state.revision, "issued_day": state.clock.day, "issued_phase": state.clock.phase, "issued_minute": 0}
        self.assertTrue(self.bridge.execute(payload)["ok"])
        after = self.bridge.kernel.state
        repeated = self.bridge.execute(payload)
        self.assertTrue(repeated["result"]["replayed"])
        self.assertEqual(after, self.bridge.kernel.state)

    def test_content_migration_preserves_existing_contracts_and_rejects_fake_manifest(self):
        from simulation.persistence.content_migrations import migrate_campus_content
        from simulation.persistence.kernel_checkpoint import LoadedCheckpoint, CheckpointError
        spec = json.loads((Path(__file__).resolve().parents[1] / "simulation/persistence/campus_field_content.json").read_text())
        # Explicit content identity boundary; a genuine prior-build disk save is
        # additionally exercised by the release verification outside this unit.
        state, rng = self.bridge.kernel.capture_checkpoint()
        state.content_version = spec["source_version"]
        state.situations.pop("campus_life", None)  # Frozen old content predates public activities.
        loaded = LoadedCheckpoint(state, rng, spec["source_manifest"])
        result = migrate_campus_content(loaded, self.bridge.registry.content_version)
        comparison = result.state.clone()
        comparison.content_version = state.content_version
        life = comparison.situations.pop("campus_life")
        self.assertEqual({}, life["records"])
        self.assertEqual(self.bridge.registry.all("life_opportunity"), life["definitions"])
        self.assertEqual(state, comparison)
        self.assertEqual(rng.snapshot(), result.rng.snapshot())
        self.assertEqual(self.bridge.registry.manifest, result.content_manifest)
        self.assertIn(spec["migration_id"], result.migrations)
        loaded = LoadedCheckpoint(state, rng, {})
        with self.assertRaises(CheckpointError):
            migrate_campus_content(loaded, self.bridge.registry.content_version)
