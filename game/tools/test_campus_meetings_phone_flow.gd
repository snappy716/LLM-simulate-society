extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(100).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	var initial: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	var meeting: Dictionary = initial.social.anomaly_meetings[-1]
	assert(meeting.status == "pending")
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "messages", "手机消息")
	phone.set("_selected_message_contact_id", String(meeting.subject_id))
	phone.call("_refresh_message_page")
	while bridge.call("is_campus_busy"): await create_timer(0.05).timeout
	var panel: Node = phone.get("_support_appointment_panel")
	assert(panel.visible and panel.get("accept_button").visible)
	panel.get("accept_button").pressed.emit()
	var accepted: Array = await bridge.campus_investigation_operation_completed
	assert(accepted[0], JSON.stringify(accepted[1]))
	assert(panel.get("detail").text.contains("双方已确认"))
	assert(not panel.get("accept_button").visible)
	while bridge.call("is_campus_busy"): await create_timer(0.05).timeout
	panel.get("cancel_button").pressed.emit()
	var cancelled: Array = await bridge.campus_investigation_operation_completed
	assert(cancelled[0])
	assert(not panel.visible)
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(initial.clock == after.clock and initial.action_economy == after.action_economy)
	print("CAMPUS_MEETINGS_PHONE_FLOW_OK actual_incoming_request no_auto_accept phone_accept_cancel no_major_cost no_api")
	quit(0)
