"""Campus content split compatibility, without accepting arbitrary content drift."""
import hashlib
import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.persistence.campus_saves import CampusSaveStore
from simulation.persistence.kernel_checkpoint import (
    CheckpointError, build_kernel_checkpoint, load_kernel_checkpoint, save_kernel_checkpoint,
)
from simulation.persistence.snapshot import atomic_write_json
from simulation.systems.content_registry import ContentRegistry

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "simulation/persistence/campus_content_split.json").read_text())
RETIRED = ("items/catalog.json", "items/uses.json", "items/shops.json",
           "items/placements.json", "locations/passages.json",
           "locations/scene_regions.json", "npcs/generation_rules.json")


class CampusContentSplitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.baseline, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / "slot_1.json"
        self.old = self.baseline.clone()
        self.old.content_version = SPEC["source_version"]
        # Resource differences must survive, rather than being reinitialized.
        self.old.population["player"]["wealth"] = 137
        self.old.inventories["actors"]["player"]["quantities"]["bread_loaf"] = 1
        save_kernel_checkpoint(self.path, self.old, self.rng, content_manifest=SPEC["source_manifest"])

    def load(self):
        return load_kernel_checkpoint(self.path, expected_content_version=SPEC["target_version"])

    def test_source_and_target_manifests_match_frozen_versions(self):
        for side in ("source", "target"):
            digest = hashlib.sha256()
            for name, record in sorted(SPEC[side + "_manifest"].items()):
                digest.update(name.encode())
                digest.update(record["sha256"].encode("ascii"))
            self.assertEqual(SPEC[side + "_version"], digest.hexdigest()[:16])
        current = ContentRegistry.load_default(ROOT / "content")
        self.assertEqual(SPEC["target_version"], current.content_version)
        self.assertEqual(SPEC["target_manifest"], current.manifest)

    def test_campus_boot_content_does_not_need_any_town_document(self):
        content = self.directory / "content"
        shutil.copytree(ROOT / "content", content)
        for name in RETIRED:
            (content / name).unlink()
        registry = ContentRegistry.load_default(content)
        self.assertEqual(SPEC["target_version"], registry.content_version)
        self.assertEqual(SPEC["item_ids"], registry.ids("item"))
        for name in RETIRED:
            self.assertNotIn(name, registry.manifest)

    def test_migration_only_changes_content_identity_not_saved_resources(self):
        disk = self.path.read_bytes()
        loaded = self.load()
        # JSON persists tuples as arrays; compare the actual serialized contract.
        expected = json.loads(json.dumps(self.old.to_dict()))
        expected["content_version"] = SPEC["target_version"]
        self.assertEqual(expected, loaded.state.to_dict())
        self.assertEqual(self.rng.snapshot(), loaded.rng.snapshot())
        self.assertEqual(disk, self.path.read_bytes())
        self.assertEqual((SPEC["migration_id"],), loaded.migrations)
        self.assertEqual(SPEC["target_manifest"], loaded.content_manifest)

    def test_unknown_target_version_is_not_silently_accepted(self):
        with self.assertRaisesRegex(CheckpointError, "content version mismatch"):
            load_kernel_checkpoint(self.path, expected_content_version="unrelated-change")

    def test_unknown_source_or_missing_or_changed_manifest_is_rejected(self):
        variants = [({}, SPEC["source_version"]),
                    (SPEC["source_manifest"], "unknown-old"),
                    ({**SPEC["source_manifest"], "unexpected.json": {"schema_version": 1, "sha256": "x"}}, SPEC["source_version"])]
        for manifest, version in variants:
            with self.subTest(version=version, manifest_size=len(manifest)):
                state = self.old.clone()
                state.content_version = version
                save_kernel_checkpoint(self.path, state, self.rng, content_manifest=manifest)
                with self.assertRaisesRegex(CheckpointError, "content version mismatch"):
                    self.load()

    def test_checksum_is_verified_before_migration(self):
        payload = json.loads(self.path.read_text())
        payload["world"]["population"]["player"]["wealth"] += 100
        atomic_write_json(self.path, payload)
        with self.assertRaisesRegex(CheckpointError, "checksum mismatch"):
            self.load()

    def test_generic_world_with_known_version_is_not_converted_to_campus(self):
        from simulation.domain.world_state import WorldState
        state = WorldState(content_version=SPEC["source_version"], master_seed=self.rng.master_seed)
        save_kernel_checkpoint(self.path, state, self.rng, content_manifest=SPEC["source_manifest"])
        with self.assertRaisesRegex(CheckpointError, "full campus"):
            self.load()

    def test_save_store_returns_migration_then_resave_keeps_original_backup(self):
        store = CampusSaveStore(self.directory)
        original = self.path.read_bytes()
        loaded, changes = store.load("slot_1", backup=False, expected_token=store.token(self.path),
                                     confirmed=True, content_version=SPEC["target_version"])
        self.assertIn(SPEC["migration_id"], changes)
        self.assertEqual(original, self.path.read_bytes())
        store.save("slot_1", loaded.state, loaded.rng, loaded.content_manifest,
                   expected_token=store.token(self.path), confirmed=True)
        backup = load_kernel_checkpoint(store.path("slot_1", True))
        self.assertEqual(json.loads(json.dumps(self.old.to_dict())), backup.state.to_dict())
        native = self.load()
        self.assertEqual((), native.migrations)
        self.assertEqual(137, native.state.population["player"]["wealth"])

    def test_failed_migration_does_not_replace_live_world(self):
        bridge = self.bridge
        before, rng = bridge.kernel.capture_checkpoint()
        invalid = deepcopy(SPEC["source_manifest"])
        invalid.pop(next(iter(invalid)))
        save_kernel_checkpoint(self.path, self.old, self.rng, content_manifest=invalid)
        store = CampusSaveStore(self.directory)
        with self.assertRaises(CheckpointError):
            bridge.persistence(store, {"operation": "load", "slot_id": "slot_1",
                "expected_token": store.token(self.path), "confirmed": True,
                "expected_world_revision": before.revision})
        after, after_rng = bridge.kernel.capture_checkpoint()
        self.assertEqual(before.to_dict(), after.to_dict())
        self.assertEqual(rng.snapshot(), after_rng.snapshot())


if __name__ == "__main__":
    unittest.main()
