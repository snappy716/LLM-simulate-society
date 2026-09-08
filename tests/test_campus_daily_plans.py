"""Daily deliberation, intraday execution and replay without paid API calls."""
import json
import unittest
import tempfile
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch

from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_daily_plans import daily_plans_invariant
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from tests.test_campus_cognition import LastLegalProvider, command
from tests import test_world_kernel as kernel_fixture


class CampusDailyPlansTests(unittest.TestCase):
    def test_intraday_runs_without_model_and_morning_selects_full_day(self):
        bridge = CampusKernelBridge(42)
        provider = LastLegalProvider()
        bridge.cognition_runtime.provider = provider
        for _ in range(3):
            self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        self.assertEqual([], provider.requests)
        self.assertEqual([], provider.dialogue_requests)
        old_plans = deepcopy(bridge.kernel.state.cognition["daily_plans"])
        self.assertEqual(1, old_plans["day"])
        self.assertEqual(200, len(old_plans["actors"]))
        morning = command(bridge, "ADVANCE_PHASE")
        self.assertTrue(morning["ok"])
        day_requests = [request for request in provider.requests
                        if request.daily_options is not None]
        self.assertEqual(20, len(day_requests))
        self.assertEqual(len(day_requests), len({request.npc_id for request in day_requests}))
        for request in day_requests:
            self.assertEqual({"morning", "afternoon", "evening", "late_night"}, set(request.daily_options))
        planned = deepcopy(bridge.kernel.state.cognition["daily_plans"])
        self.assertEqual(2, planned["day"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planned-day.json"
            saved_state, saved_rng = bridge.kernel.capture_checkpoint()
            save_kernel_checkpoint(path, saved_state, saved_rng)
            loaded = load_kernel_checkpoint(path)
        restored = CampusKernelBridge(42)
        restored.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=restored.kernel.state.revision)
        restored_provider = LastLegalProvider()
        restored.cognition_runtime.provider = restored_provider
        self.assertTrue(command(restored, "ADVANCE_PHASE")["ok"])
        self.assertEqual([], restored_provider.requests)
        self.assertEqual(planned, restored.kernel.state.cognition["daily_plans"])
        count = (len(provider.requests), len(provider.dialogue_requests))
        with patch("simulation.systems.campus_daily_plans.rank_campus_npc_activities", side_effect=AssertionError("intraday replan")):
            afternoon = command(bridge, "ADVANCE_PHASE")
        self.assertTrue(afternoon["ok"])
        state = bridge.kernel.state
        self.assertEqual(count, (len(provider.requests), len(provider.dialogue_requests)))
        self.assertEqual(planned, state.cognition["daily_plans"])
        self.assertEqual([], list(daily_plans_invariant(state)))
        self.assertTrue(any(event["event_type"] == "NPC_ACTIVITY_COMPLETED" for event in afternoon["result"]["events"]))

    def test_legacy_missing_plan_bootstraps_offline_and_bad_plan_is_rejected(self):
        bridge = CampusKernelBridge(8)
        bridge.kernel._state.clock.phase = "evening"
        provider = LastLegalProvider()
        bridge.cognition_runtime.provider = provider
        self.assertTrue(command(bridge, "ADVANCE_PHASE")["ok"])
        self.assertEqual([], provider.requests)
        state = bridge.kernel.state
        actor_id = next(iter(state.cognition["daily_plans"]["actors"]))
        state.cognition["daily_plans"]["actors"][actor_id]["morning"]["location_id"] = "invented"
        self.assertIn("invalid daily plan clock/location", list(daily_plans_invariant(state)))

    def test_compact_cache_is_detached_and_legacy_cache_replays(self):
        kernel = kernel_fixture.WorldKernelTests().make_kernel()
        request = kernel_fixture.command("compact")
        first = kernel.execute(request)
        cache = kernel.state.processed_commands["compact"]
        self.assertIsInstance(cache["result_json"], str)
        first.events[0].payload["amount"] = 999
        self.assertEqual(3, kernel.execute(request).events[0].payload["amount"])
        legacy = kernel.state
        entry = legacy.processed_commands["compact"]
        entry["result"] = json.loads(entry.pop("result_json"))
        kernel.restore_checkpoint(legacy, kernel._rng, expected_revision=kernel.state.revision)
        replay = kernel.execute(request)
        self.assertTrue(replay.replayed)
        self.assertEqual(3, replay.events[0].payload["amount"])
        self.assertEqual(13, kernel.state.inventories["player"]["money"])
