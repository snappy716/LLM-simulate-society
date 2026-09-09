extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _wait_idle(bridge: Node) -> void:
	for _attempt in range(400):
		if not bridge.call("is_campus_busy"): return
		await create_timer(0.05).timeout
	assert(false, "lead request remained busy")


func _run() -> void:
	create_timer(100).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	var initial: Dictionary = bridge.campus_snapshot.duplicate(true)
	var target := ""
	for contact in initial.messaging.contacts:
		if contact.display_name == "地点线索验收对象": target = contact.actor_id
	assert(not target.is_empty())
	var option: Dictionary = initial.messaging.check_options_by_contact[target][0]
	assert(option.lead is Dictionary)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "messages", "校园通讯")
	phone.set("_selected_message_contact_id", target)
	phone.call("_refresh_message_thread")
	await _wait_idle(bridge)
	var picker: OptionButton = phone.get("_contact_check_picker")
	assert(picker.item_count == 4)
	assert(picker.get_item_metadata(picker.selected) == option.location_id)
	assert(phone.get("_message_log").text.contains("寻访选择依据"))
	assert(phone.get("_message_log").text.contains("不保证现在仍在那里"))
	phone.get("_message_input").text = "方便时告诉我近况。"
	phone.get("_message_send_action").pressed.emit()
	var sent: Array = await bridge.campus_phone_message_completed
	assert(sent[0] and sent[1].result.code == "reply_pending")
	await _wait_idle(bridge)
	assert(not phone.get("_contact_check_button").disabled)
	phone.get("_contact_check_button").pressed.emit()
	var published: Array = await bridge.campus_phone_message_completed
	assert(published[0], JSON.stringify(published[1].get("result", {})))
	await _wait_idle(bridge)
	var task_id: String = published[1].result.payload.task_id
	var task: Dictionary = bridge.campus_snapshot.tasks[task_id]
	assert(task.scene_id == option.location_id)
	assert(task.contact_inquiry.decision_basis.source_claim_id == option.lead.claim_id)
	assert(bridge.campus_snapshot.clock == initial.clock)
	assert(bridge.campus_snapshot.player.action_budget == initial.player.action_budget)
	assert(phone.get("_contact_check_button").disabled)
	phone.call("_open_app", "forums", "双层论坛")
	phone.call("_open_task_detail", task_id)
	await _wait_idle(bridge)
	assert(phone.get("_forum_detail").text.contains("选择依据"))
	assert(phone.get("_forum_detail").text.contains("过去记录"))
	print("CAMPUS_CONTACT_LEADS_FLOW_OK actual_work_evidence permitted_share personal_basis public_points real_phone_request dated_not_live no_action_cost no_api explicit_incapacity")
	quit(0)
