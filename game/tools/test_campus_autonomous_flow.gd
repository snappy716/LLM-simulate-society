extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.1).timeout
	var initial: Dictionary = bridge.get("campus_snapshot")
	assert(not initial.is_empty())
	assert(initial.clock.phase == "late_night")
	var task_id := ""
	for key in initial.tasks:
		var task: Dictionary = initial.tasks[key]
		for entry in task.get("history", []):
			if String(entry.get("message", "")).contains("实际卡牌战斗"):
				task_id = key
				break
		if not task_id.is_empty(): break
	assert(not task_id.is_empty())
	assert(not initial.tasks[task_id].owned_by_player)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone = current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "forums", "双层论坛")
	phone.call("_set_forum_channel", "night")
	phone.call("_open_task_detail", task_id)
	await process_frame
	var detail: RichTextLabel = phone.get("_forum_detail")
	assert(detail.text.contains("实际卡牌战斗"))
	assert(detail.text.contains("动态记录"))
	assert(phone.get("_forum_primary_action").disabled)
	assert(bridge.get("campus_snapshot").clock == initial.clock)
	assert(bridge.get("campus_snapshot").player.action_budget == initial.player.action_budget)
	phone.get("_app_scroll").scroll_vertical = 0
	detail.scroll_to_line(maxi(0, detail.get_line_count() - 10))
	if OS.get_environment("GODOT_AUTONOMOUS_INSPECT") == "1":
		print("CAMPUS_AUTONOMOUS_INSPECT_READY")
		await create_timer(45).timeout
	print("CAMPUS_AUTONOMOUS_FLOW_OK actual_npc_cards task_history no_player_help no_time_cost secret_forum_gate")
	quit(0)
