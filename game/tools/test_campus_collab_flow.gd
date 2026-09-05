extends SceneTree

const COLLAB_SCENE := "res://scenes/campus/campus_collab_test.tscn"


func _initialize() -> void:
	call_deferred("_run_flow")


func _run_flow() -> void:
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(100):
		var snapshot = bridge.get("campus_snapshot")
		if snapshot is Dictionary and not snapshot.is_empty():
			break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())

	var packed := load(COLLAB_SCENE) as PackedScene
	assert(packed != null)
	var outdoor = packed.instantiate()
	root.add_child(outdoor)
	current_scene = outdoor
	await process_frame

	var presentation := root.get_node("CampusPresentation")
	assert((presentation.call("all_maps") as Array).size() == 5)
	var map := outdoor.get_node("CampusMap") as Sprite2D
	assert(map.texture != null)
	assert(map.texture.get_size() == Vector2(1774, 887))
	var camera := outdoor.get_node("Player/Camera2D") as Camera2D
	assert(camera.limit_right == 1774)
	assert(camera.limit_bottom == 887)
	assert(bool(presentation.call("select_map", "living_area")))
	await process_frame
	assert(map.texture.get_size() == Vector2(2040, 771))
	assert(bool(presentation.call("select_map", "psychology_bridge")))
	await process_frame
	assert(map.texture.get_size() == Vector2(1742, 903))
	assert(camera.limit_right == 1742)
	assert(bool(presentation.call("select_map", "campus_gate")))
	await process_frame
	assert(map.texture.get_size() == Vector2(1774, 887))
	outdoor.call("set_zoom_multiplier", 2)
	assert(camera.zoom == Vector2(2, 2))
	outdoor.call("set_zoom_multiplier", 1)

	var player = outdoor.get_node("Player")
	assert((player.get("appearance") as Dictionary).size() >= 7)
	var old_appearance: Dictionary = (player.get("appearance") as Dictionary).duplicate(true)
	var randomize_event := InputEventAction.new()
	randomize_event.action = "randomize_outfit"
	randomize_event.pressed = true
	player.call("_unhandled_input", randomize_event)
	assert((player.get("appearance") as Dictionary) != old_appearance)
	var movement_layer = outdoor.get_node("NpcMovementLayer")
	for _attempt in range(20):
		if int(movement_layer.call("visible_resident_count")) > 0:
			break
		await process_frame
	assert(int(movement_layer.call("visible_resident_count")) > 0)
	var nearby_npc = movement_layer.call("nearest_interactable_npc", player.global_position, 100.0)
	assert(nearby_npc != null)
	assert(not nearby_npc.name_label.visible)
	var inspector = outdoor.get_node("CampusNpcInspectorUI")
	inspector.call("inspect_npc", nearby_npc)
	assert(bool(inspector.call("is_open")))
	assert(paused)
	var details := inspector.get("_details") as RichTextLabel
	var public_text := details.text
	assert(public_text.contains("公开身份"))
	assert(public_text.contains("正在做的事"))
	assert(not public_text.contains("simulation_tier"))
	assert(not public_text.contains("night_access"))
	var dialogue_budget_before := int(((bridge.get("campus_snapshot") as Dictionary).get("player", {}) as Dictionary).get("action_budget", {}).get("major_remaining", -1))
	var dialogue_input := inspector.get("_dialogue_input") as LineEdit
	dialogue_input.text = "你好，我想先认识一下你。"
	inspector.call("_submit_dialogue")
	var dialogue_resolution = await bridge.campus_dialogue_completed
	assert(bool(dialogue_resolution[0]), "in-person dialogue failed: %s" % dialogue_resolution[1])
	var dialogue_result: Dictionary = dialogue_resolution[1]
	var dialogue_payload: Dictionary = (dialogue_result.get("result", {}) as Dictionary).get("payload", {})
	assert(String(dialogue_payload.get("action_class", "")) == "free")
	assert(not String(dialogue_payload.get("reply_text", "")).is_empty())
	assert(int(((bridge.get("campus_snapshot") as Dictionary).get("player", {}) as Dictionary).get("action_budget", {}).get("major_remaining", -1)) == dialogue_budget_before)
	inspector.call("_set_open", false)
	assert(not paused)

	var phone_ui = outdoor.get_node("CampusPhoneUI")
	phone_ui.call("_set_open", true)
	assert(bool(phone_ui.call("is_open")))
	assert(paused)
	phone_ui.call("_open_app", "messages", "校园通讯")
	var message_picker := phone_ui.get("_message_contact_picker") as OptionButton
	assert(message_picker.item_count == 3)
	var phone_budget_before := int(((bridge.get("campus_snapshot") as Dictionary).get("player", {}) as Dictionary).get("action_budget", {}).get("major_remaining", -1))
	var message_input := phone_ui.get("_message_input") as LineEdit
	message_input.text = "你好，我们之后可以聊聊校园里的事吗？"
	var message_send := phone_ui.get("_message_send_action") as Button
	message_send.pressed.emit()
	var message_resolution = await bridge.campus_phone_message_completed
	assert(bool(message_resolution[0]), "phone message failed: %s" % message_resolution[1])
	assert(String(message_resolution[2]) == "SEND_PHONE_MESSAGE")
	var messaged_npc_id := String(message_resolution[3])
	var messaged_thread: Dictionary = (bridge.get("campus_snapshot") as Dictionary).get("messaging", {}).get("threads", {}).get(messaged_npc_id, {})
	assert((messaged_thread.get("messages", []) as Array).size() == 2)
	assert(int(((bridge.get("campus_snapshot") as Dictionary).get("player", {}) as Dictionary).get("action_budget", {}).get("major_remaining", -1)) == phone_budget_before)
	var read_resolution = await bridge.campus_phone_message_completed
	assert(bool(read_resolution[0]), "phone read state failed: %s" % read_resolution[1])
	assert(String(read_resolution[2]) == "MARK_PHONE_THREAD_READ")
	var proposal_picker := phone_ui.get("_message_proposal_picker") as OptionButton
	proposal_picker.select(2)
	var proposal_button := phone_ui.get("_message_proposal_action") as Button
	proposal_button.pressed.emit()
	var proposal_resolution = await bridge.campus_social_proposal_completed
	var proposal_payload: Dictionary = (proposal_resolution[1].get("result", {}) as Dictionary).get("payload", {})
	assert(String(proposal_payload.get("proposal_type", "")) == "meet_up")
	assert(String(proposal_payload.get("status", "")) in ["accepted", "declined"])
	assert(String(proposal_payload.get("action_class", "")) == "free")
	messaged_thread = (bridge.get("campus_snapshot") as Dictionary).get("messaging", {}).get("threads", {}).get(messaged_npc_id, {})
	assert((messaged_thread.get("messages", []) as Array).size() == 4)
	var proposal_read_resolution = await bridge.campus_phone_message_completed
	assert(bool(proposal_read_resolution[0]), "proposal reply read state failed: %s" % proposal_read_resolution[1])
	assert(String(proposal_read_resolution[2]) == "MARK_PHONE_THREAD_READ")
	phone_ui.call("_open_app", "courses", "课程平台")
	var course_content := phone_ui.get("_content") as RichTextLabel
	assert(course_content.text.contains("学院能力"))
	assert(course_content.text.contains("认知心理"))
	assert(course_content.text.contains("角色绑定"))
	phone_ui.call("_open_app", "health", "健康档案")
	phone_ui.call("_open_app", "clubs", "社团中心")
	var club_detail := phone_ui.get("_club_detail") as RichTextLabel
	assert(club_detail.text.contains("公共资源"))
	assert(club_detail.text.contains("团队战术"))
	assert((phone_ui.get("_club_picker") as OptionButton).item_count == 12)
	phone_ui.call("_open_app", "party", "行动小队")
	var party_detail := phone_ui.get("_party_detail") as RichTextLabel
	assert(party_detail.text.contains("稳定度"))
	assert(party_detail.text.contains("关系协作能力"))
	var party_candidate_picker := phone_ui.get("_party_candidate_picker") as OptionButton
	assert(party_candidate_picker.item_count > 0)
	var party_invite_action := phone_ui.get("_party_invite_action") as Button
	assert(party_invite_action.disabled)
	assert(party_invite_action.text == "先交换联系方式")
	phone_ui.call("_open_app", "forums", "校园互助")
	var forum_cards := phone_ui.get("_forum_cards") as VBoxContainer
	assert(forum_cards.get_child_count() == 12)
	var first_task_card := forum_cards.get_child(0) as Button
	first_task_card.pressed.emit()
	var view_resolution = await bridge.campus_task_operation_completed
	assert(bool(view_resolution[0]), "forum view failed: %s" % view_resolution[1])
	var selected_task_id := String(phone_ui.get("_selected_task_id"))
	assert(not selected_task_id.is_empty())
	var primary_task_button := phone_ui.get("_forum_primary_action") as Button
	assert(not primary_task_button.disabled)
	primary_task_button.pressed.emit()
	var claim_resolution = await bridge.campus_task_operation_completed
	assert(bool(claim_resolution[0]), "forum claim failed: %s" % claim_resolution[1])
	var claimed_task: Dictionary = (bridge.get("campus_snapshot") as Dictionary).get("tasks", {}).get(selected_task_id, {})
	assert(bool(claimed_task.get("owned_by_player", false)))
	var abandon_task_button := phone_ui.get("_forum_abandon_action") as Button
	assert(abandon_task_button.visible)
	abandon_task_button.pressed.emit()
	var abandon_resolution = await bridge.campus_task_operation_completed
	assert(bool(abandon_resolution[0]), "forum abandon failed: %s" % abandon_resolution[1])
	phone_ui.call("_set_open", false)
	assert(not paused)
	assert(not bool(phone_ui.call("is_open")))
	assert(outdoor.has_node("CampusMapUI"))
	assert(outdoor.has_node("CameraControls"))
	assert(bool(movement_layer.get("use_scene_route_anchors")))
	assert(get_nodes_in_group("campus_route_anchor").size() >= 10)

	var before_walk_clock: Dictionary = (bridge.get("campus_snapshot") as Dictionary).get("clock", {}).duplicate(true)
	var before_walk_budget := int(((bridge.get("campus_snapshot") as Dictionary).get("player", {}) as Dictionary).get("action_budget", {}).get("major_remaining", -1))
	await _walk_edge(outdoor, bridge, presentation, "ToLivingArea", "living_area", "student_life_region")

	var entrance = outdoor.get_node("StudentCenterEntrance")
	assert(entrance.monitoring)
	var expected_outdoor_return := (outdoor.get_node("StudentCenterOutdoorArrival") as Node2D).global_position
	entrance.call("request_traversal")
	var entrance_resolution = await entrance.traversal_resolved
	assert(bool(entrance_resolution[0]), "collab entrance failed: %s" % entrance_resolution[1])
	for _attempt in range(30):
		await process_frame
		if current_scene != outdoor:
			break
	assert(current_scene != outdoor)
	assert(current_scene.name == "CampusLobbyGraybox")

	var exit_trigger = current_scene.get_node("StudentCenterExit")
	exit_trigger.call("request_traversal")
	var exit_resolution = await exit_trigger.traversal_resolved
	assert(bool(exit_resolution[0]), "collab exit failed: %s" % exit_resolution[1])
	var lobby = current_scene
	for _attempt in range(30):
		await process_frame
		if current_scene != lobby:
			break
	assert(current_scene != lobby)
	assert(current_scene.name == "CampusCollabTest")
	var returned_player := current_scene.get_node("Player") as Node2D
	for _attempt in range(30):
		if returned_player.position.distance_to(expected_outdoor_return) < 1.0:
			break
		await process_frame
	assert(returned_player.position.distance_to(expected_outdoor_return) < 1.0)

	# Every latest art map is connected by a bidirectional, authoritative edge.
	await _walk_edge(current_scene, bridge, presentation, "ToEastDormitory", "east_dormitory", "east_dorm_region")
	await _walk_edge(current_scene, bridge, presentation, "ToLivingArea", "living_area", "student_life_region")
	await _walk_edge(current_scene, bridge, presentation, "ToWestDormitory", "west_dormitory", "west_dorm_region")
	await _walk_edge(current_scene, bridge, presentation, "ToLivingArea", "living_area", "student_life_region")
	await _walk_edge(current_scene, bridge, presentation, "ToPsychologyBridge", "psychology_bridge", "humanities_psychology_region")
	await _walk_edge(current_scene, bridge, presentation, "ToLivingArea", "living_area", "student_life_region")
	await _walk_edge(current_scene, bridge, presentation, "ToCampusGate", "campus_gate", "south_gate_region")
	var after_walk_snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(after_walk_snapshot.get("clock", {}) == before_walk_clock)
	assert(int((after_walk_snapshot.get("player", {}) as Dictionary).get("action_budget", {}).get("major_remaining", -1)) == before_walk_budget)

	var phase_panel := current_scene.get_node("UI/PhasePanel")
	var advance_button := phase_panel.get_node("Margin/VBox/Advance") as Button
	advance_button.pressed.emit()
	var afternoon_resolution = await bridge.campus_phase_advanced
	assert(bool(afternoon_resolution[0]))
	advance_button.pressed.emit()
	var evening_resolution = await bridge.campus_phase_advanced
	assert(bool(evening_resolution[0]))
	await process_frame
	var incoming: Array = ((bridge.get("campus_snapshot") as Dictionary).get("social", {}) as Dictionary).get("incoming_proposals", [])
	var pending_incoming_count := 0
	for proposal in incoming:
		if proposal is Dictionary and String(proposal.get("status", "")) == "pending":
			pending_incoming_count += 1
	assert(pending_incoming_count > 0)
	var current_phone = current_scene.get_node("CampusPhoneUI")
	current_phone.call("_set_open", true)
	current_phone.call("_open_app", "messages", "校园通讯")
	if bool(bridge.call("is_campus_busy")):
		var incoming_read_resolution = await bridge.campus_phone_message_completed
		assert(bool(incoming_read_resolution[0]), "incoming proposal read failed: %s" % incoming_read_resolution[1])
	var incoming_picker := current_phone.get("_incoming_proposal_picker") as OptionButton
	assert(incoming_picker.item_count > 0)
	var incoming_id := String(incoming_picker.get_item_metadata(incoming_picker.selected))
	var incoming_decline := current_phone.get("_incoming_proposal_decline") as Button
	incoming_decline.pressed.emit()
	var incoming_resolution = await bridge.campus_social_proposal_response_completed
	assert(bool(incoming_resolution[0]), "incoming proposal response failed: %s" % incoming_resolution[1])
	assert(String(incoming_resolution[2]) == incoming_id)
	assert(String(((incoming_resolution[1].get("result", {}) as Dictionary).get("payload", {}) as Dictionary).get("status", "")) == "declined")
	current_phone.call("_set_open", false)
	assert(not paused)
	var night_world_button := phase_panel.get_node("Margin/VBox/NightWorld") as Button
	assert(not night_world_button.disabled)
	night_world_button.pressed.emit()
	var night_entry_resolution = await bridge.campus_night_world_operation_completed
	assert(bool(night_entry_resolution[0]), "night-world entry failed: %s" % night_entry_resolution[1])
	var entered_snapshot: Dictionary = bridge.get("campus_snapshot")
	var entered_night: Dictionary = entered_snapshot.get("night_world", {})
	assert(String(entered_night.get("current_layer", "")) == "night")
	assert(int(entered_night.get("pollution", 0)) > 0)
	assert(bool(entered_night.get("night_forum_unlocked", false)))
	assert(bool(entered_night.get("night_forum_accessible", false)))
	assert(int(entered_night.get("active_npc_count", 0)) >= 6)
	assert(int((((entered_snapshot.get("task_summary", {}) as Dictionary).get("by_forum", {}) as Dictionary).get("night", {}) as Dictionary).get("total", 0)) == 20)
	current_phone.call("_set_open", true)
	current_phone.call("_open_app", "forums", "双层论坛")
	current_phone.call("_set_forum_channel", "night")
	await process_frame
	var night_cards := current_phone.get("_forum_cards") as VBoxContainer
	var night_access_note := current_phone.get("_forum_access_note") as Label
	assert(night_cards.get_child_count() > 0)
	assert(night_access_note.text.contains("当前可竞争接取"))
	current_phone.call("_set_open", false)
	assert(not paused)
	night_world_button.pressed.emit()
	var night_exit_resolution = await bridge.campus_night_world_operation_completed
	assert(bool(night_exit_resolution[0]), "night-world exit failed: %s" % night_exit_resolution[1])
	assert(String(((bridge.get("campus_snapshot") as Dictionary).get("night_world", {}) as Dictionary).get("current_layer", "")) == "surface")
	movement_layer = current_scene.get_node("NpcMovementLayer")
	assert(int(movement_layer.get("last_replayed_count")) > 0)
	for visible_npc in movement_layer.get_children():
		assert(not visible_npc.name_label.visible)
	var log_npc = movement_layer.get_child(0)
	var log_profile: Dictionary = log_npc.call("get_campus_profile")
	var log_inspector = current_scene.get_node("CampusNpcInspectorUI")
	log_inspector.call("inspect_npc", log_npc)
	log_inspector.call("_select_tab", "recent")
	var log_resolution = await bridge.campus_npc_chronicle_loaded
	assert(bool(log_resolution[0]), "NPC chronicle failed: %s" % log_resolution[1])
	assert(String(log_resolution[2]) == String(log_profile.get("npc_id")))
	await process_frame
	var log_details := log_inspector.get("_details") as RichTextLabel
	assert(log_details.text.contains("最近七日日程"))
	assert(log_details.text.contains("第 1 天"))
	assert(not log_details.text.contains("NPC_DECISION_MADE"))
	log_inspector.call("_set_open", false)
	assert(not paused)

	var before_map_clock: Dictionary = (bridge.get("campus_snapshot") as Dictionary).get("clock", {}).duplicate(true)
	var before_map_budget := int(((bridge.get("campus_snapshot") as Dictionary).get("player", {}) as Dictionary).get("action_budget", {}).get("major_remaining", -1))
	var map_ui = current_scene.get_node("CampusMapUI")
	map_ui.call("_choose_map", "east_dormitory")
	var map_travel_resolution = await bridge.campus_fast_travel_completed
	assert(bool(map_travel_resolution[0]), "campus map travel failed: %s" % map_travel_resolution[1])
	await process_frame
	var after_map_snapshot: Dictionary = bridge.get("campus_snapshot")
	assert((after_map_snapshot.get("player", {}) as Dictionary).get("current_location_id") == "east_dorm_region")
	assert(after_map_snapshot.get("clock", {}) == before_map_clock)
	assert(int((after_map_snapshot.get("player", {}) as Dictionary).get("action_budget", {}).get("major_remaining", -1)) == before_map_budget)
	assert(String(presentation.get("current_map_id")) == "east_dormitory")
	map = current_scene.get_node("CampusMap") as Sprite2D
	assert(map.texture.get_size() == Vector2(1774, 887))
	var same_region_revision := int(after_map_snapshot.get("revision", -1))
	map_ui.call("_choose_map", "east_dormitory")
	await process_frame
	assert(String(presentation.get("current_map_id")) == "east_dormitory")
	assert(int((bridge.get("campus_snapshot") as Dictionary).get("revision", -2)) == same_region_revision)
	assert((current_scene.get_node("CampusMap") as Sprite2D).texture.get_size() == Vector2(1774, 887))

	print("CAMPUS_COLLAB_FLOW_OK")
	current_scene.queue_free()
	current_scene = null
	await process_frame
	await process_frame
	quit(0)


func _walk_edge(
	scene: Node,
	bridge: Node,
	presentation: Node,
	trigger_name: String,
	target_map_id: String,
	target_location_id: String
) -> void:
	var trigger = scene.get_node("MapEdgeTransitions/%s" % trigger_name)
	# Moving the real CharacterBody2D into the Area2D verifies automatic walking
	# activation, rather than bypassing the scene with a direct method call.
	var player := scene.get_node("Player") as Node2D
	player.global_position = trigger.global_position
	var resolution = await trigger.traversal_resolved
	assert(bool(resolution[0]), "edge %s failed: %s" % [trigger_name, resolution[1]])
	await process_frame
	assert(current_scene == scene)
	assert(String(presentation.get("current_map_id")) == target_map_id)
	assert(not bool(bridge.get("_campus_busy")), "arrival triggered an unintended second traversal")
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	assert((snapshot.get("player", {}) as Dictionary).get("current_location_id") == target_location_id)
