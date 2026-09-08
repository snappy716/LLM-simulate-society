extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(110).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("Overnight transition timeout")
			quit(1)
	)
	var bridge := root.get_node("SimulationBridge")
	var transition := root.get_node("OvernightTransition")
	for _attempt in range(400):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())
	var count := int(bridge.get("_campus_command_counter"))
	# Real offline server, including the overnight command and updated snapshot.
	for phase in ["afternoon", "evening", "late_night", "morning"]:
		bridge.advance_campus_phase()
		assert(transition.is_active() == (phase == "morning"))
		assert(paused == (phase == "morning"))
		assert((bridge.get("_campus_request") as HTTPRequest).timeout == (180.0 if phase == "morning" else 30.0))
		if phase == "morning":
			# Duplicate calls are rejected without closing the pending overnight visual.
			bridge.advance_campus_phase()
			assert(transition.is_active() and transition.get("_waiting"))
		var reply: Array = await bridge.campus_phase_advanced
		assert(reply[0], "real phase request failed: %s" % reply[1])
		assert(bridge.get("campus_snapshot").clock.phase == phase)
		assert((bridge.get("_campus_request") as HTTPRequest).timeout == 30.0)
		await create_timer(0.55).timeout
		assert(not transition.is_active() and not paused)
	assert(bridge.get("campus_snapshot").clock.day == 2)
	assert(int(bridge.get("_campus_command_counter")) == count + 4)
	count += 4
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := get_first_node_in_group("campus_phone_ui")
	var settings := root.get_node("InterfaceSettings")
	# Held-response presentation fixture: no backend action or paid API is sent.
	for resolution in [Vector2i(960, 540), Vector2i(1280, 720), Vector2i(1920, 1080)]:
		root.size = resolution
		bridge.campus_phase_started.emit({"day": 2, "phase": "late_night"})
		await process_frame
		await process_frame
		var sky: Control = transition.get("_sky")
		var content: Control = transition.get("_content")
		assert(sky.is_visible_in_tree() and paused)
		assert(sky.get_global_rect().encloses(content.get_global_rect()))
		var time_before := float(sky.get("elapsed"))
		await create_timer(0.12).timeout
		assert(float(sky.get("elapsed")) > time_before, "animation must run while scene is paused")
		for keycode in [KEY_T, KEY_M, KEY_ESCAPE, KEY_E]:
			var event := InputEventKey.new()
			event.keycode = keycode
			event.pressed = true
			Input.parse_input_event(event)
			await process_frame
		assert(not phone.is_open() and not settings.is_open())
		assert(transition.is_active() and paused)
		bridge.campus_phase_advanced.emit(false, {"result": {"message": "测试：日程暂时无法结算"}})
		await process_frame
		await process_frame
		assert(transition.is_active())
		assert((transition.get("_detail") as Label).text.contains("日程暂时无法结算"))
		var dismiss: Button = transition.get("_dismiss")
		assert(dismiss.visible and sky.get_global_rect().encloses(dismiss.get_global_rect()))
		dismiss.pressed.emit()
		assert(not transition.is_active() and not paused)
	# Preserve an existing modal pause and keyboard focus.
	phone.call("_set_open", true)
	assert(phone.is_open() and paused)
	var previous_focus := root.gui_get_focus_owner()
	bridge.campus_phase_started.emit({"day": 2, "phase": "late_night"})
	bridge.campus_phase_advanced.emit(false, {"error": "测试：连接中断，操作结果尚未确认"})
	var escape := InputEventKey.new()
	escape.keycode = KEY_ESCAPE
	escape.pressed = true
	Input.parse_input_event(escape)
	await process_frame
	assert(not transition.is_active() and paused and phone.is_open())
	assert(not settings.is_open())
	assert(root.gui_get_focus_owner() == previous_focus)
	phone.call("_set_open", false)
	# An inconsistent success must not pretend dawn is ready or trap the player.
	bridge.campus_phase_started.emit({"day": 2, "phase": "late_night"})
	bridge.campus_phase_advanced.emit(true, {"ok": true})
	assert((transition.get("_detail") as Label).text.contains("日期与预期不一致"))
	transition.call("_close")
	# Test the actual transport failure callback and reconnect without replay.
	bridge.campus_phase_started.emit({"day": 2, "phase": "late_night"})
	bridge.set("_campus_pending_operation", "advance_phase")
	bridge.set("_campus_busy", true)
	bridge.call("_on_campus_request_completed", HTTPRequest.RESULT_TIMEOUT, 0, PackedStringArray(), PackedByteArray())
	assert((transition.get("_detail") as Label).text.contains("尚未确认"))
	assert(not bool(bridge.get("connected")))
	transition.call("_close")
	(bridge.get("_retry_timer") as Timer).stop()
	bridge.call("_request_snapshot")
	await bridge.campus_snapshot_updated
	assert(bridge.get("campus_snapshot").clock.day == 2)
	assert(int(bridge.get("_campus_command_counter")) == count)
	assert(not paused)
	print("CAMPUS_OVERNIGHT_FLOW_OK real_dawn intraday_skip duplicate_guard animated_wait three_sizes input_block modal_pause focus_restore failure inconsistent_snapshot timeout reconnect no_replay")
	if "--keep-open" in OS.get_cmdline_user_args():
		root.size = Vector2i(1280, 720)
		bridge.campus_phase_started.emit({"day": 2, "phase": "late_night"})
		print("OVERNIGHT_INSPECT_READY held_response_visual_fixture no_command_sent")
		await create_timer(180).timeout
		bridge.campus_phase_advanced.emit(false, {"error": "演示等待结束：这是过场展示测试，没有再次推进日期。"})
		await create_timer(15).timeout
		transition.call("_close")
	quit(0)
