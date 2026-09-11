extends SceneTree

func _initialize() -> void: call_deferred("_run")

func _run() -> void:
	create_timer(90).timeout.connect(func(): push_error("preferences timeout"); quit(1))
	var bridge := root.get_node("SimulationBridge")
	while not bridge.connected: await create_timer(0.05).timeout
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	for i in range(4): await process_frame
	var original: Dictionary = bridge.campus_snapshot.duplicate(true)
	var menu := root.get_node("SystemMenu")
	var preferences := root.get_node("CampusPreferences")
	menu.open_pause()
	menu._settings()
	var panel: Node = menu.body.get_child(menu.body.get_child_count() - 1)
	assert(panel.has_method("_set_preference"))
	panel._set_preference("volume", 0.35)
	panel._set_preference("muted", true)
	assert(is_equal_approx(AudioServer.get_bus_volume_linear(0), 0.35))
	assert(AudioServer.is_bus_mute(0))
	panel._set_preference("font_size", 18)
	assert((load("res://ui/themes/campus_theme.tres") as Theme).default_font_size == 18)
	panel._set_preference("fps", 30)
	assert(Engine.max_fps == 30)
	panel._set_preference("reduced_motion", true)
	var saved := ConfigFile.new()
	assert(saved.load(preferences.settings_path()) == OK)
	assert(saved.get_value("presentation", "reduced_motion") == true)
	for window_size in [Vector2i(960, 540), Vector2i(1280, 720), Vector2i(1920, 1080)]:
		root.size = window_size
		for i in range(8): await process_frame
		assert(root.get_visible_rect().encloses(menu.back.get_global_rect()))
	panel.probe.pressed.emit()
	assert(panel.probe_confirmation.visible)
	assert(not bridge.interface_probe_pending)
	panel.probe_confirmation.hide()
	panel.probe_confirmation.confirmed.emit()
	assert(bridge.interface_probe_pending)
	assert(bridge.is_campus_busy(), "probe must serialize against gameplay operations")
	bridge.probe_interface() # duplicate attempt must not create a second request
	var result: Dictionary = await bridge.interface_probe_completed
	assert(result.code == "offline" and not result.ok)
	assert(result.aggregate_usage.calls == 0)
	assert(not bridge.interface_probe_pending and not bridge.busy)
	assert(original.clock == bridge.campus_snapshot.clock and original.player == bridge.campus_snapshot.player)
	panel._set_preference("volume", 1.0)
	panel._set_preference("muted", false)
	panel._set_preference("font_size", 16)
	panel._set_preference("fps", 60)
	panel._set_preference("reduced_motion", false)
	menu.close_menu()
	print("CAMPUS_PREFERENCES_FLOW_OK real_audio_font_fps_local_save three_sizes explicit_probe duplicate_guard offline_no_charge no_world_change")
	quit(0)
