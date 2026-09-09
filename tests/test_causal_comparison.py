"""Evidence integrity checks, not proof that an autonomous week is fun."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from production.run_causal_comparison import (AuditSession, natural_start, sample,
    world_digest, visible_people, explore, run_branch, compare, code_manifest)
from simulation.api.server import CampusKernelBridge
from production.causal_player_policy import daytime, participate


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

    def test_participant_observes_present_people_before_walking_away(self):
        calls = []
        view = {"clock": {"day": 3, "phase": "morning"}, "player": {"current_location_id": "here"},
            "population": {"present": {"current_location_id": "here"}, "remote": {"current_location_id": "elsewhere"}},
            "messaging": {"contacts": []}, "social": {"anomalies": [], "anomaly_meetings": []}, "growth": {"topics": []}}
        session = SimpleNamespace(bridge=SimpleNamespace(snapshot=lambda: deepcopy(view)),
            act=lambda action, params: (calls.append((action, params)) or SimpleNamespace(success=False)),
            travel=lambda destination: calls.append(("travel", destination)))
        with patch("production.causal_player_policy.support_here", return_value=False):
            daytime(session, 0)
        self.assertEqual("ASK_ANOMALY_EXPERIENCE", calls[0][0])
        self.assertEqual({"npc_id": "present"}, calls[0][1])
        self.assertFalse(any(params == {"npc_id": "remote"} for _, params in calls))

    def test_due_appointment_precedes_exploration_and_study(self):
        calls = []
        view = {"clock": {"day": 3, "phase": "morning"}, "social": {"anomaly_meetings": [
            {"status": "confirmed", "day": 3, "phase": "morning", "location_id": "agreed_place"}]}}
        session = SimpleNamespace(bridge=SimpleNamespace(snapshot=lambda: deepcopy(view)),
            travel=lambda place: calls.append(place))
        with patch("production.causal_player_policy.support_here", return_value=False) as support:
            daytime(session, 0)
        self.assertEqual(["agreed_place"], calls)
        support.assert_called_once_with(session)

    def test_late_night_rest_uses_own_home_and_formal_action(self):
        calls = []
        view = {"clock": {"phase": "late_night"}, "night_world": {"current_layer": "surface"},
            "player": {"home_location_id": "my_home", "can_rest_recover": True,
                "vitals": {"health": 10, "max_health": 20, "focus": 20, "max_focus": 20}}}
        before = deepcopy(view)
        session = SimpleNamespace(bridge=SimpleNamespace(snapshot=lambda: deepcopy(view)),
            travel=lambda place: calls.append(("travel", place)), act=lambda action: calls.append((action, {})))
        participate(session, 3)
        self.assertEqual([("travel", "my_home"), ("REST", {})], calls)
        self.assertEqual(before, view)

    def test_clock_validator_accounts_for_automatic_defeat_without_fake_frames(self):
        # Synthetic validator input only, never injected into a game world.
        phases = ("morning", "afternoon", "evening", "late_night")
        def clock(tick): return {"day": tick // 4 + 1, "phase": phases[tick % 4]}
        def branch(mode, ids):
            events = [{"event_type": "WORLD_PHASE_ADVANCED", "command_id": cid,
                "payload": {**clock(i + 1), "previous_day": clock(i)["day"], "previous_phase": clock(i)["phase"]}}
                for i, cid in enumerate(ids)]
            groups = {cid: i + 1 for i, cid in enumerate(ids)}
            return {"mode": mode, "days": 1, "source_digest": "same", "start_digest": "same", "case_id": "same",
                "frames": [{"clock": clock(0), "calls_today": 0}] + [{"clock": clock(tick), "calls_today": 0,
                    "sample_after_command": cid} for cid, tick in groups.items()],
                "events": events, "summary": {}, "commands": [{"command": {"command_id": cid,
                    "action_id": "END_COMBAT_ROUND" if cid == "defeat" else "ADVANCE_PHASE"}, "result": {"success": True}}
                    for cid in groups]}
        left = branch("unattended", ["a", "b", "c", "d"])
        right = branch("participant", ["a", "b", "defeat", "defeat"])
        self.assertTrue(compare(left, right)["same_checkpoint_verified"])
        broken = deepcopy(right)
        broken["events"].pop()
        with self.assertRaises(ValueError): compare(left, broken)
        broken = deepcopy(right)
        broken["frames"].insert(-1, {"clock": clock(3), "calls_today": 0, "sample_after_command": "defeat"})
        with self.assertRaises(ValueError): compare(left, broken)

    def test_participant_uses_real_cards_and_public_task_without_hidden_case_target(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("No API in offline test")):
            left = run_branch(self.checkpoint, self.cid, 1, "unattended")
            right = run_branch(self.checkpoint, self.cid, 1, "participant")
        self.assertTrue(compare(left, right)["same_checkpoint_verified"])
        successful = [r["command"]["action_id"] for r in right["commands"] if r["result"]["success"]]
        self.assertIn("START_CARD_COMBAT", successful)
        self.assertIn("PLAY_COMBAT_CARD", successful)
        self.assertIn("VIEW_FORUM_TASK", successful)
        self.assertEqual(0, right["summary"]["api_calls"])
        self.assertEqual(sum(r["route"] == "day_support" and r["helper_id"] == "player"
            for r in right["summary"]["history"]), right["summary"]["player_supports"])
        self.assertGreater(right["summary"]["player_night_containments"], 0)

    def test_provider_axis_keeps_identical_checkpoint_and_tracks_real_adapter_requests(self):
        import io
        import json
        import tempfile
        from pathlib import Path
        from production.live_causal_audit import CausalProvider, AuditBudget, coverage
        class Response(io.BytesIO):
            status = 200
        def respond(request, **kwargs):
            payload = json.loads(json.loads(request.data)["messages"][1]["content"])
            result = {"npc_id": payload["npc_id"], "candidate_revision": payload["candidate_revision"]}
            if "daily_options" in payload:
                result.update(selected_action_id=None, reason="test", social_choice=None,
                    daily_choices={phase: options[0]["candidate_id"] for phase, options in payload["daily_options"].items()})
            elif "dialogue_kind" in payload:
                result.update(target_id=payload["target_id"], utterance="你好。", fact_ids_used=[])
            else:
                result.update(selected_action_id=payload["candidates"][0]["candidate_id"], reason="test")
            return Response(json.dumps({"id": "mock-only", "model": "mock-only", "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}).encode())
        with tempfile.TemporaryDirectory() as directory:
            provider = CausalProvider("fake-private-test-key", Path(directory)/"live", AuditBudget(Path(directory)))
            with patch("urllib.request.urlopen", respond):
                left = run_branch(self.checkpoint, self.cid, 1, "unattended")
                right = run_branch(self.checkpoint, self.cid, 1, "unattended", provider=provider)
            self.assertEqual(20, sum(r["kind"] == "plan" for r in provider.records))
            self.assertTrue(compare(left, right, axis="provider", allow_api=True)["same_checkpoint_verified"])
            self.assertEqual(20, coverage(right)["observed_llm_planned_slots"])
            with self.assertRaises(ValueError): compare(left, right, axis="provider")
            bad_control = deepcopy(left)
            bad_control["frames"][1]["calls_today"] = 1
            with self.assertRaises(ValueError): compare(bad_control, right, axis="provider", allow_api=True)
            changed = deepcopy(right)
            changed["mode"] = "participant"
            with self.assertRaises(ValueError): compare(left, changed, axis="provider", allow_api=True)
            provider.secret_forget()


if __name__ == "__main__": unittest.main()
