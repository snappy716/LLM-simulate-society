extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _wait_idle(bridge: Node) -> void:
	for _attempt in range(400):
		if not bridge.call("is_campus_busy"): return
		await create_timer(0.05).timeout
	assert(false, "inquiry request stayed busy")


func _run() -> void:
	create_timer(100).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	var initial: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	var task_id := ""
	var target := ""
	for task in initial.tasks.values():
		if task.get("resolution_kind") == "contact_inquiry": task_id = task.task_id
	for contact in initial.messaging.contacts:
		if contact.display_name == "寻访对象验收": target = contact.actor_id
	assert(not task_id.is_empty() and not target.is_empty())
	assert(not initial.tasks[task_id].contact_inquiry.has("target_name"))
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
	assert(phone.get("_contact_check_button").disabled)
	phone.get("_message_input").text = "方便时回我一下。"
	phone.get("_message_send_action").pressed.emit()
	var sent: Array = await bridge.campus_phone_message_completed
	assert(sent[0] and sent[1].result.code == "reply_pending")
	await _wait_idle(bridge)
	assert(not phone.get("_contact_check_button").disabled)
	phone.get("_contact_check_button").pressed.emit()
	var published: Array = await bridge.campus_phone_message_completed
	assert(published[0] and published[1].result.payload.action_class == "free")
	assert(phone.get("_message_feedback").text.contains("寻访已发布"))
	await _wait_idle(bridge)
	phone.call("_open_app", "forums", "双层论坛")
	phone.call("_open_task_detail", task_id)
	assert(phone.get("_forum_detail_view").is_visible_in_tree())
	await _wait_idle(bridge)
	phone.get("_forum_primary_action").pressed.emit()
	var claimed: Array = await bridge.campus_task_operation_completed
	assert(claimed[0] and claimed[2] == "CLAIM_FORUM_TASK")
	await _wait_idle(bridge)
	assert(phone.get("_forum_detail").text.contains("寻访对象验收"))
	assert(phone.get("_forum_primary_action").text.contains("实地核对"))
	var before: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	phone.get("_forum_primary_action").pressed.emit()
	var checked: Array = await bridge.campus_task_operation_completed
	assert(checked[0], JSON.stringify(checked[1].get("result", {})))
	assert(checked[1].result.payload.contact_report.seen == false)
	await _wait_idle(bridge)
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(after.clock == initial.clock)
	assert(after.tasks[task_id].state == "completed")
	assert(after.player.action_budget.major_remaining == before.player.action_budget.major_remaining - 1)
	assert(phone.get("_forum_detail").text.contains("不能据此断定失踪"))
	assert(phone.get("_forum_primary_action").disabled)
	print("CAMPUS_INQUIRY_FLOW_OK actual_phone_publish actual_forum_claim private_target physical_report real_action_cost no_fake_missing explicit_incident no_api")
	quit(0)
