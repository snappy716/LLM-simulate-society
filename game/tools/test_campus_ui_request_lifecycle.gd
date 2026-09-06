extends SceneTree
## Deliberate UI state fixtures; no paid model calls or fabricated world events.


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
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
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "messages", "校园通讯")
	var target: String = phone.get("_selected_message_contact_id")
	assert(not target.is_empty())
	var input: LineEdit = phone.get("_message_input")
	input.text = "原消息"
	phone.set("_message_pending", "send")
	phone.set("_message_pending_target", target)
	phone.set("_message_sent_text", "原消息")
	phone.call("_refresh_message_page")
	assert(phone.get("_message_send_action").disabled)
	assert(phone.get("_message_contact_picker").disabled)
	var count: int = bridge.get("_campus_command_counter")
	phone.call("_send_phone_message_from_input", "重复消息")
	assert(bridge.get("_campus_command_counter") == count)
	input.text = "发送期间的新草稿"
	phone.call("_on_phone_message_completed", true, {"result": {"message": "发送成功"}}, "SEND_PHONE_MESSAGE", target)
	assert(input.text == "发送期间的新草稿")
	assert(not phone.get("_message_send_action").disabled)
	phone.set("_message_pending", "send")
	phone.set("_message_sent_text", input.text)
	phone.call("_on_phone_message_completed", false, {"error": "连接中断，结果未确认"}, "SEND_PHONE_MESSAGE", target)
	assert(input.text == "发送期间的新草稿")
	assert(phone.get("_message_feedback").text == "连接中断，结果未确认")
	phone.set("_message_pending", "send")
	phone.call("_on_phone_message_completed", true, {}, "SEND_PHONE_MESSAGE", target)
	assert(input.text.is_empty())
	assert(phone.get("_message_send_action").disabled)
	var original: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	var fixture := original.duplicate(true)
	fixture.messaging.contacts = []
	bridge.set("campus_snapshot", fixture)
	phone.call("_refresh_message_page")
	assert(phone.get("_message_log").text.contains("暂无联系人"))
	assert(phone.get("_message_send_action").disabled)
	bridge.set("campus_snapshot", original)
	phone.call("_open_app", "combat", "夜战部署")
	phone.set("_combat_pending", true)
	phone.call("_refresh_combat_page")
	assert(phone.get("_combat_prepare_action").disabled)
	assert(phone.get("_combat_prepare_action").tooltip_text == preload("res://scripts/ui/campus_ui_text.gd").PENDING_MESSAGE)
	phone.call("_send_combat_operation", "START_CARD_COMBAT", {})
	assert(bridge.get("_campus_command_counter") == count)
	phone.call("_on_combat_operation_completed", false, {"error": "阵型已变化"}, "START_CARD_COMBAT", "test")
	assert(not phone.get("_combat_pending"))
	assert(phone.get("_combat_feedback").text == "阵型已变化")
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	inspector.set("_selected_profile", {"npc_id": target, "display_name": "测试联系人"})
	inspector.set("_dialogue_pending_target", target)
	inspector.set("_dialogue_sent_text", "原对话")
	inspector.get("_dialogue_input").text = "新对话草稿"
	assert(inspector.get("_dialogue_button").disabled)
	inspector.call("_submit_dialogue")
	assert(bridge.get("_campus_command_counter") == count)
	inspector.call("_on_dialogue_completed", true, {"result": {"payload": {"reply_text": "测试回复"}}}, target)
	assert(inspector.get("_dialogue_input").text == "新对话草稿")
	assert(not inspector.get("_dialogue_button").disabled)
	assert(bridge.get("campus_snapshot") == original)
	phone.call("_open_app", "messages", "校园通讯")
	phone.get("_message_feedback").text = ""
	print("CAMPUS_UI_REQUEST_LIFECYCLE_OK explicit_ui_fixtures no_duplicate_commands drafts_preserved empty_contacts pending_release")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
