extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(60).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("theme flow timed out")
			quit(1)
	)
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())
	var theme_path := String(ProjectSettings.get_setting("gui/theme/custom"))
	var shared := load(theme_path) as Theme
	assert(shared != null)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	assert(paused)
	var overlay := phone.get("_overlay") as Control
	var shell := overlay.get_child(0) as PanelContainer
	assert(shell.theme_type_variation == &"CampusPhone")
	assert(shell.get_theme_stylebox("panel") == shared.get_stylebox("panel", "CampusPhone"))
	phone.call("_open_app", "market", "校园商城")
	await process_frame
	var button := Button.new()
	overlay.add_child(button)
	assert(button.get_theme_stylebox("normal") == shared.get_stylebox("normal", "Button"))
	assert(button.get_theme_stylebox("disabled") != button.get_theme_stylebox("normal"))
	assert(button.get_theme_stylebox("focus") != button.get_theme_stylebox("normal"))
	button.grab_focus()
	assert(button.has_focus())
	button.queue_free()
	var status := phone.get("_connection_label") as Label
	bridge.connection_state_changed.emit(false, "isolated UI test")
	assert(status.text == "模拟未连接")
	bridge.connection_state_changed.emit(true, "isolated UI test")
	assert(status.text == "模拟已连接")
	assert(status.tooltip_text.contains("不表示 LLM"))
	phone.call("_set_open", false)
	assert(not paused)
	var settings := root.get_node("InterfaceSettings")
	assert((settings.get_node("Panel/Window") as Control).get_theme_stylebox("panel") == shared.get_stylebox("panel", "Panel"))
	phone.call("_set_open", true)
	phone.call("_show_home")
	print("CAMPUS_THEME_FLOW_OK shared_theme phone settings button_states truthful_connection modal_restore")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
