extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(60).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("inspector layout timeout")
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
	bridge.call("fast_travel_campus", "student_life_region")
	var result = await bridge.campus_fast_travel_completed
	assert(bool(result[0]))
	root.get_node("CampusPresentation").call("select_map", "living_area")
	await process_frame
	await process_frame
	var layer := current_scene.get_node("NpcMovementLayer")
	assert(layer.get_child_count() > 0)
	var npc := layer.get_child(0)
	current_scene.get_node("Player").global_position = npc.global_position
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	inspector.call("inspect_npc", npc)
	assert(inspector.call("is_open") and paused)
	var panel := inspector.get("_panel") as Control
	var scroll := inspector.get("_body_scroll") as ScrollContainer
	var close := inspector.get("_close_button") as Button
	var input := inspector.get("_dialogue_input") as LineEdit
	for window_size in [Vector2i(960, 540), Vector2i(1280, 720), Vector2i(1920, 1080)]:
		root.size = window_size
		for _frame in range(6):
			await process_frame
		var viewport := panel.get_viewport_rect()
		assert(viewport.encloses(panel.get_global_rect()), "panel outside viewport")
		assert(viewport.encloses(close.get_global_rect()), "close outside viewport")
		assert(close.visible and not close.disabled)
		assert(scroll.get_v_scroll_bar().max_value > scroll.size.y)
		input.grab_focus()
		await process_frame
		await process_frame
		assert(input.has_focus())
		assert(scroll.get_global_rect().intersects(input.get_global_rect()), "keyboard focus not revealed")
		scroll.scroll_vertical = 10000
		await process_frame
		assert(viewport.encloses(close.get_global_rect()), "footer moved with body")
	close.pressed.emit()
	assert(not inspector.call("is_open") and not paused)
	root.size = Vector2i(1280, 720)
	inspector.call("inspect_npc", npc)
	await process_frame
	assert(scroll.scroll_vertical == 0)
	print("CAMPUS_INSPECTOR_LAYOUT_OK real_npc three_sizes scroll keyboard fixed_close reset")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
