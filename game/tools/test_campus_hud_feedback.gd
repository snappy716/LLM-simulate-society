extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(60).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("HUD feedback timeout")
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
	var hud := current_scene.get_node("UI/PhasePanel")
	var status := hud.get("status_label") as Label
	var advance := hud.get("advance_button") as Button
	var night := hud.get("night_world_button") as Button
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	var counter := int(bridge.get("_campus_command_counter"))
	assert(status.text.contains("生命") and status.text.contains("专注"))
	assert(not status.text.contains("ORIENTATION_OR_CLASS"))
	assert(not status.text.contains("humanities_classroom_pool"))
	assert(not advance.disabled)
	assert(night.disabled and not night.tooltip_text.is_empty())
	bridge.set("_campus_busy", true)
	hud.call("_refresh_availability")
	assert(advance.disabled and advance.tooltip_text.contains("正在处理"))
	bridge.set("_campus_busy", false)
	var replies: Array = []
	bridge.campus_inventory_operation_completed.connect(func(success, result): replies.append([success, result]))
	# Transport fixtures only: no action is submitted or repeated by this test.
	for body in [PackedByteArray(), "invalid JSON".to_utf8_buffer()]:
		bridge.set("_campus_pending_operation", "inventory")
		bridge.call("_on_campus_request_completed", HTTPRequest.RESULT_CANT_CONNECT, 0, PackedStringArray(), body)
		assert(not bool(bridge.get("connected")))
		assert(advance.disabled and night.disabled)
		assert(status.text.contains("不会自动重复"))
		assert(not bool(replies.back()[0]))
		assert(String(replies.back()[1].error).contains("尚未确认"))
		(bridge.get("_retry_timer") as Timer).stop()
		bridge.call("_request_snapshot")
		await bridge.campus_snapshot_updated
		assert(bool(bridge.get("connected")))
		assert(not advance.disabled)
		assert(int(bridge.get("_campus_command_counter")) == counter)
		assert(int(bridge.get("campus_snapshot").revision) == int(snapshot.revision))
	bridge.set("_campus_pending_operation", "inventory")
	bridge.call("_on_campus_request_completed", HTTPRequest.RESULT_SUCCESS, 409, PackedStringArray(), JSON.stringify({"error": "任务已被其他人领取"}).to_utf8_buffer())
	assert(bool(bridge.get("connected")), "business rejection is not a disconnected server")
	assert(not bool(replies.back()[0]))
	assert(replies.back()[1].error == "任务已被其他人领取")
	assert(not advance.disabled)
	print("CAMPUS_HUD_FEEDBACK_OK readable_vitals busy_reason invalid_response reconnect no_command_replay business_rejection")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
