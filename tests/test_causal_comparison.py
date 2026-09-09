"""Evidence integrity checks, not proof that an autonomous week is fun."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from production.run_causal_comparison import (AuditSession, natural_start, sample,
    world_digest, visible_people, explore, run_branch, compare, code_manifest)
from simulation.api.server import CampusKernelBridge


class CausalComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkpoint, cls.cid, cls.bootstrap = natural_start(42)

    def setUp(self):
        self.bridge = CampusKernelBridge(42)
        self.bridge.kernel.restore_checkpoint(*self.checkpoint, expected_revision=self.bridge.kernel.state.revision)

    def test_natural_start_uses_only_successful_phase_actions(self):
        self.assertTrue(self.bootstrap)
        self.assertTrue(all(r["command"]["action_id"] == "ADVANCE_PHASE" and r["result"]["success"] for r in self.bootstrap))
        state = self.checkpoint[0]
        self.assertIn(self.cid, state.situations["night_sites"]["sites"])
        self.assertEqual("unsettled", state.situations["campus_anomalies"]["cases"][self.cid]["status"])

    def test_restores_identical_world_and_rng_without_changing_source(self):
        before = world_digest(self.bridge)
        other = CampusKernelBridge(42)
        other.kernel.restore_checkpoint(*self.checkpoint, expected_revision=other.kernel.state.revision)
        self.assertEqual(before, world_digest(other))
        self.assertNotEqual(self.bridge.kernel._state.revision, self.checkpoint[0].revision)

    def test_sample_is_read_only_and_separates_private_case_from_player_views(self):
        before = world_digest(self.bridge)
        row = sample(self.bridge, self.cid)
        self.assertEqual(before, world_digest(self.bridge))
        self.assertIn("core", row["auditor_only"]["case"])
        shown = row["available_player_views_not_proof_of_reading"]
        self.assertNotIn("auditor_only", shown)
        self.assertEqual(self.bridge.snapshot()["social"], shown["social"])
        self.assertEqual(self.bridge.snapshot()["messaging"], shown["messaging"])

    def test_sampling_detects_accidental_mutation(self):
        original = self.bridge.snapshot
        def unsafe():
            value = original()
            self.bridge.kernel._state.population["player"]["wealth"] += 1
            return value
        with patch.object(self.bridge, "snapshot", side_effect=unsafe):
            with self.assertRaisesRegex(RuntimeError, "mutated"):
                sample(self.bridge, self.cid)

    def test_commands_after_restore_do_not_reuse_bootstrap_ids(self):
        session = AuditSession(self.bridge)
        self.assertTrue(session.act("ADVANCE_PHASE").success)
        self.assertNotIn(session.commands[0]["command"]["command_id"],
            {r["command"]["command_id"] for r in self.bootstrap})

    def test_visibility_obeys_colocation_contacts_and_cap(self):
        population = {f"npc-{i:02}": {"current_location_id": "here", "is_phone_contact": i == 24} for i in range(25)}
        population["remote-friend"] = {"current_location_id": "elsewhere", "is_phone_contact": True}
        view = {"player": {"current_location_id": "here"}, "population": population}
        people = visible_people(view)
        self.assertEqual(18, len(people))
        self.assertEqual("npc-24", people[0])
        self.assertNotIn("remote-friend", people)

    def test_explorer_cannot_target_remote_noncontact_from_population_projection(self):
        view = {"clock": {"day": 3, "phase": "morning"}, "player": {"current_location_id": "here"},
            "population": {"hidden-target": {"current_location_id": "elsewhere"},
                "local": {"current_location_id": "here"}}, "messaging": {"contacts": []},
            "social": {"anomalies": []}, "growth": {"topics": []}}
        class Session:
            bridge = type("Bridge", (), {"snapshot": lambda self: deepcopy(view)})()
            calls = []
            def travel(self, destination): return True
            def act(self, action, params): self.calls.append((action, params))
        session = Session()
        explore(session, 0)
        self.assertEqual([("ASK_ANOMALY_EXPERIENCE", {"npc_id": "local"})], session.calls)

    def test_complete_one_day_comparison_and_tampering_rejection(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("Offline audit must not use network")):
            left = run_branch(self.checkpoint, self.cid, 1, "unattended")
            right = run_branch(self.checkpoint, self.cid, 1, "explorer")
        self.assertTrue(compare(left, right)["same_checkpoint_verified"])
        self.assertEqual(5, len(left["frames"]))
        for kind in ("source", "period", "clock", "intervention", "api", "duplicate_branch"):
            with self.subTest(kind=kind):
                bad = deepcopy(left)
                if kind == "source": bad["source_digest"] = "different"
                if kind == "period": bad["frames"].pop()
                if kind == "clock": bad["frames"][1]["clock"]["day"] += 1
                if kind == "intervention": bad["commands"].append({"command": {"action_id": "ASK_ANOMALY_EXPERIENCE"}})
                if kind == "api": bad["frames"][0]["calls_today"] = 1
                if kind == "duplicate_branch": bad["mode"] = "explorer"
                with self.assertRaises(ValueError): compare(bad, right)

    def test_source_manifest_excludes_private_design_and_handoff(self):
        manifest = code_manifest()
        self.assertIn("production/run_causal_comparison.py", manifest)
        self.assertIn("simulation/api/server.py", manifest)
        self.assertFalse(any(path.startswith("design/") or "STEP_08_HANDOFF" in path for path in manifest))


if __name__ == "__main__": unittest.main()
