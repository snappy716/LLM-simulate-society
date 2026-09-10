extends SceneTree
## Real scene + phone commands; no client score or attendance injection.

func event_session() -> String:
	return "life:3:observation_challenge"

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	create_timer(90).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "agenda", "日程与约定")
	var panel: Node = phone.get("_agenda_root")
	var picker: OptionButton = panel.get("opportunity")
	var found := false
	for index in range(picker.item_count):
		if picker.get_item_metadata(index) == event_session():
			picker.select(index)
			picker.item_selected.emit(index)
			found = true
	assert(found)
	assert(panel.get("event_club").visible)
	assert(not panel.get("event_support").button_pressed)
	assert(panel.get("event_support").disabled)
	assert(panel.get("opportunity_detail").text.contains("准备不保证获胜"))
	var before: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	panel.get("enroll").pressed.emit()
	var result = await bridge.campus_life_operation_completed
	assert(result[0])
	assert(before.clock == bridge.get("campus_snapshot").clock)
	assert(before.action_economy == bridge.get("campus_snapshot").action_economy)
	assert(panel.get("event_club").disabled)
	assert(not panel.get("attend").disabled)
	panel.get("attend").pressed.emit()
	result = await bridge.campus_life_operation_completed
	assert(result[0])
	assert(before.clock == bridge.get("campus_snapshot").clock)
	assert(panel.get("participation").text.contains("本人成绩依据"))
	assert(panel.get("participation").text.contains("当前不是最终排名"))
	assert(panel.get("attend").disabled)
	bridge.call("operate_campus_life", "ATTEND_CAMPUS_OPPORTUNITY", {"session_id": event_session(), "score": 999})
	result = await bridge.campus_life_operation_completed
	assert(not result[0])
	bridge.call("advance_campus_phase")
	var advanced = await bridge.campus_phase_advanced
	assert(advanced[0])
	phone.call("_open_app", "agenda", "日程与约定")
	panel.call("refresh")
	assert(panel.get("event_results").text.contains("正式结果"))
	assert(panel.get("event_results").text.contains("不会自动添加联系人"))
	var finalized := false
	for entry in bridge.get("campus_snapshot").agenda.life.history:
		if entry.session_id == event_session():
			assert(entry.result.event.finalized)
			assert(int(entry.result.event.resource_cost) == 0)
			finalized = true
	assert(finalized)
	print("CAMPUS_EVENTS_FLOW_OK %s real_scene_phone_http enrollment_actual_performance_end_phase_result private_breakdown no_auto_resource_spend no_duplicate no_api" % event_session())
	quit(0)
