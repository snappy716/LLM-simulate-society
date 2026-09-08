"""Explicit relationship/provider fixtures: no paid network requests."""
import json
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from dataclasses import asdict

from simulation.api.server import CampusKernelBridge
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems.campus_cognition import cognition_invariant
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint, CheckpointError
from tests.test_campus_cognition import LastLegalProvider, command
from tests.test_player_npc_dialogue import talk


class FriendFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.baseline, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel._state = self.baseline.clone()
        self.bridge.kernel._rng = self.rng.clone()
        self.bridge.cognition_runtime.configure_rule()
        self.state = self.bridge.kernel._state
        self.npc = next(n for n in self.state.population if n != "player" and n not in self.state.cognition["focused_ids"])

    def befriend(self, **values):
        self.state = self.bridge.kernel._state
        # Test fixture simulates a new relationship revision, not a replay of an
        # already rejected command ID at the same revision.
        self.state.revision += 1
        self.state.relationships[self.npc]["player"] = {**DEFAULT_RELATIONSHIP, "closeness": 45, "trust": 45, "conflict": 40, **values}

    def test_relationship_threshold_is_authoritative_and_free(self):
        base = list(self.state.cognition["base_focused_ids"])
        before = deepcopy(self.state.action_economy)
        for values in ({"closeness": 44}, {"trust": 44}, {"conflict": 41}):
            self.befriend(**values)
            revision = self.bridge.snapshot()["revision"]
            result = command(self.bridge, "AWAKEN_NPC", target_id=self.npc)
            self.assertFalse(result["ok"])
            self.assertEqual(revision, result["snapshot"]["revision"])
            self.assertFalse(result["snapshot"]["population"][self.npc]["friend_focus"]["eligible"])
        self.befriend()
        result = command(self.bridge, "AWAKEN_NPC", target_id=self.npc)
        self.assertTrue(result["ok"])
        self.assertEqual(21, result["snapshot"]["cognition"]["focused_count"])
        self.assertEqual(before, self.bridge.kernel.state.action_economy)
        self.assertEqual(base, self.bridge.kernel.state.cognition["base_focused_ids"])
        self.assertTrue(command(self.bridge, "AWAKEN_NPC", target_id=self.npc)["ok"])
        self.assertEqual(21, self.bridge.snapshot()["cognition"]["focused_count"])

    def test_base_npc_cannot_be_double_counted_and_friends_are_not_reranked_out(self):
        base = list(self.state.cognition["base_focused_ids"])
        self.assertFalse(command(self.bridge, "AWAKEN_NPC", target_id=base[0])["ok"])
        self.befriend()
        self.assertTrue(command(self.bridge, "AWAKEN_NPC", target_id=self.npc)["ok"])
        self.bridge.kernel._state.relationships[self.npc]["player"]["closeness"] = 0
        provider = LastLegalProvider()
        self.bridge.cognition_runtime.provider = provider
        for _ in range(3):
            self.assertTrue(command(self.bridge, "ADVANCE_PHASE")["ok"])
        self.assertEqual([], provider.requests)
        self.assertTrue(command(self.bridge, "ADVANCE_PHASE")["ok"])
        day_requests = [r for r in provider.requests if r.daily_options is not None]
        self.assertEqual(set(base) | {self.npc}, {r.npc_id for r in day_requests})
        self.assertEqual(21, len(day_requests))
        self.assertEqual(0, self.bridge.kernel.state.cognition["usage"]["budget_blocks"])
        self.assertEqual(base, self.bridge.kernel.state.cognition["base_focused_ids"])
        count = len(provider.requests)
        self.assertTrue(command(self.bridge, "ADVANCE_PHASE")["ok"])
        self.assertEqual(count, len(provider.requests))

    def test_ordinary_npc_can_chat_many_times_without_becoming_deep(self):
        self.state.population["player"]["current_location_id"] = self.state.population[self.npc]["current_location_id"]
        provider = LastLegalProvider()
        self.bridge.cognition_runtime.provider = provider
        self.state.cognition["usage"].update(automated_calls=10000, automated_estimated_tokens=100000000)
        before = asdict(self.state.clock)
        for i in range(15):
            result = talk(self.bridge, self.npc, "你好，今天怎么样？", i)
            self.assertTrue(result["ok"])
            self.assertEqual("llm", result["result"]["payload"]["wording_source"])
        self.assertEqual(15, len(provider.dialogue_requests))
        self.assertEqual(20, self.bridge.snapshot()["cognition"]["focused_count"])
        self.assertNotIn(self.npc, self.bridge.kernel.state.cognition["focused_ids"])
        self.assertEqual(before, self.bridge.snapshot()["clock"])

    def test_legacy_save_preserves_awakened_memories_rng_and_existing_day_plan(self):
        legacy = self.state.clone()
        old_spec = json.loads(Path("simulation/persistence/campus_friend_content.json").read_text())
        legacy.content_version = old_spec["source_version"]
        old_ids = list(legacy.cognition["focused_ids"])
        legacy.cognition["awakened_ids"] = old_ids[:2]
        legacy.cognition.pop("base_focused_ids")
        legacy.cognition["schema_version"] = 1
        legacy.cognition["policy"]["player_awakened_slots"] = 6
        legacy.cognition["policy"].pop("enforce_automated_budgets")
        old_clock = asdict(legacy.clock)
        old_inventory = deepcopy(legacy.inventories)
        old_memories = deepcopy(legacy.cognition["memory_by_actor"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.json"
            save_kernel_checkpoint(path, legacy, self.rng, content_manifest=old_spec["source_manifest"])
            original = path.read_bytes()
            loaded = load_kernel_checkpoint(path, expected_content_version=self.bridge.registry.content_version)
            self.assertEqual(original, path.read_bytes())
            migrated = Path(folder) / "migrated.json"
            save_kernel_checkpoint(migrated, loaded.state, loaded.rng, content_manifest=loaded.content_manifest)
            again = load_kernel_checkpoint(migrated, expected_content_version=self.bridge.registry.content_version)
        self.assertEqual(old_ids[:2], loaded.state.cognition["awakened_ids"])
        self.assertEqual(22, len(loaded.state.cognition["focused_ids"]))
        self.assertEqual(old_clock, asdict(loaded.state.clock))
        self.assertEqual(old_inventory, loaded.state.inventories)
        self.assertEqual(old_memories, loaded.state.cognition["memory_by_actor"])
        self.assertEqual(self.rng.snapshot(), loaded.rng.snapshot())
        self.assertEqual([], list(cognition_invariant(loaded.state)))
        self.assertEqual(loaded.state.to_dict(), again.state.to_dict())
        self.assertFalse(loaded.state.cognition["policy"]["enforce_automated_budgets"])

    def test_one_request_composes_different_slots_and_rejects_missing_or_foreign_ids(self):
        actor = self.state.cognition["focused_ids"][0]
        options = {phase: [{"candidate_id": f"goal:test:{phase}:{i}", "activity_id": "REST", "location_id": "south_gate_region",
                           "parameters": {"server_owned": i}} for i in range(3)]
                   for phase in ("morning", "afternoon", "evening", "late_night")}
        class MixedProvider(LastLegalProvider):
            def decide(self, request, **kwargs):
                response = super().decide(request, **kwargs)
                response["daily_choices"]["morning"] = "morning:0"
                return response
        provider = MixedProvider()
        self.bridge.cognition_runtime.provider = provider
        selected = self.bridge.cognition_runtime.plan_day(self.state, actor, options)
        self.assertEqual(1, len(provider.requests))
        self.assertEqual(0, selected["morning"]["parameters"]["server_owned"])
        self.assertEqual("goal:test:morning:0", selected["morning"]["candidate_id"])
        self.assertEqual(2, selected["evening"]["parameters"]["server_owned"])
        for bad in ({"morning": "morning:0"}, {p: "morning:0" for p in options}):
            class BadProvider(LastLegalProvider):
                def decide(self, request, **kwargs):
                    response = super().decide(request, **kwargs)
                    response["daily_choices"] = bad
                    return response
            self.state.cognition["decision_cache"].clear()
            self.state.cognition["decision_cache_order"].clear()
            self.bridge.cognition_runtime.provider = BadProvider()
            self.assertIsNone(self.bridge.cognition_runtime.plan_day(self.state, actor, options))


if __name__ == "__main__":
    unittest.main()
