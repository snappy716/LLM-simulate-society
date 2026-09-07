extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	var task_id := ""
	for task in snapshot.tasks.values():
		if task.get("state") == "completed" and not (task.get("night_site", {}) as Dictionary).is_empty():
			task_id = task.task_id
	assert(not task_id.is_empty())
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var presentation := root.get_node("CampusPresentation")
	var location_id := String(snapshot.player.current_location_id)
	var region_id := String(snapshot.places[location_id].get("region_id", location_id))
	assert(region_id in (presentation.call("get_map") as Dictionary).visible_region_ids, "Actual player location must match the background after initial connection")
	var saved_map := String(presentation.get("current_map_id"))
	presentation.call("select_map", "campus_gate")
	bridge.campus_snapshot_updated.emit(snapshot)
	await process_frame
	assert(presentation.get("current_map_id") == saved_map, "Reconnection/escort snapshots must correct stale background")
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "forums", "双层论坛")
	phone.call("_set_forum_channel", "night")
	phone.call("_open_task_detail", task_id)
	assert(phone.get("_forum_detail_view").is_visible_in_tree())
	assert(phone.get("_forum_detail").text.contains("实际现场"))
	assert(phone.get("_forum_detail").text.contains("现场目标已实际完成"))
	assert(phone.get("_forum_primary_action").disabled)
	assert(not phone.get("_forum_abandon_action").visible)
	assert(not snapshot.tasks[task_id].night_site.can_follow_through)
	phone.get("_forum_detail").get_v_scroll_bar().value = phone.get("_forum_detail").get_v_scroll_bar().max_value
	if OS.get_environment("GODOT_SITES_INSPECT") == "1":
		print("CAMPUS_SITES_INSPECT_READY")
		await create_timer(45).timeout
	print("CAMPUS_SITES_FLOW_OK actual_site actual_combat resolved_objective reward no_duplicate visible_detail")
	quit(0)
