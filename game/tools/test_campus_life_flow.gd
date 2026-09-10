extends SceneTree
## Actual phone -> HTTP -> shared ledger -> effects; explicit route fixture.

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
		if picker.get_item_metadata(index) == "life:1:campus_walk":
			picker.select(index)
			picker.item_selected.emit(index)
			found = true
	assert(found and not panel.get("enroll").disabled and panel.get("attend").disabled)
	var before: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	panel.get("enroll").pressed.emit()
	assert(panel.get("enroll").disabled and picker.disabled)
	panel.get("enroll").pressed.emit() # Explicit duplicate-click fixture.
	var enrolled = await bridge.campus_life_operation_completed
	assert(enrolled[0] and not panel.get("attend").disabled)
	assert(panel.get("detail").text.contains("已报名的校园活动"))
	var booked: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	assert(before.clock == booked.clock and before.action_economy == booked.action_economy)
	panel.get("cancel").pressed.emit()
	var cancelled = await bridge.campus_life_operation_completed
	assert(cancelled[0] and panel.get("attend").disabled and not panel.get("enroll").disabled)
	panel.get("enroll").pressed.emit()
	var rebooked = await bridge.campus_life_operation_completed
	assert(rebooked[0])
	panel.get("attend").pressed.emit()
	var attended = await bridge.campus_life_operation_completed
	assert(attended[0])
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(before.clock == after.clock)
	assert(int(after.player.action_budget.major_remaining) == int(before.player.action_budget.major_remaining) - 1)
	assert(panel.get("participation").text.contains("已实际参加"))
	assert(panel.get("attend").disabled and panel.get("enroll").disabled and panel.get("cancel").disabled)
	bridge.call("operate_campus_life", "ATTEND_CAMPUS_OPPORTUNITY", {"session_id": "life:1:campus_walk"})
	var repeat = await bridge.campus_life_operation_completed
	assert(not repeat[0])
	assert(after.action_economy == bridge.get("campus_snapshot").action_economy)
	for viewport_size in [Vector2i(1280,720), Vector2i(1600,900), Vector2i(1920,1080)]:
		root.size = viewport_size
		await process_frame
		assert(panel.size.x > 0 and not panel.get("opportunity_detail").text.is_empty())
		assert(panel.get("opportunity").size.x <= panel.size.x + 1)
		assert(panel.get("attend").size.x <= panel.size.x + 1)
	print("CAMPUS_LIFE_FLOW_OK actual_ui_http enrollment_cancel_rebook actual_attendance one_action duplicate_guard private_history three_sizes explicit_route_fixture no_api")
	quit(0)
