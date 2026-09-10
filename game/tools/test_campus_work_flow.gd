extends SceneTree

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	create_timer(90).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "agenda", "日程与约定")
	var panel: Node = phone.get("_agenda_root")
	var picker: OptionButton = panel.get("opportunity")
	for index in range(picker.item_count):
		if picker.get_item_metadata(index) == "life:1:canteen_part_time":
			picker.select(index)
			picker.item_selected.emit(index)
	assert(panel.get("opportunity_detail").text.contains("班次报酬 12"))
	assert(not panel.get("attend").disabled)
	var before: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	panel.get("attend").pressed.emit()
	var result = await bridge.campus_life_operation_completed
	assert(result[0])
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(before.clock == after.clock)
	assert(int(after.economy.balance) == int(before.economy.balance) + 12)
	assert(panel.get("participation").text.contains("实收 12 · 付款方：食堂窗口"))
	assert(panel.get("attend").disabled)
	bridge.call("operate_campus_life", "ATTEND_CAMPUS_OPPORTUNITY", {"session_id": "life:1:canteen_part_time"})
	result = await bridge.campus_life_operation_completed
	assert(not result[0])
	assert(after.economy.balance == bridge.get("campus_snapshot").economy.balance)
	print("CAMPUS_WORK_FLOW_OK actual_reserved_shift actual_ui_http_cash_transfer private_receipt no_double_pay no_api")
	quit(0)
