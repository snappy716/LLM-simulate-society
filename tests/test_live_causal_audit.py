"""Audit integrity only; mock transport is never evidence of real LLM quality."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from production.live_causal_audit import AuditBudget, CausalProvider, coverage, validate_request_timing


class LiveCausalAuditTests(unittest.TestCase):
    def timing_branch(self):
        return {"requests": [{"day": 4, "phase": "morning", "kind": "plan"}],
            "summary": {"api_calls": 1}, "commands": [{"command": {"action_id": "END_COMBAT_ROUND", "issued_phase": "evening"},
                "request_span": [0, 1], "result": {"success": True, "events": [
                    {"event_type": "WORLD_PHASE_ADVANCED", "payload": {"day": 3, "phase": "late_night"}},
                    {"event_type": "WORLD_PHASE_ADVANCED", "payload": {"day": 4, "phase": "morning"}}]}}]}

    def test_automatic_defeat_overnight_allows_actual_dawn_requests(self):
        validate_request_timing(self.timing_branch())

    def test_intraday_failed_and_unattributed_requests_are_rejected(self):
        for kind in ("no_dawn", "wrong_day", "wrong_phase", "failed", "gap", "overlap", "missing"):
            branch = self.timing_branch()
            if kind == "no_dawn": branch["commands"][0]["result"]["events"].pop()
            if kind == "wrong_day": branch["requests"][0]["day"] = 5
            if kind == "wrong_phase": branch["requests"][0]["phase"] = "afternoon"
            if kind == "failed": branch["commands"][0]["result"]["success"] = False
            if kind == "gap": branch["commands"][0]["request_span"] = [1, 1]
            if kind == "overlap": branch["commands"].append(deepcopy(branch["commands"][0]))
            if kind == "missing": branch["summary"]["api_calls"] = 2
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate_request_timing(branch)

    def test_empty_live_ledger_is_not_success(self):
        with self.assertRaisesRegex(ValueError, "No actual"):
            validate_request_timing({"commands": [], "requests": [], "summary": {"api_calls": 0}})

    def test_budget_is_shared_and_ledger_contains_no_credentials(self):
        class Response(io.BytesIO):
            status = 200
        with tempfile.TemporaryDirectory() as directory:
            budget = AuditBudget(Path(directory), max_requests=1)
            first = CausalProvider("fake-private-test-key", Path(directory)/"first", budget)
            second = CausalProvider("fake-private-test-key", Path(directory)/"second", budget)
            response = Response(json.dumps({"id": "test-response", "model": "test-model",
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]}).encode())
            with patch("urllib.request.urlopen", return_value=response) as transport:
                self.assertTrue(first._complete_json("test", {}, 20)["ok"])
                with self.assertRaises(SystemExit): second._complete_json("test", {}, 20)
                self.assertEqual(1, transport.call_count)
            self.assertEqual(12, budget.report()["tokens"]["total_tokens"])
            self.assertEqual("test-response", first.records[0]["response_id"])
            self.assertIn("started_at", first.records[0])
            self.assertNotIn("fake-private-test-key", (Path(directory)/"usage-ledger.json").read_text())
            self.assertNotIn("fake-private-test-key", (Path(directory)/"first/requests.json").read_text())
            first.secret_forget()
            second.secret_forget()

    def test_reported_token_stop_and_unknown_usage_remain_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            budget = AuditBudget(Path(directory), max_tokens=10)
            provider = CausalProvider("fake-key", Path(directory)/"sample", budget)
            provider.records.extend([{"usage": {"total_tokens": 10}}, {"error": "timeout"}])
            self.assertEqual(1, budget.report()["missing_usage"])
            with self.assertRaises(SystemExit): budget.before_request()

    def test_coverage_does_not_count_future_slots_or_stale_activity(self):
        audit = {"usage": {"calls": 20}, "focused_ids": ["npc"],
            "daily_plans": {"npc": {p: {"day": 4, "planned_source": "llm", "activity_id": "READ", "location_id": "library"}
                for p in ("morning", "afternoon", "evening", "late_night")}},
            "actual_activities": {"npc": {"day": 4, "phase": "morning", "status": "completed", "activity_id": "READ", "location_id": "library"}}}
        branch = {"frames": [{}, {"clock": {"day": 4, "phase": "morning"}, "cognition_audit": audit}]}
        result = coverage(branch)
        self.assertEqual(1, result["observed_llm_planned_slots"])
        self.assertEqual(1, result["matching_activity_and_location"])
        audit["actual_activities"]["npc"]["day"] = 3
        self.assertEqual(0, coverage(branch)["completed_llm_planned_slots"])


if __name__ == "__main__":
    unittest.main()
