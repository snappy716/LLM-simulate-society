extends SceneTree
## Actual HTTP reservation/cancellation and rendered read-only calendar.


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())
	var initial: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "agenda", "日程与约定")
	var panel: Node = phone.get("_agenda_root")
	assert(panel.visible and panel.get("detail").text.contains("目前没有"))
	assert(not phone.get("_content").visible)
	panel.get_child(2).pressed.emit()
	assert(phone.get("_party_root").visible and not panel.visible)
	phone.get("_departure_reserve").pressed.emit()
	var reserved = await bridge.campus_party_operation_completed
	assert(reserved[0])
	phone.call("_open_app", "agenda", "日程与约定")
	assert(panel.get("detail").text.contains("全队出击预约"))
	assert(panel.get("detail").text.contains("第 1 天"))
	assert(panel.get("detail").text.contains("实际执行时核验"))
	assert(not phone.get("_party_root").visible)
	panel.get_child(2).pressed.emit()
	phone.get("_departure_cancel").pressed.emit()
	var cancelled = await bridge.campus_party_operation_completed
	assert(cancelled[0])
	phone.call("_open_app", "agenda", "日程与约定")
	assert(panel.get("detail").text.contains("目前没有"))
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(initial.clock == after.clock and initial.action_economy == after.action_economy)
	panel.get_child(3).pressed.emit()
	assert(phone.get("_message_root").visible and not panel.visible)
	print("CAMPUS_AGENDA_FLOW_OK real_http phone_home calendar reserve_cancel original_management no_time_cost no_api")
	quit(0)
