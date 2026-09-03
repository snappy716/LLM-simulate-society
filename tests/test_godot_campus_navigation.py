from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_DIR = Path(__file__).resolve().parents[1]
GAME_DIR = REPOSITORY_DIR / "game"


class GodotCampusNavigationSourceTests(unittest.TestCase):
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

    def test_bridge_exposes_authoritative_phase_advance(self):
        bridge = (GAME_DIR / "scripts/simulation/simulation_bridge.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn("signal campus_phase_advanced", bridge)
        self.assertIn("func advance_campus_phase()", bridge)
        self.assertIn('"action_id": "ADVANCE_PHASE"', bridge)

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
