from __future__ import annotations

import json
import hashlib
import struct
import unittest
from pathlib import Path


REPOSITORY_DIR = Path(__file__).resolve().parents[1]
GAME_DIR = REPOSITORY_DIR / "game"


class GodotCampusNavigationSourceTests(unittest.TestCase):
    def test_phone_messages_have_contact_thread_input_and_free_command_bridge(self):
        phone = (GAME_DIR / "scripts/ui/campus_phone_ui.gd").read_text(encoding="utf-8")
        bridge = (GAME_DIR / "scripts/simulation/simulation_bridge.gd").read_text(encoding="utf-8")
        for text in (
            "_build_message_page", "_refresh_message_thread", "_send_phone_message",
            '"SEND_PHONE_MESSAGE"', '"MARK_PHONE_THREAD_READ"', "不消耗主要行动",
        ):
            self.assertIn(text, phone)
        self.assertIn("func operate_campus_message", bridge)
        self.assertIn("campus_phone_message_completed", bridge)
        inspector = (GAME_DIR / "scripts/ui/campus_npc_inspector_ui.gd").read_text(encoding="utf-8")
        self.assertIn('"ADD_PHONE_CONTACT"', inspector)
        self.assertIn("交换联系方式（免费操作）", inspector)
        self.assertIn("func operate_campus_dialogue", bridge)
        self.assertIn("campus_dialogue_completed", bridge)
        self.assertIn("当面交谈（免费，可继续追问）", inspector)
        self.assertIn('"TALK_TO_NPC"', bridge)
        self.assertIn("func operate_campus_social_proposal", bridge)
        self.assertIn("campus_social_proposal_completed", bridge)
        self.assertIn('"MAKE_SOCIAL_PROPOSAL"', bridge)
        self.assertIn('"RESPOND_SOCIAL_PROPOSAL"', bridge)
        self.assertIn("campus_social_proposal_response_completed", bridge)
        self.assertIn('"ENTER_NIGHT_WORLD"', bridge)
        self.assertIn('"EXIT_NIGHT_WORLD"', bridge)
        self.assertIn("campus_night_world_operation_completed", bridge)
        self.assertIn("func operate_campus_combat", bridge)
        self.assertIn("campus_combat_operation_completed", bridge)
        self.assertIn('"START_BATTLE_PREPARATION"', phone)
        self.assertIn('"DEPLOY_COMBAT_CHARACTER"', phone)
        self.assertIn('"CONFIRM_BATTLE_DEPLOYMENT"', phone)
        self.assertIn('"START_CARD_COMBAT"', phone)
        self.assertIn('"END_COMBAT_ROUND"', phone)
        self.assertIn("共享指令点", phone)
        self.assertIn("锁定后本场不能替补", phone)
        self.assertTrue((GAME_DIR / "tools/test_campus_combat_round_flow.gd").is_file())
        self.assertIn("约定稍后见面", phone)
        self.assertIn("正式提出", phone)

    def test_seven_latest_collaboration_maps_are_catalogued_with_real_dimensions(self):
        catalog_path = GAME_DIR / "data/campus_art_catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        maps = catalog["maps"]
        self.assertEqual("Project-c-0.1(1).rar", catalog["source_package"])
        self.assertEqual(7, len(maps))
        self.assertEqual(7, len({entry["id"] for entry in maps}))
        self.assertEqual(7, len({entry["texture_path"] for entry in maps}))
        self.assertEqual(
            7,
            len(list((GAME_DIR / "assets/maps/campus_collab").glob("*.png"))),
        )
        for entry in maps:
            self.assertIn(entry["semantic_location_id"], {
                "south_gate_region",
                "student_life_region",
                "east_dorm_region",
                "west_dorm_region",
                "humanities_psychology_region",
                "central_region",
                "sports_health_region",
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
            x, y, w, h = entry["walk_rect"]
            self.assertTrue(0 <= x < x + w <= width)
            self.assertTrue(0 <= y < y + h <= height)
            sx, sy = entry["spawn"]
            self.assertTrue(x <= sx <= x + w and y <= sy <= y + h, entry["id"])

    def test_maps_match_the_reviewed_new_delivery(self):
        expected = {
            "campus_gate": "7a0d08d064bcf01628d3ed34f99544498c1e0052bec8fb9b766e01dbffd7831d",
            "east_dormitory": "7ca331f067344c13699cf32bfbdc99c5be5e19967e662f3696e276591d852c32",
            "living_area": "da8064eb1167dce3bb56419f0ee9eeb48cea0723e14a38d639ec373344fbb164",
            "psychology_bridge": "09b5bdcdfb44a4399060dbbf63a03592b9a1a7817b634a86fa78858f6664cdd8",
            "west_dormitory": "4f2be076746bc8f025c5c79a9f7b9acf7553cafcc26f623474ff0017d3bc68fb",
            "library": "7bccb9eba0e2d761d096275b8d89235c518f3888d49cb2ed276b73ce95c80dd7",
            "sports_field": "b43950d24ffd5f6e92a3eb9c1454e8e935dadf7142e8e04092db8695636e5dbb",
        }
        for map_id, digest in expected.items():
            path = GAME_DIR / "assets/maps/campus_collab" / f"{map_id}.png"
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest(), map_id)

    def test_library_and_sports_npcs_are_not_projected_on_other_maps(self):
        maps = json.loads((GAME_DIR / "data/campus_art_catalog.json").read_text())["maps"]
        for region, owner in [("central_region", "library"), ("sports_health_region", "sports_field")]:
            self.assertEqual([owner], [entry["id"] for entry in maps if region in entry["visible_region_ids"]])

    def test_latest_art_maps_form_one_reciprocal_walkable_network(self):
        catalog = json.loads((GAME_DIR / "data/campus_art_catalog.json").read_text(encoding="utf-8"))
        passages = json.loads(
            (REPOSITORY_DIR / "content/locations/campus_passages.json").read_text(encoding="utf-8")
        )["passages"]
        passage_ids = {entry["id"] for entry in passages}
        passage_by_id = {entry["id"]: entry for entry in passages}
        maps = {entry["id"]: entry for entry in catalog["maps"]}
        adjacency = {map_id: set() for map_id in maps}
        edges = set()
        for map_id, entry in maps.items():
            self.assertTrue(entry.get("edge_exits"), map_id)
            for exit_config in entry["edge_exits"]:
                self.assertIn(exit_config["passage_id"], passage_ids)
                self.assertIn(exit_config["target_map_id"], maps)
                self.assertIn(exit_config["edge"], {"left", "right", "top", "bottom"})
                self.assertEqual(2, len(exit_config["target_arrival_ratio"]))
                self.assertTrue(all(0 < value < 1 for value in exit_config["target_arrival_ratio"]))
                passage = passage_by_id[exit_config["passage_id"]]
                self.assertEqual(
                    {passage["from_id"], passage["to_id"]},
                    {entry["semantic_location_id"], maps[exit_config["target_map_id"]]["semantic_location_id"]},
                )
                adjacency[map_id].add(exit_config["target_map_id"])
                edges.add((map_id, exit_config["target_map_id"], exit_config["passage_id"]))
        for source, target, passage_id in edges:
            self.assertIn((target, source, passage_id), edges)
        visited = set()
        pending = [catalog["default_map_id"]]
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            pending.extend(adjacency[current] - visited)
        self.assertEqual(set(maps), visited)

    def test_existing_blueprint_tool_has_explicit_boundary_position_type(self):
        generator = (
            GAME_DIR / "tools/generate_full_city_orthographic_blueprint.gd"
        ).read_text(encoding="utf-8")
        self.assertIn("var position: int = MARGIN + int(boundary) * CELL", generator)

    def test_project_starts_campus_and_keeps_stable_user_storage_name(self):
        project = (GAME_DIR / "project.godot").read_text(encoding="utf-8")
        self.assertIn('run/main_scene="res://scenes/campus/campus_collab_test.tscn"', project)
        self.assertIn('config/name="project-a-0.2"', project)
        self.assertIn('InterfaceSettings="*res://scenes/ui/interface_settings_ui.tscn"', project)
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
        player_scene = (GAME_DIR / "scenes/characters/player.tscn").read_text(encoding="utf-8")
        trigger_scene = (
            GAME_DIR / "scenes/world/components/campus_transition_trigger.tscn"
        ).read_text(encoding="utf-8")
        self.assertIn('add_to_group("player")', player)
        self.assertIn("collision_layer = 2", player_scene)
        self.assertIn("collision_mask = 2", trigger_scene)

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

    def test_forum_detail_exposes_relationship_and_club_consequences(self):
        phone = (GAME_DIR / "scripts/ui/campus_phone_ui.gd").read_text(encoding="utf-8")
        self.assertIn("[b]社会影响[/b]", phone)
        self.assertIn("organization_name", phone)
        self.assertIn("social_result", phone)
        self.assertIn("已结算", phone)

    def test_forum_ui_exposes_separate_surface_and_discovered_night_channels(self):
        phone = (GAME_DIR / "scripts/ui/campus_phone_ui.gd").read_text(encoding="utf-8")
        for text in (
            "表世界 · 校园广场",
            "里世界 · 未发现",
            "里世界 · 可浏览",
            "里世界 · 行动中",
            "进入夜相后可接取",
        ):
            self.assertIn(text, phone)
        self.assertIn('task.get("forum", "surface")', phone)
        self.assertIn('night_forum_accessible', phone)

    def test_course_app_exposes_college_abilities_and_future_card_pool(self):
        phone = (GAME_DIR / "scripts/ui/campus_phone_ui.gd").read_text(encoding="utf-8")
        self.assertIn("学院能力 · 心理学院", phone)
        self.assertIn('player.get("abilities", [])', phone)
        self.assertIn('player", {}) as Dictionary).get("card_pool", [])', phone)
        self.assertIn('card.get("command_cost", 0)', phone)
        self.assertIn("角色绑定的战斗卡牌", phone)

    def test_club_app_exposes_membership_resources_and_activity_actions(self):
        phone = (GAME_DIR / "scripts/ui/campus_phone_ui.gd").read_text(encoding="utf-8")
        bridge = (GAME_DIR / "scripts/simulation/simulation_bridge.gd").read_text(
            encoding="utf-8"
        )
        for text in ("社团中心", "公共资源", "你的身份", "团队战术", "申请加入", "参加本时段活动"):
            self.assertIn(text, phone)
        self.assertIn("func operate_campus_club", bridge)
        self.assertIn("campus_club_operation_completed", bridge)
        self.assertIn('"JOIN_CAMPUS_CLUB"', phone)
        self.assertIn('"CLUB_ACTIVITY"', phone)

    def test_party_app_exposes_invitation_commitment_and_stability(self):
        phone = (GAME_DIR / "scripts/ui/campus_phone_ui.gd").read_text(encoding="utf-8")
        bridge = (GAME_DIR / "scripts/simulation/simulation_bridge.gd").read_text(
            encoding="utf-8"
        )
        for text in ("行动小队", "稳定度", "关系协作能力", "发出邀请", "解除承诺"):
            self.assertIn(text, phone)
        self.assertIn("func operate_campus_party", bridge)
        self.assertIn("campus_party_operation_completed", bridge)
        self.assertIn('"party_invite"', phone)
        self.assertIn("需先交换联系方式", phone)
        self.assertIn('"DISMISS_PARTY_MEMBER"', phone)

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
        self.assertIn("_configure_edge_transitions", controller)
        self.assertIn("target_arrival_ratio", controller)

    def test_campus_scene_keeps_authoritative_npcs_visible_and_inspectable(self):
        scene = (GAME_DIR / "scenes/campus/campus_collab_test.tscn").read_text(
            encoding="utf-8"
        )
        layer = (GAME_DIR / "scripts/world/campus_npc_movement_layer.gd").read_text(
            encoding="utf-8"
        )
        inspector = (GAME_DIR / "scripts/ui/campus_npc_inspector_ui.gd").read_text(
            encoding="utf-8"
        )
        project = (GAME_DIR / "project.godot").read_text(encoding="utf-8")
        self.assertIn('name="CampusNpcInspectorUI"', scene)
        self.assertIn("interact_npc={", project)
        self.assertIn('add_to_group("campus_npc_movement_layer")', layer)
        self.assertIn("func _refresh_residents()", layer)
        self.assertIn("func nearest_interactable_npc", layer)
        self.assertIn("get_campus_profile", inspector)
        self.assertIn("内在需求、秘密动机与后续计划不会直接显示", inspector)
        self.assertNotIn('_dictionary_lines(profile.get("needs"', inspector)

    def test_forum_detail_explains_dynamic_task_origin_without_hidden_need_values(self):
        phone = (GAME_DIR / "scripts/ui/campus_phone_ui.gd").read_text(encoding="utf-8")
        self.assertIn("任务来源", phone)
        self.assertIn("其他人仍可接取", phone)
        self.assertNotIn('task.get("issuer_need_before"', phone)

    def test_npc_inspector_loads_private_paginated_chronicle_on_demand(self):
        inspector = (GAME_DIR / "scripts/ui/campus_npc_inspector_ui.gd").read_text(
            encoding="utf-8"
        )
        bridge = (GAME_DIR / "scripts/simulation/simulation_bridge.gd").read_text(
            encoding="utf-8"
        )
        for label in ("人物概况", "日程记录", "重要经历", "加载更早记录"):
            self.assertIn(label, inspector)
        self.assertIn("request_npc_chronicle", inspector)
        self.assertIn("campus_npc_chronicle_loaded", bridge)
        self.assertIn("/kernel/npcs/%s/chronicle", bridge)
        self.assertNotIn('campus_snapshot["chronicles"]', inspector)

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
