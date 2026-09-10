"""Parallel transport must preserve serial worlds, RNG, privacy and billing."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import io
import json
import threading
import time
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from simulation.api.server import CampusKernelBridge
from simulation.cognition.provider import ProviderFailure
from simulation.persistence.kernel_checkpoint import build_kernel_checkpoint
from simulation.systems.daily_plan_jobs import DailyPlanJobs
from tests.test_campus_cognition import LastLegalProvider, command


class ConcurrentProvider(LastLegalProvider):
    def __init__(self, limit, failures=None):
        super().__init__()
        self.max_concurrent_requests = limit
        self.failures = failures or {}
        self.lock = threading.Lock()
        self.active = self.peak = 0

    def decide(self, request, *, max_output_tokens):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            # Different completions: settled order must not follow HTTP order.
            time.sleep(.02 if int(request.npc_id[-1], 36) % 2 else .04)
            result = super().decide(request, max_output_tokens=max_output_tokens)
            failure = self.failures.get(request.npc_id) if request.daily_options else None
            if failure == "timeout":
                raise TimeoutError("synthetic")
            if failure in ("http_429", "output_truncated"):
                raise ProviderFailure(failure, {"prompt_tokens": 11, "completion_tokens": 7})
            if failure == "identity":
                result["npc_id"] = "someone-else"
            if failure == "stale":
                result["candidate_revision"] -= 1
            return result
        finally:
            with self.lock:
                self.active -= 1


def night_bridge(seed=42):
    bridge = CampusKernelBridge(seed)
    for _ in range(3):
        assert command(bridge, "ADVANCE_PHASE")["ok"]
    return bridge


def checkpoint(bridge):
    return build_kernel_checkpoint(*bridge.kernel.capture_checkpoint())


def first_difference(left, right, path="world"):
    if type(left) is not type(right):
        return path + ": different types"
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return path + ": different keys"
        for key in left:
            found = first_difference(left[key], right[key], path + "." + str(key))
            if found:
                return found
    elif isinstance(left, (tuple, list)):
        if len(left) != len(right):
            return path + ": different lengths"
        for index, (a, b) in enumerate(zip(left, right)):
            found = first_difference(a, b, path + "." + str(index))
            if found:
                return found
    elif left != right:
        return f"{path}: {str(left)[:100]} != {str(right)[:100]}"
    return ""


class ParallelDailyPlansTests(unittest.TestCase):
    def setUp(self):
        self.network = patch("urllib.request.urlopen", side_effect=AssertionError("paid network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_parallel_and_serial_multi_day_worlds_rng_requests_and_usage_match(self):
        bridges = [night_bridge(), night_bridge()]
        providers = [ConcurrentProvider(1), ConcurrentProvider(10)]
        for bridge, provider in zip(bridges, providers):
            bridge.cognition_runtime.provider = provider
        for _ in range(5):  # Two overnights and all intervening daytime phases.
            for bridge in bridges:
                self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
            self.assertEqual("", first_difference(checkpoint(bridges[0]), checkpoint(bridges[1])))
        self.assertEqual(1, providers[0].peak)
        self.assertGreater(providers[1].peak, 1)
        self.assertLessEqual(providers[1].peak, 10)
        requests = lambda p: sorted(json.dumps(r.to_dict(), sort_keys=True) for r in p.requests)
        self.assertEqual(requests(providers[0]), requests(providers[1]))
        self.assertEqual(40, sum(r.daily_options is not None for r in providers[1].requests))

    def test_partial_failure_billing_and_fallbacks_identical_without_retries(self):
        bridges = [night_bridge(8), night_bridge(8)]
        failures = dict(zip(bridges[0].kernel.state.cognition["focused_ids"],
                            ("timeout", "http_429", "output_truncated", "identity", "stale")))
        for bridge, limit in zip(bridges, (1, 10)):
            provider = ConcurrentProvider(limit, failures)
            bridge.cognition_runtime.provider = provider
            self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
            self.assertEqual(20, sum(r.daily_options is not None for r in provider.requests))
        self.assertEqual("", first_difference(checkpoint(bridges[0]), checkpoint(bridges[1])))
        usage = bridges[1].kernel.state.cognition["usage"]
        self.assertEqual(3, usage["provider_errors"])
        self.assertEqual(2, usage["rejected_responses"])
        self.assertEqual(5, usage["fallbacks"])

    def test_additional_friends_get_full_plans_and_daytime_never_replans(self):
        bridge = night_bridge()
        state = bridge.kernel.state
        base = state.cognition["focused_ids"]
        extras = [n for n in sorted(state.population) if n != "player" and n not in base][:3]
        state.cognition["focused_ids"].extend(extras)
        state.cognition["awakened_ids"].extend(extras)
        bridge.kernel._state = state
        provider = ConcurrentProvider(6)
        bridge.cognition_runtime.provider = provider
        self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        self.assertEqual(23, sum(r.daily_options is not None for r in provider.requests))
        count = len(provider.requests)
        self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        self.assertEqual(count, len(provider.requests))
        self.assertLessEqual(provider.peak, 6)

    def test_usage_reservations_cache_and_validation_run_on_world_thread(self):
        bridge = night_bridge()
        provider = ConcurrentProvider(10)
        bridge.cognition_runtime.provider = provider
        from simulation.systems import campus_cognition
        original = campus_cognition.bind_cognition_identity
        owner = threading.get_ident()
        def bound(*args):
            self.assertEqual(owner, threading.get_ident())
            return original(*args)
        with patch.object(campus_cognition, "bind_cognition_identity", side_effect=bound):
            self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        # Same bounded activity request: second selection is a local cache hit.
        runtime, state = bridge.cognition_runtime, bridge.kernel.state
        request = runtime._request(state, state.cognition["focused_ids"][0],
            [{"candidate_id": "stay", "activity_id": "REST", "location_id": "library_reading_hall", "decision_reason": "rest"}])
        first = runtime._select_response(state, request, purpose="activity")
        count = len(provider.requests)
        second = runtime._select_response(state, request, purpose="activity")
        self.assertEqual(first, second)
        self.assertEqual(count, len(provider.requests))
        self.assertEqual(1, state.cognition["usage"]["cache_hits"])

    def test_opt_in_automated_budget_cannot_be_oversubscribed_by_workers(self):
        bridge = night_bridge()
        runtime = bridge.cognition_runtime
        runtime.policy = replace(runtime.policy, enforce_automated_budgets=True, daily_call_limit=3)
        runtime.provider = ConcurrentProvider(10)
        self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        self.assertLessEqual(len(runtime.provider.requests), 3)
        self.assertGreater(bridge.kernel.state.cognition["usage"]["budget_blocks"], 0)

    def test_parent_capacity_boundary_waits_before_next_candidate_is_built(self):
        graph = SimpleNamespace(locations={
            "building": SimpleNamespace(parent_id="region", capacity=1),
            "a": SimpleNamespace(parent_id="building", capacity=100),
            "b": SimpleNamespace(parent_id="building", capacity=100)})
        occupancy = {"morning": Counter()}
        completed = []
        from simulation.systems.campus_decisions import reserve_decision_destination, _has_capacity
        def apply(actor, slots, options):
            completed.append(actor)
            reserve_decision_destination(graph, occupancy["morning"], slots["morning"]["location_id"])
        def flow():
            yield SimpleNamespace(run=lambda: (None, None, None, 0.0))
            return {"morning": {"location_id": "a"}}
        with DailyPlanJobs(graph, occupancy, 10, apply) as jobs:
            jobs.submit("first", flow(), {"morning": [{"location_id": "a"}, {"location_id": "b"}]})
            jobs.before_actor()
            self.assertEqual(["first"], completed)
            self.assertFalse(_has_capacity(graph, occupancy["morning"], "b"))
        self.assertEqual(1, jobs.metrics["capacity_barriers"])

    def test_real_adapter_parallel_wire_usage_and_diagnostics_are_isolated(self):
        bridge = night_bridge()
        bridge.configure_cognition_interface({"provider": "openai_compatible", "base_url": "https://test.invalid",
            "model": "test", "api_key": "synthetic-test-secret", "max_concurrent_requests": 5})
        lock, active, peak, calls = threading.Lock(), 0, 0, []
        from simulation.cognition.prompt_compaction import expand_option_payload
        def response(http_request, **kwargs):
            nonlocal active, peak
            body = json.loads(http_request.data)
            request = expand_option_payload(json.loads(body["messages"][1]["content"]))
            with lock:
                active += 1
                peak = max(peak, active)
                calls.append(request)
            time.sleep(.03)
            answer = {"npc_id": request["npc_id"], "candidate_revision": request["candidate_revision"],
                      "reason": "选择可行安排", "selected_action_id": None}
            if request.get("daily_options") is not None:
                answer["daily_choices"] = {phase: rows[-1]["candidate_id"] for phase, rows in request["daily_options"].items()}
            elif "target_id" in request:
                answer.update(target_id=request["target_id"], utterance="我会按约定安排。", fact_ids_used=[])
            else:
                answer["selected_action_id"] = request["candidates"][-1]["candidate_id"]
            with lock:
                active -= 1
            return io.BytesIO(json.dumps({"model": "test-actual", "choices": [{"finish_reason": "stop",
                "message": {"content": json.dumps(answer)}}], "usage": {"prompt_tokens": 31, "completion_tokens": 13}}).encode())
        with patch("urllib.request.urlopen", side_effect=response):
            self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 5)
        usage = bridge.kernel.state.cognition["usage"]
        self.assertEqual(len(calls) * 31, usage["prompt_tokens"])
        self.assertEqual(len(calls) * 13, usage["completion_tokens"])
        self.assertEqual(0, usage["fallbacks"])
        self.assertNotIn("synthetic-test-secret", json.dumps(bridge.snapshot()))
        self.assertEqual("test-actual", bridge.cognition_runtime.public_status()["last_result"]["actual_model"])

    def test_concurrency_is_optional_validated_and_not_a_player_call_quota(self):
        bridge = CampusKernelBridge(42)
        config = {"provider": "openai_compatible", "base_url": "https://test.invalid", "model": "test", "api_key": "fake"}
        bridge.configure_cognition_interface(config)
        self.assertEqual(10, bridge.cognition_runtime.provider.max_concurrent_requests)
        old = bridge.cognition_runtime.provider
        for invalid in (True, 0, 21, 1.5, "10", None):
            with self.assertRaises(ValueError):
                bridge.configure_cognition_interface({**config, "max_concurrent_requests": invalid})
            self.assertIs(old, bridge.cognition_runtime.provider)
        bridge.configure_cognition_interface({**config, "max_concurrent_requests": 1})
        self.assertEqual(1, bridge.cognition_runtime.provider.max_concurrent_requests)
        self.assertIsNone(bridge.snapshot()["cognition"]["daily_call_limit"])

    def test_duplicate_overnight_command_replays_without_new_requests(self):
        bridge = night_bridge()
        provider = ConcurrentProvider(10)
        bridge.cognition_runtime.provider = provider
        snapshot = bridge.snapshot()
        payload = {"command_id": "parallel-repeat", "actor_id": "player", "action_id": "ADVANCE_PHASE",
            "target_ids": [], "parameters": {}, "expected_world_revision": snapshot["revision"],
            "issued_day": snapshot["clock"]["day"], "issued_phase": snapshot["clock"]["phase"],
            "issued_minute": snapshot["clock"]["minute"], "source": "player"}
        self.assertTrue(bridge.execute(payload)["ok"])
        count = (len(provider.requests), len(provider.dialogue_requests))
        before = checkpoint(bridge)
        self.assertTrue(bridge.execute(payload)["ok"])
        self.assertEqual(count, (len(provider.requests), len(provider.dialogue_requests)))
        self.assertEqual("", first_difference(before, checkpoint(bridge)))

    def test_custom_audit_adapter_remains_serial_and_retains_error_counter(self):
        from production.run_live_cognition_soak import AuditedProvider
        from tests.test_live_cognition_audit import Response
        bridge = CampusKernelBridge(42)
        runtime, state = bridge.cognition_runtime, bridge.kernel.state
        request = runtime._request(state, state.cognition["focused_ids"][0],
            [{"candidate_id": "stay", "activity_id": "REST", "location_id": "library_reading_hall", "decision_reason": "rest"}])
        with tempfile.TemporaryDirectory() as directory:
            provider = AuditedProvider("fake-audit-key", Path(directory), 30, True)
            runtime.provider = provider
            self.assertFalse(provider.parallel_requests_supported)
            def truncated(*args, **kwargs):
                return Response(json.dumps({"choices": [{"finish_reason": "length", "message": {"content": ""}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7}}).encode())
            with patch("urllib.request.urlopen", truncated):
                for expected in (1, 2):
                    self.assertIsNone(runtime._select_response(state, request, purpose="activity"))
                    self.assertEqual(expected, provider.consecutive_errors)
                with self.assertRaises(SystemExit):
                    runtime._select_response(state, request, purpose="activity")
            self.assertEqual([0, 1, 2], [r["index"] for r in provider.records])
            self.assertNotIn("fake-audit-key", (Path(directory) / "requests.json").read_text())

    def test_later_cached_plan_does_not_overtake_inflight_audit_or_call_network(self):
        bridge = CampusKernelBridge(42)
        runtime, state = bridge.cognition_runtime, bridge.kernel.state
        provider = ConcurrentProvider(10)
        runtime.provider = provider
        actors = state.cognition["focused_ids"][:2]
        phases = ("morning", "afternoon", "evening", "late_night")
        options = {phase: [{"candidate_id": phase + ":rest", "activity_id": "REST",
            "location_id": "library_reading_hall", "decision_reason": "rest", "action_class": "free"}]
            for phase in phases}
        runtime.plan_day(state, actors[1], options)
        state.cognition["decision_audit"].clear()
        provider.requests.clear()
        applied = []
        with DailyPlanJobs(bridge.location_graph, {p: Counter() for p in phases}, 10,
                           lambda actor, *_: applied.append(actor)) as jobs:
            for actor in actors:
                jobs.before_actor()
                jobs.submit(actor, runtime.plan_day_flow(state, actor, options), options)
        self.assertEqual(actors, applied)
        self.assertEqual(actors, [row["npc_id"] for row in state.cognition["decision_audit"]])
        self.assertEqual(1, len(provider.requests))
        self.assertEqual(1, jobs.metrics["network_calls"])
        self.assertEqual(1, state.cognition["usage"]["cache_hits"])


if __name__ == "__main__":
    unittest.main()
