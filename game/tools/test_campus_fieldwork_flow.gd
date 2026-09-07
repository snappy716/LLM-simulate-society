extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(95).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	var initial: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	var task_id := ""
	for task in initial.tasks.values():
		if task.get("owned_by_player", false) and task.get("resolution_kind") == "field_recon":
			task_id = task.task_id
	assert(not task_id.is_empty())
	assert(initial.combat.owned_night_tasks.is_empty(), "Recon cannot silently become combat")
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "forums", "双层论坛")
	phone.call("_set_forum_channel", "night")
	phone.call("_open_task_detail", task_id)
	assert(phone.get("_forum_detail_view").is_visible_in_tree())
	assert(phone.get("_forum_primary_action").text.contains("深入搜查"))
	phone.get("_forum_primary_action").pressed.emit()
	await process_frame
	var panel: Control = phone.get("_investigation_root")
	assert(panel.visible)
	assert(not panel.get("search").disabled)
	panel.get("search").pressed.emit()
	assert(panel.get("search").disabled)
	var searched = await bridge.campus_investigation_operation_completed
	assert(searched[0], JSON.stringify(searched))
	await process_frame
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(snapshot.clock == initial.clock)
	assert(snapshot.tasks[task_id].fieldwork.ready_to_report)
	var physical_count := 0
	for entry in snapshot.investigation.entries:
		if entry.claim.get("evidence_kind") == "field_measurement":
			physical_count += 1
	assert(physical_count >= 2)
	phone.call("_open_app", "forums", "双层论坛")
	phone.call("_set_forum_channel", "night")
	phone.call("_open_task_detail", task_id)
	assert(phone.get("_forum_detail_view").is_visible_in_tree())
	assert(phone.get("_forum_primary_action").text.contains("提交实地报告"))
	phone.get("_forum_primary_action").pressed.emit()
	assert(phone.get("_forum_primary_action").disabled)
	var submitted = await bridge.campus_task_operation_completed
	assert(submitted[0], JSON.stringify(submitted))
	await process_frame
	snapshot = bridge.get("campus_snapshot")
	assert(snapshot.clock == initial.clock)
	assert(snapshot.tasks[task_id].state == "completed")
	assert(phone.get("_forum_primary_action").disabled)
	assert(phone.get("_forum_detail").text.contains("实地核对记录"))
	assert(phone.get("_forum_detail").text.contains("未推定幕后原因"))
	phone.get("_forum_detail").get_v_scroll_bar().value = phone.get("_forum_detail").get_v_scroll_bar().max_value
	if OS.get_environment("GODOT_FIELDWORK_INSPECT") == "1":
		print("CAMPUS_FIELDWORK_INSPECT_READY")
		await create_timer(45).timeout
	print("CAMPUS_FIELDWORK_FLOW_OK real_site search_two_readings report no_combat reward no_extra_time pending")
	quit(0)
