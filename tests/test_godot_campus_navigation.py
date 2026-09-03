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


if __name__ == "__main__":
    unittest.main()
