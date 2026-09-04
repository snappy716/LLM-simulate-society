from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path


REPOSITORY_DIR = Path(__file__).resolve().parents[1]
GAME_DIR = REPOSITORY_DIR / "game"


class GodotCampusNavigationSourceTests(unittest.TestCase):
    def test_five_latest_collaboration_maps_are_catalogued_with_real_dimensions(self):
        catalog_path = GAME_DIR / "data/campus_art_catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        maps = catalog["maps"]
        self.assertEqual(5, len(maps))
        self.assertEqual(5, len({entry["id"] for entry in maps}))
        self.assertEqual(5, len({entry["texture_path"] for entry in maps}))
        self.assertEqual(
            5,
            len(list((GAME_DIR / "assets/maps/campus_collab").glob("*.png"))),
        )
        for entry in maps:
            self.assertIn(entry["semantic_location_id"], {
                "south_gate_region",
                "student_life_region",
                "east_dorm_region",
                "west_dorm_region",
                "humanities_psychology_region",
            })
            texture_path = entry["texture_path"].removeprefix("res://")
            image_path = GAME_DIR / texture_path
            self.assertTrue(image_path.is_file(), entry["id"])
            with image_path.open("rb") as image:
                self.assertEqual(b"\x89PNG\r\n\x1a\n", image.read(8))
                self.assertEqual(13, struct.unpack(">I", image.read(4))[0])
                self.assertEqual(b"IHDR", image.read(4))
                width, height = struct.unpack(">II", image.read(8))
            self.assertEqual([width, height], entry["map_size"], entry["id"])

    def test_existing_blueprint_tool_has_explicit_boundary_position_type(self):
        generator = (
            GAME_DIR / "tools/generate_full_city_orthographic_blueprint.gd"
        ).read_text(encoding="utf-8")
        self.assertIn("var position: int = MARGIN + int(boundary) * CELL", generator)

    def test_project_registers_navigation_without_replacing_legacy_main_scene(self):
        project = (GAME_DIR / "project.godot").read_text(encoding="utf-8")
        self.assertIn('run/main_scene="res://scenes/debug/integration_test.tscn"', project)
        self.assertIn('CampusNavigation="*res://scripts/world/campus_navigation.gd"', project)

    def test_reusable_trigger_and_anchor_scenes_exist(self):
        trigger = GAME_DIR / "scenes/world/components/campus_transition_trigger.tscn"
        anchor = GAME_DIR / "scenes/world/components/campus_arrival_anchor.tscn"
        self.assertTrue(trigger.is_file())
        self.assertTrue(anchor.is_file())
        self.assertIn("passage_id", (
            GAME_DIR / "scripts/world/campus_transition_trigger.gd"
        ).read_text(encoding="utf-8"))
        self.assertIn("arrival_anchor_id", (
            GAME_DIR / "scripts/world/campus_navigation.gd"
        ).read_text(encoding="utf-8"))

    def test_player_is_identifiable_by_transition_triggers(self):
        player = (GAME_DIR / "scripts/player/player_controller.gd").read_text(encoding="utf-8")
        self.assertIn('add_to_group("player")', player)

    def test_debug_scenes_reuse_player_camera_without_duplicate_child(self):
        outdoors = (GAME_DIR / "scenes/debug/campus_navigation_test.tscn").read_text(
            encoding="utf-8"
        )
        lobby = (GAME_DIR / "scenes/debug/campus_lobby_test.tscn").read_text(
            encoding="utf-8"
        )
        outdoor_script = (
            GAME_DIR / "scripts/world/campus_navigation_graybox.gd"
        ).read_text(encoding="utf-8")
        lobby_script = (GAME_DIR / "scripts/world/campus_lobby_graybox.gd").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('[node name="Camera2D"', outdoors)
        self.assertNotIn('[node name="Camera2D"', lobby)
        self.assertIn('get_node_or_null("Player/Camera2D")', outdoor_script)
        self.assertIn('get_node_or_null("Player/Camera2D")', lobby_script)

    def test_navigation_camera_looks_ahead_toward_boundary_traffic(self):
        script = (GAME_DIR / "scripts/world/campus_navigation_graybox.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn("camera.position = Vector2(0, -180)", script)

    def test_bridge_exposes_authoritative_phase_advance(self):
        bridge = (GAME_DIR / "scripts/simulation/simulation_bridge.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn("signal campus_phase_advanced", bridge)
        self.assertIn("func advance_campus_phase()", bridge)
        self.assertIn('"action_id": "ADVANCE_PHASE"', bridge)

    def test_map_ui_uses_authoritative_free_travel_and_scene_mounts_all_prototypes(self):
        bridge = (GAME_DIR / "scripts/simulation/simulation_bridge.gd").read_text(
            encoding="utf-8"
        )
        map_ui = (GAME_DIR / "scripts/ui/campus_art_map_ui.gd").read_text(
            encoding="utf-8"
        )
        scene = (GAME_DIR / "scenes/campus/campus_collab_test.tscn").read_text(
            encoding="utf-8"
        )
        self.assertIn('"action_id": "FAST_TRAVEL_CAMPUS"', bridge)
        self.assertIn("SimulationBridge.fast_travel_campus(destination_id)", map_ui)
        self.assertNotIn("change_scene_to_file", map_ui)
        for node_name in ("CampusMapUI", "CampusPhoneUI", "CameraControls"):
            self.assertIn(f'name="{node_name}"', scene)
        self.assertIn("R 随机人物模块", scene)

    def test_collaboration_scene_reuses_current_modular_characters_and_camera(self):
        scene = (GAME_DIR / "scenes/campus/campus_collab_test.tscn").read_text(
            encoding="utf-8"
        )
        controller = (GAME_DIR / "scripts/world/campus_collab_scene.gd").read_text(
            encoding="utf-8"
        )
        player = (GAME_DIR / "scripts/player/player_controller.gd").read_text(
            encoding="utf-8"
        )
        npc_layer = (GAME_DIR / "scripts/world/campus_npc_movement_layer.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn('res://scenes/characters/player.tscn', scene)
        self.assertIn('res://scenes/characters/npc.tscn', scene)
        self.assertIn("AppearanceGenerator.generate", player)
        self.assertIn("npc.world_seed", npc_layer)
        self.assertIn('add_to_group("campus_art_camera")', controller)
        self.assertIn("camera.limit_right = int(_map_size.x)", controller)
        self.assertIn("edge_scroll_speed", controller)

    def test_bridge_port_is_configurable_without_changing_windows_default(self):
        bridge = (GAME_DIR / "scripts/simulation/simulation_bridge.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn('OS.get_environment("GODOT_SIM_PORT")', bridge)
        self.assertIn("var _server_port := 8765", bridge)
        self.assertIn('"--port", str(_server_port)', bridge)

    def test_navigation_graybox_keeps_outdoors_continuous_and_reuses_lobby(self):
        outdoors = (GAME_DIR / "scenes/debug/campus_navigation_test.tscn").read_text(
            encoding="utf-8"
        )
        lobby = (GAME_DIR / "scenes/debug/campus_lobby_test.tscn").read_text(
            encoding="utf-8"
        )
        self.assertIn('passage_id = "road_gate_to_student_life"', outdoors)
        self.assertIn('passage_id = "parent:student_center"', outdoors)
        self.assertIn('anchor_id = "outside:student_center:entrance"', outdoors)
        self.assertIn('anchor_id = "inside:student_center:entrance"', lobby)
        self.assertIn('passage_id = "parent:student_center"', lobby)

    def test_graybox_exposes_coarse_phase_and_major_action_debug_ui(self):
        panel_scene = GAME_DIR / "scenes/ui/campus_phase_debug_panel.tscn"
        panel_script = GAME_DIR / "scripts/ui/campus_phase_debug_panel.gd"
        self.assertTrue(panel_scene.is_file())
        self.assertTrue(panel_script.is_file())
        script = panel_script.read_text(encoding="utf-8")
        scene = panel_scene.read_text(encoding="utf-8")
        self.assertIn("anchor_left = 1.0", scene)
        self.assertIn("anchor_right = 1.0", scene)
        self.assertIn("offset_right = -20.0", scene)
        self.assertIn("主要行动剩余", script)
        self.assertIn("聊天 / 购物 / 吃饭 / 普通移动：免费", script)
        self.assertIn('call("advance_campus_phase")', script)

    def test_phase_changes_replay_visible_npc_routes_without_status_text(self):
        scene = (GAME_DIR / "scenes/debug/campus_navigation_test.tscn").read_text(
            encoding="utf-8"
        )
        layer = (GAME_DIR / "scripts/world/campus_npc_movement_layer.gd").read_text(
            encoding="utf-8"
        )
        npc = (GAME_DIR / "scripts/npc/npc_controller.gd").read_text(encoding="utf-8")
        self.assertIn('name="NpcMovementLayer"', scene)
        self.assertIn('"ACTOR_LOCATION_CHANGED"', layer)
        self.assertIn("npc.show_name_label = false", layer)
        self.assertNotIn("Label.new", layer)
        self.assertIn("func play_simulation_route", npc)
        self.assertIn("name_label.visible = show_name_label", npc)


if __name__ == "__main__":
    unittest.main()
