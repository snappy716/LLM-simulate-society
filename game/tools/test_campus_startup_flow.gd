extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("campus startup test timed out")
			quit(1)
	)
	assert(not OS.get_environment("GODOT_SIM_SETTINGS_PATH").is_empty(), "use an isolated settings file")
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())
	for retired_method in ["advance_time", "trade", "use_item", "perform_action"]:
		assert(not bridge.has_method(retired_method), "retired town request must not return")
	for retired_signal in ["snapshot_updated", "advance_state_changed", "trade_completed", "item_use_completed", "action_completed"]:
		assert(not bridge.has_signal(retired_signal), "retired town signal must not return")
	var main_path := String(ProjectSettings.get_setting("application/run/main_scene"))
	assert(main_path == "res://scenes/ui/campus_title.tscn")
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "settings", "接口设置")
	var settings := root.get_node("InterfaceSettings")
	assert(settings.call("is_open"))
	assert(paused and not phone.call("is_open"))
	# A gameplay hotkey must not open a second overlay over API settings.
	var hotkey := InputEventAction.new()
	hotkey.action = "toggle_phone"
	hotkey.pressed = true
	phone.call("_unhandled_input", hotkey)
	assert(not phone.call("is_open"))
	(settings.get_node("Panel/Window/SaveApply") as Button).pressed.emit()
	var configured = await bridge.interface_configured
	assert(bool(configured[0]), "offline configuration failed: %s" % configured[1])
	assert(FileAccess.file_exists(OS.get_environment("GODOT_SIM_SETTINGS_PATH")))
	assert(not bool(configured[1].status.configured))
	assert((settings.get("status") as Label).text.contains("接口已应用"))
	settings.call("_add_profile")
	(settings.get("base_url") as LineEdit).text = "https://api.deepseek.com"
	(settings.get("model") as LineEdit).text = "deepseek-v4-flash"
	(settings.get("api_key") as LineEdit).text = "fake-no-paid-request"
	(settings.get("request_timeout") as SpinBox).value = 30
	assert((settings.get("request_concurrency") as SpinBox).value == 10)
	(settings.get("request_concurrency") as SpinBox).value = 6
	settings.call("_save_and_apply")
	var deepseek = await bridge.interface_configured
	assert(bool(deepseek[0]))
	assert(deepseek[1].status.thinking_mode == "disabled")
	assert(deepseek[1].status.timeout_seconds == 30)
	assert(deepseek[1].max_concurrent_requests == 6)
	assert(deepseek[1].status.last_result.state == "untested")
	assert((settings.get("status") as Label).text.contains("尚未请求验证"))
	var selected_profile := int(settings.get("selected_index"))
	settings.call("_load_profiles")
	settings.call("_select_profile", selected_profile)
	assert((settings.get("request_concurrency") as SpinBox).value == 6)
	settings.call("_select_profile", 0)
	settings.call("_save_and_apply")
	await bridge.interface_configured
	settings.call("_close")
	assert(not paused)
	var escape := InputEventAction.new()
	escape.action = "ui_cancel"
	escape.pressed = true
	var menu := root.get_node("SystemMenu")
	menu.call("_input", escape)
	assert(menu.is_open() and paused and not settings.is_open())
	menu.call("_input", escape)
	assert(not menu.is_open() and not paused)
	phone.call("_set_open", true)
	phone.call("_open_app", "settings", "接口设置")
	print("CAMPUS_STARTUP_FLOW_OK campus_default campus_handshake offline_settings modal_guard stable_user_path")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
