extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _wait_idle(bridge: Node) -> void:
	for _attempt in range(400):
		if not bridge.call("is_campus_busy"): return
		await create_timer(0.05).timeout
	assert(false, "phone request did not become idle")


func _run() -> void:
	create_timer(100).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "messages", "校园通讯")
	var initial: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	var target := ""
	for contact in initial.messaging.contacts:
		if contact.display_name == "联系状态验收": target = String(contact.actor_id)
	assert(not target.is_empty())
	phone.set("_selected_message_contact_id", target)
	phone.call("_refresh_message_thread")
	await _wait_idle(bridge)
	for index in range(2):
		phone.get("_message_input").text = "第 %d 次联系，方便的时候回复我。" % index
		phone.get("_message_send_action").pressed.emit()
		var reply: Array = await bridge.campus_phone_message_completed
		assert(reply[0] and reply[1].result.code == "reply_pending")
		assert(phone.get("_message_feedback").text.contains("暂未收到回复"))
		assert(phone.get("_message_log").text.contains("尚不能据此确认失踪"))
		await _wait_idle(bridge)
	var pending: Dictionary = bridge.get("campus_snapshot")
	assert(pending.clock == initial.clock)
	assert(pending.action_economy == initial.action_economy)
	assert(pending.messaging.threads[target].messages.size() == 2)
	assert(pending.messaging.threads[target].contact_status.distinct_phases == 1)
	phone.call("_set_open", false)
	for _index in range(2):
		await _wait_idle(bridge)
		bridge.call("advance_campus_phase")
		var advanced: Array = await bridge.campus_phase_advanced
		assert(advanced[0], "real phase advancement failed")
	await _wait_idle(bridge)
	phone.call("_set_open", true)
	phone.call("_open_app", "messages", "校园通讯")
	phone.set("_selected_message_contact_id", target)
	phone.call("_refresh_message_thread")
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(after.messaging.threads[target].contact_status.status == "contact_resumed")
	assert(phone.get("_message_log").text.contains("不代表此前的问题或委托已经解决"))
	var acknowledgments := 0
	for message in after.messaging.threads[target].messages:
		if message.source == "deferred_acknowledgment": acknowledgments += 1
	assert(acknowledgments == 1)
	await _wait_idle(bridge)
	phone.get("_message_input").text = "现在继续聊吧。"
	phone.get("_message_send_action").pressed.emit()
	var continued: Array = await bridge.campus_phone_message_completed
	assert(continued[0] and continued[1].result.payload.reply_messages.size() == 1)
	await _wait_idle(bridge)
	print("CAMPUS_CONTACT_FLOW_OK real_phone_buttons unanswered_not_missing no_quota free real_dawn one_ack continued_dialogue explicit_incident no_api")
	quit(0)
