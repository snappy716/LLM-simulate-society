"""Static companion to the real Godot theme/interaction acceptance flow."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CampusThemeTests(unittest.TestCase):
    def test_request_lifecycle_preserves_drafts_and_guards_pending(self):
        phone = (ROOT / "game/scripts/ui/campus_phone_ui.gd").read_text()
        inspector = (ROOT / "game/scripts/ui/campus_npc_inspector_ui.gd").read_text()
        self.assertIn("func _send_combat_operation", phone)
        self.assertIn("_message_input.text.strip_edges() == _message_sent_text", phone)
        self.assertIn("_dialogue_input.text.strip_edges() == _dialogue_sent_text", inspector)
        self.assertIn("_lock_waiting_controls(_message_root)", phone)

    def test_club_display_terms_cover_current_content(self):
        import json
        import re
        catalog = json.loads((ROOT / "content/organizations/clubs.json").read_text())
        text = (ROOT / "game/scripts/ui/campus_ui_text.gd").read_text()
        terms = set(re.findall(r'"([a-z_]+)": "', text))
        for club in catalog["clubs"]:
            for key in ("category", "surface_skill", "signature_resource"):
                self.assertIn(club[key], terms)

    def test_social_pages_have_pending_locks_and_availability_hints(self):
        phone = (ROOT / "game/scripts/ui/campus_phone_ui.gd").read_text()
        for page in ("forum", "club", "party"):
            self.assertIn(f'_lock_social_controls("{page}"', phone)
        for control in ("_forum_primary_action", "_club_membership_action", "_club_activity_action", "_party_invite_action", "_party_dismiss_action"):
            self.assertIn(control + ".tooltip_text", phone)

    def test_inventory_panels_share_operation_feedback(self):
        for name in ("health", "inventory", "trade"):
            panel = (ROOT / f"game/scripts/ui/campus_{name}_panel.gd").read_text()
            self.assertIn("operation_feedback(success, result)", panel)
            self.assertIn("PENDING_MESSAGE", panel)
        health = (ROOT / "game/scripts/ui/campus_health_panel.gd").read_text()
        for name in ("rest_button", "home_button", "heal_button"):
            self.assertIn(f"{name}.tooltip_text", health)

    def test_phone_catalog_has_unique_entries_and_licensed_icons(self):
        import re
        catalog = (ROOT / "game/scripts/ui/campus_phone_catalog.gd").read_text()
        phone = (ROOT / "game/scripts/ui/campus_phone_ui.gd").read_text()
        ids = re.findall(r'"id": "([^"]+)"', catalog)
        self.assertEqual(len(ids), 15)
        self.assertEqual(len(set(ids)), 15)
        apps = phone.split("const APPS := [", 1)[1].split("\n]", 1)[0]
        self.assertEqual(set(ids), set(re.findall(r'"id": "([^"]+)"', apps)))
        directory = ROOT / "game/assets/ui/kenney_game_icons"
        for icon in re.findall(r'"icon": "([^"]+)"', catalog):
            self.assertTrue((directory / (icon + ".png")).is_file())
        self.assertIn("License (CC0)", (directory / "license.txt").read_text())
        self.assertNotIn("func _icon_style", phone)

    def test_phone_long_forms_have_fixed_navigation_and_shared_activity_labels(self):
        phone = (ROOT / "game/scripts/ui/campus_phone_ui.gd").read_text()
        self.assertIn("_app_scroll.follow_focus = true", phone)
        self.assertIn("_close_button = hint", phone)
        self.assertIn("UI_TEXT.activity_name", phone)
        self.assertIn("node.custom_minimum_size.y = 160", phone)

    def test_hud_is_readable_and_actions_have_unavailability_reasons(self):
        hud = (ROOT / "game/scripts/ui/campus_phase_debug_panel.gd").read_text()
        self.assertIn("advance_button.tooltip_text", hud)
        self.assertIn("night_world_button.tooltip_text", hud)
        self.assertIn('player.get("vitals", {})', hud)
        self.assertNotIn('plan.get("activity_id"', hud)

    def test_inspector_has_viewport_sizing_and_focus_following_body(self):
        inspector = (ROOT / "game/scripts/ui/campus_npc_inspector_ui.gd").read_text()
        self.assertIn("_overlay.resized.connect(_fit_panel)", inspector)
        self.assertIn("_body_scroll.follow_focus = true", inspector)
        self.assertIn("shell.add_child(close)", inspector)
        self.assertNotIn("panel.size = Vector2(680, 700)", inspector)

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
