extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func(): push_error("minimal HUD timeout"); quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _i in range(200):
		if not bridge.campus_snapshot.is_empty(): break
		await create_timer(0.05).timeout
	assert(not bridge.campus_snapshot.is_empty())
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var hud := current_scene.get_node("CampusHUD")
	var phone := current_scene.get_node("CampusPhoneUI")
	var before: Dictionary = bridge.campus_snapshot.duplicate(true)
	for size in [Vector2i(960, 540), Vector2i(1280, 720), Vector2i(1920, 1080)]:
		root.size = size
		for _frame in range(4): await process_frame
		var view: Rect2 = hud.phone.get_viewport_rect()
		assert(view.encloses(hud.phone.get_global_rect()), "phone outside viewport")
		assert(hud.phone.get_global_rect().position.y > view.size.y / 2)
		assert(hud.entries.size() == 5)
		for button in hud.entries.values():
			assert(view.encloses(button.get_global_rect()), "right icon outside viewport")
			assert(button.get_global_rect().position.x > view.size.x / 2)
			assert(button.get_theme_stylebox("normal") is StyleBoxEmpty)
			assert(button.get_theme_constant("icon_max_width") == 30)
			assert(button.material is ShaderMaterial)
			assert(button.custom_minimum_size.x >= 44, "small glyphs keep a usable hit target")
		for id in ["party", "character", "cards", "relationships"]:
			hud.open_entry(id)
			assert(phone.is_open() and paused)
			for _frame in range(3): await process_frame
			var scroll: ScrollContainer = phone._app_scroll
			assert(scroll.get_h_scroll_bar().max_value <= scroll.size.x + 1, "overflow " + id)
			if id == "character":
				assert(phone._health_root.is_visible_in_tree())
				phone._hud_tabs.get_child(1).pressed.emit()
				assert(phone._inventory_root.is_visible_in_tree())
				assert(phone._inventory_root.action_picker.selected == 2, "inventory defaults to owned usable items")
				for _frame in range(3): await process_frame
				assert(phone._inventory_root.action_picker.size.x >= 140, "inventory action label must remain readable")
				assert(not phone._health_root.visible)
				phone._hud_tabs.get_child(0).pressed.emit()
			if id == "cards":
				assert(phone._growth_root._cards_only)
				assert(phone._growth_root.actor.item_count > 0)
				assert(not phone._growth_root.read.is_visible_in_tree())
			if id == "relationships": assert(phone._relationships_root.is_visible_in_tree())
			phone._set_open(false)
			assert(not paused)
		hud.open_entry("map")
		assert(current_scene.get_node("CampusMapUI").is_open())
		current_scene.get_node("CampusMapUI")._set_open(false)
	assert(not current_scene.get_node("UI/PhasePanel").visible)
	assert(not current_scene.get_node("UI/Instructions").visible)
	assert(not current_scene.get_node("CameraControls").visible)
	var focused_icon: Button = hud.entries.cards
	assert(focused_icon.material != hud.entries.party.material, "icon feedback must be independent")
	focused_icon.grab_focus()
	await create_timer(0.22).timeout
	assert(float(focused_icon.get_meta("ink_emphasis")) > 0.99)
	assert(float(hud.entries.party.get_meta("ink_emphasis")) < 0.01)
	if RenderingServer.get_current_rendering_method() != "":
		assert(float(focused_icon.material.get_shader_parameter("emphasis")) > 0.99)
	focused_icon.release_focus()
	await create_timer(0.22).timeout
	assert(float(focused_icon.get_meta("ink_emphasis")) < 0.01)
	if RenderingServer.get_current_rendering_method() != "":
		assert(float(focused_icon.material.get_shader_parameter("emphasis")) < 0.01)
	hud.open_entry("phone")
	phone._open_app("time", "时间与镜头")
	assert(phone._time_root.is_visible_in_tree())
	assert(not phone._time_root.get_child(0).advance_button.disabled)
	phone._time_root.get_child(1).get_child(1).pressed.emit()
	assert(current_scene.get_zoom_multiplier() == 2)
	current_scene.set_zoom_multiplier(1)
	phone._set_open(false)
	assert(bridge.campus_snapshot.revision == before.revision, "browsing must not spend actions")
	# Notification fixtures only, no messages sent and no paid LLM calls.
	bridge.remove_meta("hud_messages")
	var sample := {"revision": 1, "clock": {"day": 1, "phase": "morning"}, "messaging": {"threads": {"npc": {"messages": [{"message_id": "old", "sender_id": "npc"}]}}}}
	hud._check_messages(sample)
	assert(hud.pulse_count == 0, "old mail baseline must not shake")
	sample.messaging.threads.npc.messages.append({"message_id": "new", "sender_id": "npc"})
	hud._check_messages(sample)
	assert(hud.pulse_count == 1)
	sample.messaging.threads.npc.messages.append({"message_id": "new2", "sender_id": "npc"})
	hud._check_messages(sample)
	assert(hud.pulse_count == 1, "one pulse per phase")
	sample.clock.phase = "afternoon"
	hud._check_messages(sample)
	assert(hud.pulse_count == 1, "unread mail cannot shake on phase change")
	sample.messaging.threads.npc.messages.append({"message_id": "mine", "sender_id": "player"})
	hud._check_messages(sample)
	assert(hud.pulse_count == 1, "own messages are not incoming")
	sample.messaging.threads.npc.messages.append({"message_id": "new3", "sender_id": "npc"})
	hud._check_messages(sample)
	assert(hud.pulse_count == 2)
	bridge.campus_snapshot = sample
	var rebuilt = load("res://scripts/ui/campus_hud.gd").new()
	root.add_child(rebuilt)
	var count: int = rebuilt.pulse_count
	assert(count == 0)
	rebuilt._check_messages(sample)
	assert(rebuilt.pulse_count == count, "HUD rebuild must not replay notifications")
	rebuilt.queue_free()
	bridge.campus_snapshot = before
	bridge.remove_meta("hud_messages")
	hud._render(before)
	var tracking_sample := before.duplicate(true)
	tracking_sample.tasks = {"fixture": {"task_id": "fixture", "owned_by_player": true, "state": "locked", "title": "已接委托", "scene_name": "图书馆"}}
	tracking_sample.agenda.commitments = [{"day": 2, "phase": "afternoon", "label": "已确认约定", "location_name": "校园"}]
	hud._render(tracking_sample)
	assert(hud._rows.size() == 2 and hud.tracking_detail.visible)
	tracking_sample.tasks.fixture.title = "很长的委托标题".repeat(24)
	hud._render(tracking_sample)
	assert(hud.tracking.clip_text)
	hud.cycle.pressed.emit()
	assert(hud.tracking.text.contains("近期约定"))
	hud.tracking.pressed.emit()
	assert(not hud.tracking_detail.visible and not hud.cycle.visible)
	hud._render(before)
	# The migrated control must still submit exactly one real phase command.
	phone.open_hud_page("phone")
	phone._open_app("time", "时间与镜头")
	var command_count: int = bridge._campus_command_counter
	phone._time_root.get_child(0).advance_button.pressed.emit()
	var advanced = await bridge.campus_phase_advanced
	assert(bool(advanced[0]))
	assert(bridge._campus_command_counter == command_count + 1)
	assert(bridge.campus_snapshot.clock.phase == "afternoon")
	phone._set_open(false)
	change_scene_to_file("res://scenes/debug/campus_lobby_test.tscn")
	await process_frame
	await process_frame
	assert(current_scene.has_node("CampusHUD") and current_scene.has_node("CampusMapUI"))
	current_scene.get_node("CampusHUD").open_entry("map")
	assert(current_scene.get_node("CampusMapUI").is_open())
	current_scene.get_node("CampusMapUI")._set_open(false)
	print("CAMPUS_MINIMAL_HUD_OK six_icons three_sizes direct_pages inventory_tabs cards relationships time_camera messages tracking indoor free_browsing one_real_phase_command")
	quit(0)
