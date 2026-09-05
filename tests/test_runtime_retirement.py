"""Retirement is explicit: production imports must not recreate the old town."""
import importlib
import pkgutil
import unittest
from pathlib import Path

import simulation
from simulation.domain.entities import PHASES, Phase
from simulation.systems.content_registry import ContentRegistry

ROOT = Path(__file__).resolve().parents[1]
RETIRED = [
    "simulation/actions/catalog.py",
    "simulation/actions/registry.py",
    "simulation/api/legacy_bridge.py",
    "simulation/cognition/contracts.py",
    "simulation/cognition/dialogue.py",
    "simulation/cognition/memory.py",
    "simulation/cognition/observation.py",
    "simulation/cognition/planning.py",
    "simulation/cognition/reflection.py",
    "simulation/domain/interactions.py",
    "simulation/domain/item_use.py",
    "simulation/domain/planning.py",
    "simulation/narrative/anchors.py",
    "simulation/narrative/consequence_chains.py",
    "simulation/narrative/illegal_ritual.py",
    "simulation/narrative/situations.py",
    "simulation/narrative/stories.py",
    "simulation/persistence/migrations.py",
    "simulation/runtime.py",
    "simulation/systems/action_resolution.py",
    "simulation/systems/desires.py",
    "simulation/systems/economy.py",
    "simulation/systems/equipment.py",
    "simulation/systems/identity.py",
    "simulation/systems/intelligence.py",
    "simulation/systems/item_actions.py",
    "simulation/systems/item_effects.py",
    "simulation/systems/item_instances.py",
    "simulation/systems/items.py",
    "simulation/systems/organizations.py",
    "simulation/systems/passages.py",
    "simulation/systems/population.py",
    "simulation/systems/relationships.py",
    "simulation/systems/rituals.py",
    "simulation/systems/weapons.py",
    "tests/test_environment_action_system.py",
    "tests/test_equipment_effect_system.py",
    "tests/test_identity_item_actions.py",
    "tests/test_incident_response.py",
    "tests/test_inventory_trade_system.py",
    "tests/test_item_instance_system.py",
    "tests/test_item_transfer_actions.py",
    "tests/test_item_use_system.py",
    "tests/test_modular_system.py",
    "tests/test_notebook_intelligence_system.py",
    "tests/test_passage_item_actions.py",
    "tests/test_population_schedule.py",
    "tests/test_ritual_material_system.py",
    "tests/test_special_needs.py",
    "tests/test_story_system.py",
    "tests/test_unified_action_api.py",
    "tests/test_weapon_item_actions.py",
    "content/items/catalog.json",
    "content/items/uses.json",
    "content/items/shops.json",
    "content/items/placements.json",
    "content/locations/passages.json",
    "content/locations/scene_regions.json",
    "content/npcs/generation_rules.json",
    "content/npcs/NPC_ROSTER.csv",
    "content/npcs/NPC_RELATIONSHIPS.csv",
    "contracts/world_snapshot.schema.json",
    "contracts/trade_request.schema.json",
    "contracts/item_use_request.schema.json",
    "contracts/action_request.schema.json"
]


class RuntimeRetirementTests(unittest.TestCase):
    def test_retired_files_are_absent(self):
        for name in RETIRED:
            with self.subTest(path=name):
                self.assertFalse((ROOT / name).exists())

    def test_old_world_constructor_is_no_longer_a_package_api(self):
        self.assertFalse(hasattr(simulation, "World"))
        self.assertFalse(hasattr(simulation, "Config"))
        self.assertIsNone(importlib.util.find_spec("simulation.runtime"))
        self.assertIsNone(importlib.util.find_spec("simulation.api.legacy_bridge"))

    def test_all_remaining_modules_import_without_retired_dependencies(self):
        for module in pkgutil.walk_packages(simulation.__path__, simulation.__name__ + "."):
            with self.subTest(module=module.name):
                importlib.import_module(module.name)

    def test_shared_clock_and_content_identity_survive_retirement(self):
        self.assertEqual(["morning", "afternoon", "evening", "late_night"],
                         [phase.value for phase in PHASES])
        self.assertIs(Phase.MORNING, PHASES[0])
        self.assertEqual("382ffb9aa84a36d0", ContentRegistry.load_default(ROOT / "content").content_version)


if __name__ == "__main__":
    unittest.main()
