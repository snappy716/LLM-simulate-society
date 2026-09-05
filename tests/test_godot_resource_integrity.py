"""Resource boundaries after retiring the town-only Godot client."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / "game"
RETIRED_FILES = [
    "game/scenes/debug/integration_test.tscn",
    "game/scenes/world/test_world.tscn",
    "game/scenes/ui/simulation_ui.tscn",
    "game/scripts/simulation/simulation_population.gd",
    "game/scripts/simulation/simulation_population.gd.uid",
    "game/scripts/ui/simulation_ui.gd",
    "game/scripts/ui/simulation_ui.gd.uid",
    "game/scripts/ui/world_map_ui.gd",
    "game/scripts/ui/world_map_ui.gd.uid",
    "game/scripts/world/isometric_tile_chunk.gd",
    "game/scripts/world/isometric_tile_chunk.gd.uid",
    "game/scripts/world/isometric_graybox.gd.uid",
    "game/scripts/world/npc_spawner.gd",
    "game/scripts/world/npc_spawner.gd.uid",
    "game/tools/capture_runtime_map.gd.uid",
    "game/tools/convert_tinggen_to_400x400_blueprint.gd",
    "game/tools/convert_tinggen_to_400x400_blueprint.gd.uid",
    "game/tools/convert_tinggen_to_400x400_blueprint.tscn",
    "game/tools/generate_central_square_blueprints.gd",
    "game/tools/generate_central_square_blueprints.gd.uid",
    "game/tools/generate_full_city_orthographic_blueprint.gd",
    "game/tools/generate_full_city_orthographic_blueprint.gd.uid",
    "game/assets/maps/tilesets/blueprint_tiles_64x32.svg",
    "game/assets/maps/tilesets/temporary_ground_64x32.svg",
    "game/data/maps/tinggen_city_overrides.json",
    "game/data/simulation/scene_regions.json",
    "game/assets/maps/blueprints/tinggen_no_icons_400x400_grid_preview_v2.png",
    "game/assets/maps/blueprints/tinggen_no_icons_400x400_logical_blueprint_v2.png",
    "game/assets/maps/road_layers/yanhen_road_network.png",
    "game/data/maps/tinggen_city_layout.png"
]


class GodotResourceIntegrityTests(unittest.TestCase):
    def test_retired_town_resources_are_absent(self):
        for name in RETIRED_FILES:
            with self.subTest(path=name):
                self.assertFalse((ROOT / name).exists())

    def test_literal_resource_references_resolve(self):
        # Dynamic formatted paths are validated by their catalog tests.
        paths = [GAME / "project.godot"]
        for directory in ("scenes", "scripts", "tools"):
            paths.extend(p for p in (GAME / directory).rglob("*")
                         if p.suffix in (".gd", ".tscn", ".tres"))
        checked = 0
        for path in paths:
            source = path.read_text(encoding="utf-8")
            for reference in re.findall(r'["\x27]\*?res://([^"\x27]+)["\x27]', source):
                if any(token in reference for token in ("%", "{", "*")):
                    continue
                with self.subTest(source=str(path.relative_to(GAME)), reference=reference):
                    checked += 1
                    self.assertTrue((GAME / reference).exists(), "dangling Godot resource")
        self.assertGreater(checked, 50, "resource scan must not silently match nothing")

    def test_client_only_exposes_campus_actions(self):
        source = (GAME / "scripts/simulation/simulation_bridge.gd").read_text(encoding="utf-8")
        for method in ("advance_time", "trade", "use_item", "perform_action"):
            self.assertNotIn("func " + method + "(", source)
        for endpoint in ("/snapshot", "/step", "/trade", "/use-item", "/action"):
            self.assertNotIn('"' + endpoint + '"', source)
        for active in ("campus_snapshot_updated", "operate_campus_inventory",
                       "operate_campus_combat", "configure_interface", "campus_persistence"):
            self.assertIn(active, source)

    def test_campus_art_and_reusable_character_components_remain(self):
        self.assertEqual(
            {"campus_gate", "east_dormitory", "west_dormitory", "library",
             "living_area", "psychology_bridge", "sports_field"},
            {p.stem for p in (GAME / "assets/maps/campus_collab").glob("*.png")},
        )
        for name in ("scripts/npc/npc_controller.gd", "scripts/characters/modular_character.gd",
                     "scenes/characters/npc.tscn", "scenes/characters/player.tscn",
                     "scenes/ui/interface_settings_ui.tscn"):
            self.assertTrue((GAME / name).is_file())
        self.assertIsInstance(json.loads((GAME / "data/appearance_catalog.json").read_text()), dict)


if __name__ == "__main__":
    unittest.main()
