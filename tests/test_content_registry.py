from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simulation.systems import ContentRegistry, ContentSource, ContentValidationError


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class ContentRegistryTests(unittest.TestCase):
    def test_default_registry_loads_one_canonical_view(self):
        registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        self.assertEqual(36, len(registry.ids("item")))
        self.assertEqual(36, len(registry.ids("item_use")))
        self.assertEqual(8, len(registry.ids("college")))
        self.assertEqual(56, len(registry.ids("campus_ability")))
        self.assertEqual(12, len(registry.ids("club")))
        self.assertEqual(12, len(registry.ids("schedule_template")))
        self.assertEqual(33, len(registry.ids("campus_activity")))
        self.assertEqual(8, len(registry.ids("enemy_archetype")))
        self.assertEqual(5, len(registry.ids("shop")))
        self.assertEqual(21, len(registry.ids("location")))
        self.assertEqual(10, len(registry.ids("campus_region")))
        self.assertEqual(53, len(registry.ids("campus_location")))
        self.assertEqual(16, len(registry.ids("interior_template")))
        self.assertIn("campus_population", registry.ids("configuration"))
        self.assertIn("action_economy", registry.ids("configuration"))
        self.assertIn("campus_decisions", registry.ids("configuration"))
        self.assertIn("party_policy", registry.ids("configuration"))

    def test_content_version_is_reproducible_and_manifest_is_portable(self):
        first = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        second = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        self.assertEqual(first.content_version, second.content_version)
        self.assertEqual(16, len(first.content_version))
        self.assertTrue(all(not Path(path).is_absolute() for path in first.manifest))
        self.assertTrue(all(record["schema_version"] == 1 for record in first.manifest.values()))

    def test_callers_receive_defensive_copies(self):
        registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        item = registry.get("item", "bread_loaf")
        item["name"] = "mutated"
        self.assertEqual("黑麦面包", registry.get("item", "bread_loaf")["name"])

    def test_duplicate_identifier_is_rejected(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "one.json").write_text(
            json.dumps({"schema_version": 1, "entries": [{"id": "same"}, {"id": "same"}]}),
            encoding="utf-8",
        )
        registry = ContentRegistry(root)
        with self.assertRaisesRegex(ContentValidationError, "duplicate test id"):
            registry.load([ContentSource("one.json", "test", "entries")])

    def test_paths_cannot_escape_content_root(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        registry = ContentRegistry(Path(temporary.name))
        with self.assertRaisesRegex(ContentValidationError, "stay below"):
            registry.load([ContentSource("../outside.json", "test", "entries")])

    def test_unknown_cross_reference_is_rejected(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        documents = {
            "items.json": {"schema_version": 1, "items": [{"id": "known"}]},
            "uses.json": {"schema_version": 1, "uses": [{"item_id": "missing"}]},
        }
        for name, payload in documents.items():
            (root / name).write_text(json.dumps(payload), encoding="utf-8")
        registry = ContentRegistry(root)
        registry.load([
            ContentSource("items.json", "item", "items"),
            ContentSource("uses.json", "item_use", "uses", id_field="item_id"),
        ])
        with self.assertRaisesRegex(ContentValidationError, "unknown item"):
            registry.validate_references()


if __name__ == "__main__":
    unittest.main()
