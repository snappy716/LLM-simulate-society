extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(100).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	var task_id := ""
	for task in snapshot.tasks.values():
		if task.get("state") == "completed" and not (task.get("afterimage", {}) as Dictionary).is_empty():
			task_id = task.task_id
			assert(not task.has("anomaly_case_id"))
	assert(not task_id.is_empty())
	assert(snapshot.tasks[task_id].night_site.victim_name == "")
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "forums", "双层论坛")
	phone.call("_set_forum_channel", "night")
	phone.call("_open_task_detail", task_id)
	assert(phone.get("_forum_detail_view").is_visible_in_tree())
	assert(phone.get("_forum_detail").text.contains("月相残像 · 不是人物本身"))
	assert(phone.get("_forum_detail").text.contains("外壳已切断，人物近况需本人确认"))
	assert(phone.get("_forum_primary_action").disabled)
	assert(not phone.get("_forum_abandon_action").visible)
	assert(bridge.get("campus_snapshot").clock == snapshot.clock)
	print("CAMPUS_AFTERIMAGE_FLOW_OK real_day_support_and_card_victory anonymous_site actual_containment not_person_recovery no_duplicate visible_forum no_api")
	quit(0)
