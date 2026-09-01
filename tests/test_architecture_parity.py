from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from simulation import runtime as current
from simulation.api.server import SimulationBridge
from simulation.persistence import migrate_snapshot


REPOSITORY_DIR = Path(__file__).resolve().parents[1]
LEGACY_DIR = REPOSITORY_DIR / "emergent_town_demo"


def load_legacy_runtime():
    sys.path.insert(0, str(LEGACY_DIR))
    spec = importlib.util.spec_from_file_location(
        "legacy_town_demo", LEGACY_DIR / "town_demo.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ArchitectureParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy = load_legacy_runtime()

    def _worlds(self, seed=42):
        legacy_dir = tempfile.TemporaryDirectory()
        current_dir = tempfile.TemporaryDirectory()
        self.addCleanup(legacy_dir.cleanup)
        self.addCleanup(current_dir.cleanup)
        legacy_world = self.legacy.World(
            self.legacy.Config(seed=seed, core_npcs=20, simple_npcs=30, llm_mode="rule", log_dir=legacy_dir.name, verbose=False)
        )
        current_world = current.World(
            current.Config(seed=seed, core_npcs=20, simple_npcs=30, llm_mode="rule", log_dir=current_dir.name, verbose=False)
        )
        return legacy_world, current_world

    def test_initial_world_matches_legacy(self):
        legacy_world, current_world = self._worlds()
        self.assertEqual(
            {key: asdict(value) for key, value in legacy_world.scenes.items()},
            {key: asdict(value) for key, value in current_world.scenes.items()},
        )
        fields = (
            "id", "name", "tier", "occupation", "home_scene", "work_scene",
            "personality", "needs", "emotions", "abilities", "organization",
            "work_days", "work_phases", "special_needs", "skills", "layer",
            "sequence_pathway", "sequence_rank", "faction_ids", "duties",
            "current_scene", "goals", "wealth", "sanity", "health",
        )
        for npc_id in legacy_world.npcs:
            before = legacy_world.npcs[npc_id]
            after = current_world.npcs[npc_id]
            self.assertEqual(
                {field: getattr(before, field) for field in fields},
                {field: getattr(after, field) for field in fields},
                npc_id,
            )
        legacy_actions = set(legacy_world.action_registry.ids())
        current_actions = set(current_world.action_registry.ids())
        self.assertTrue(legacy_actions.issubset(current_actions))
        self.assertEqual({"BUY_ITEM", "SELL_ITEM", "TRADE_WITH_NPC", "USE_ITEM",
                          "GIVE_ITEM","DROP_ITEM","PICK_UP_ITEM",
                          "EQUIP_ITEM","UNEQUIP_ITEM","PICK_LOCK",
                          "FORCE_OPEN","UNLOCK_WITH_KEY","CLIMB_WITH_ROPE",
                          "TRAVERSE_PASSAGE","PRESENT_IDENTITY","RECORD_INTELLIGENCE",
                          "THREATEN_WITH_WEAPON","PERFORM_LEGAL_RITUAL"},
                         current_actions - legacy_actions)

    def test_rule_plans_match_legacy(self):
        legacy_world, current_world = self._worlds(seed=7)
        for npc_id in legacy_world.npcs:
            before = self.legacy.rule_plan_for_npc(legacy_world, legacy_world.npcs[npc_id])
            after = current.rule_plan_for_npc(current_world, current_world.npcs[npc_id])
            for phase in before:
                if asdict(before[phase]) == asdict(after[phase]):
                    continue
                # The only intentional planner divergence is proactive food
                # shopping at moderate satiety; all other legacy plans remain equal.
                npc=current_world.npcs[npc_id]
                self.assertLess(npc.states.get("satiety",70),60,npc_id)
                self.assertEqual("SHOP",after[phase].behavior,npc_id)
                self.assertIn(after[phase].scene_id,{"market","tavern"},npc_id)

    def test_one_phase_matches_legacy(self):
        legacy_world, current_world = self._worlds(seed=9)
        for world, module in ((legacy_world, self.legacy), (current_world, current)):
            for npc in world.npcs.values():
                npc.daily_plan = module.rule_plan_for_npc(world, npc)
            module.arrange_social_invitations(world, world.day)
            module.simulate_phase(world, module.Phase.MORNING)

        def comparable_events(world):
            return [
                (
                    event.event_type,
                    event.scene_id,
                    event.actor_ids,
                    event.description,
                    event.severity,
                    event.tags,
                )
                for event in world.events_by_day[1]
            ]

        self.assertEqual(comparable_events(legacy_world), comparable_events(current_world))
        for npc_id in legacy_world.npcs:
            before = legacy_world.npcs[npc_id]
            after = current_world.npcs[npc_id]
            self.assertEqual(
                (before.current_scene, before.wealth, before.health, before.states),
                (after.current_scene, after.wealth, after.health, after.states),
                npc_id,
            )

    def test_api_snapshot_contract_shape(self):
        output_dir = tempfile.TemporaryDirectory()
        self.addCleanup(output_dir.cleanup)
        bridge = SimulationBridge(Path(output_dir.name))
        snapshot = bridge.snapshot()
        schema = json.loads(
            (REPOSITORY_DIR / "contracts" / "world_snapshot.schema.json").read_text(encoding="utf-8")
        )
        self.assertTrue(set(schema["required"]).issubset(snapshot))
        self.assertEqual(2, snapshot["schema_version"])
        self.assertEqual(200, len(snapshot["npcs"]))
        self.assertNotIn("home_001", snapshot["scenes"])
        updated = bridge.step()
        self.assertEqual("afternoon", updated["phase"])
        self.assertEqual(snapshot["revision"] + 1, updated["revision"])

    def test_contract_files_are_valid_json_schemas(self):
        for path in sorted((REPOSITORY_DIR / "contracts").glob("*.schema.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
            self.assertEqual("object", schema["type"])

    def test_snapshot_migration_rejects_unknown_versions(self):
        payload = {"schema_version": 1, "day": 1}
        migrated = migrate_snapshot(payload)
        self.assertEqual(2,migrated["schema_version"])
        self.assertEqual({},migrated["item_instances"])
        self.assertEqual({},migrated["scene_inventories"])
        self.assertEqual({},migrated["container_inventories"])
        self.assertIsNot(payload, migrated)
        with self.assertRaises(ValueError):
            migrate_snapshot({"schema_version": 999})


if __name__ == "__main__":
    unittest.main()
