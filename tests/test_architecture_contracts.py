"""Active contracts survive retirement of the standalone town source copies.

The three source-to-source town parity tests were retired deliberately with
their comparison target. Campus and still-used compatibility tests remain.
"""
import json
import tempfile
import unittest
from pathlib import Path

from simulation.api.server import SimulationBridge
from simulation.persistence import migrate_snapshot

REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class ArchitectureContractTests(unittest.TestCase):
    def test_retired_source_copies_are_absent_and_campus_entry_remains(self):
        for name in ("emergent_town_demo", "project-a-0.2", "ProjectA-0.21.zip"):
            self.assertFalse((REPOSITORY_DIR / name).exists(), name)
        self.assertTrue((REPOSITORY_DIR / "game/scenes/campus/campus_collab_test.tscn").is_file())
        self.assertTrue((REPOSITORY_DIR / "simulation/api/server.py").is_file())

    def test_api_snapshot_contract_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = SimulationBridge(Path(directory))
            snapshot = bridge.snapshot()
            schema = json.loads((REPOSITORY_DIR / "contracts/world_snapshot.schema.json").read_text(encoding="utf-8"))
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
        self.assertEqual(2, migrated["schema_version"])
        self.assertEqual({}, migrated["item_instances"])
        self.assertEqual({}, migrated["scene_inventories"])
        self.assertEqual({}, migrated["container_inventories"])
        self.assertIsNot(payload, migrated)
        with self.assertRaises(ValueError):
            migrate_snapshot({"schema_version": 999})
