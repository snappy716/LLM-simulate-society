extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("phone layout timeout")
			quit(1)
	)
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	var scroll := phone.get("_app_scroll") as ScrollContainer
	var back := phone.get("_back_button") as Button
	var close := phone.get("_close_button") as Button
	var budget: Dictionary = bridge.get("campus_snapshot").player.action_budget.duplicate(true)
	for window_size in [Vector2i(960, 540), Vector2i(1280, 720), Vector2i(1920, 1080)]:
		root.size = window_size
		phone.call("_set_open", true)
		var search := phone.get("_home_search") as LineEdit
		var home_scroll := phone.get("_home_scroll") as ScrollContainer
		var buttons: Array = phone.get("_home_buttons")
		assert(buttons.size() == 15)
		search.text = "聊天"
		search.text_changed.emit(search.text)
		var found := 0
		for button in buttons:
			assert(button.icon != null)
			if button.visible:
				found += 1
				assert(button.get_meta("app_id") == "messages")
		assert(found == 1)
		search.text = "无此功能xyz"
		search.text_changed.emit(search.text)
		assert((phone.get("_home_empty") as Label).visible)
		search.text = ""
		search.text_changed.emit(search.text)
		for _frame in range(8):
			await process_frame
		assert(not (phone.get("_home_empty") as Label).visible)
		assert(home_scroll.get_h_scroll_bar().max_value <= home_scroll.size.x + 1)
		assert(close.get_viewport_rect().encloses(search.get_global_rect()))
		for button in buttons:
			assert(button.visible and button.is_visible_in_tree())
			button.grab_focus()
			for _frame in range(4):
				await process_frame
			assert(home_scroll.get_global_rect().grow(2).encloses(button.get_global_rect()))
		for app in ["saves", "messages", "assistance", "courses", "album", "notes", "market", "trade", "wallet", "health", "clubs", "party", "combat", "forums"]:
			phone.call("_open_app", app, app)
			if app == "saves":
				await bridge.campus_persistence_completed
			for _frame in range(8):
				await process_frame
			var viewport := close.get_viewport_rect()
			assert(viewport.encloses(back.get_global_rect()), "back cropped: " + app)
			assert(viewport.encloses(close.get_global_rect()), "close cropped: " + app)
			assert(viewport.encloses(scroll.get_global_rect()), "body cropped: " + app)
			assert(scroll.get_h_scroll_bar().max_value <= scroll.size.x + 1, "horizontal overflow: " + app)
			if app == "combat":
				assert((phone.get("_combat_formation_detail") as Control).size.y >= 160)
				assert(scroll.get_v_scroll_bar().max_value > scroll.size.y)
			if app == "courses":
				assert(not (phone.get("_content") as RichTextLabel).text.contains("ORIENTATION_OR_CLASS"))
			scroll.scroll_vertical = 10000
			await process_frame
			assert(viewport.encloses(back.get_global_rect()))
			assert(viewport.encloses(close.get_global_rect()))
			back.pressed.emit()
			assert((phone.get("_home") as Control).visible and paused)
		close.pressed.emit()
		assert(not phone.call("is_open") and not paused)
	phone.call("_set_open", true)
	phone.call("_open_app", "settings", "接口设置")
	assert(root.get_node("InterfaceSettings").call("is_open"))
	root.get_node("InterfaceSettings").call("_close")
	assert(not paused)
	assert(bridge.get("campus_snapshot").player.action_budget == budget)
	root.size = Vector2i(1280, 720)
	phone.call("_set_open", true)
	phone.get("_home_scroll").scroll_vertical = 0
	print("CAMPUS_PHONE_LAYOUT_OK fifteen_apps three_sizes fixed_navigation readable_forms searchable_catalog keyboard_reachability no_action_cost")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
