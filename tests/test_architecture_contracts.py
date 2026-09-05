"""Active campus architecture and schema boundaries after town retirement."""
import json
import unittest
from pathlib import Path

REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class ArchitectureContractTests(unittest.TestCase):
    def test_retired_source_copies_are_absent_and_campus_entry_remains(self):
        for name in ("emergent_town_demo", "project-a-0.2", "ProjectA-0.21.zip"):
            self.assertFalse((REPOSITORY_DIR / name).exists(), name)
        self.assertTrue((REPOSITORY_DIR / "game/scenes/campus/campus_collab_test.tscn").is_file())
        self.assertTrue((REPOSITORY_DIR / "simulation/api/server.py").is_file())

    def test_contract_files_are_valid_json_schemas(self):
        for path in sorted((REPOSITORY_DIR / "contracts").glob("*.schema.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
            self.assertEqual("object", schema["type"])
