extends SceneTree
## Real HTTP commands and rendered phone controls, isolated test save/settings.


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func(): quit(1))
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
	phone.call("_set_open", true)
	phone.call("_open_app", "party", "行动小队")
	var reserve: Button = phone.get("_departure_reserve")
	var cancel: Button = phone.get("_departure_cancel")
	assert(not reserve.disabled)
	reserve.pressed.emit()
	assert(reserve.disabled and cancel.disabled)
	var reserved = await bridge.campus_party_operation_completed
	assert(reserved[0], "reservation failed")
	assert(phone.get("_party_detail").text.contains("出击预约：第 1 天"))
	assert(not reserve.disabled)
	var player: Dictionary = bridge.get("campus_snapshot").player
	assert(player.action_budget.major_remaining == 1)
	cancel.pressed.emit()
	var cancelled = await bridge.campus_party_operation_completed
	assert(cancelled[0])
	assert(not phone.get("_party_detail").text.contains("出击预约："))
	reserve.pressed.emit()
	await bridge.campus_party_operation_completed
	for _phase in range(2):
		bridge.call("advance_campus_phase")
		var advanced = await bridge.campus_phase_advanced
		assert(advanced[0])
	assert(bridge.get("campus_snapshot").player.action_budget.major_remaining == 1)
	phone.call("_refresh_party_page")
	assert(phone.get("_party_detail").text.contains("出击预约：第 1 天"))
	assert(phone.get("_departure_picker").get_global_rect().end.y <= root.get_visible_rect().size.y)
	print("CAMPUS_DEPARTURE_FLOW_OK real_http reserve_cancel phase_hold pending_release visible_controls")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
