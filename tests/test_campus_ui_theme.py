"""Static companion to the real Godot theme/interaction acceptance flow."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CampusThemeTests(unittest.TestCase):
    def test_project_has_a_replaceable_theme_resource(self):
        project = (ROOT / "game/project.godot").read_text()
        self.assertIn('theme/custom="res://ui/themes/campus_theme.tres"', project)
        theme = (ROOT / "game/ui/themes/campus_theme.tres").read_text()
        for state in ("normal", "hover", "pressed", "disabled", "focus"):
            self.assertIn(f"Button/styles/{state}", theme)
        self.assertIn('CampusPhone/base_type = &"PanelContainer"', theme)

    def test_phone_uses_real_connection_signal_not_fictional_percentage(self):
        phone = (ROOT / "game/scripts/ui/campus_phone_ui.gd").read_text()
        self.assertIn("connection_state_changed.connect(_refresh_connection)", phone)
        self.assertIn("不表示 LLM", phone)
        self.assertNotIn("86%", phone)
        self.assertNotIn("func _panel_style", phone)
