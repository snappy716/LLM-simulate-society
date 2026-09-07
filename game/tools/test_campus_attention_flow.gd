extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(100).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.1).timeout
	var initial: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	assert(not initial.is_empty())
	assert(initial.clock.day == 1 and initial.clock.phase == "morning")
	var observations: Array[Dictionary] = []
	bridge.campus_snapshot_updated.connect(func(snapshot: Dictionary):
		var totals := {"viewed": 0, "considering": 0, "claimed": 0}
		for task in snapshot.tasks.values():
			totals.viewed += int(task.viewer_count)
			totals.considering += int(task.considering_count)
			if task.state == "locked" and not task.owned_by_player: totals.claimed += 1
		observations.append(totals)
	)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone = current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "forums", "双层论坛")
	assert(paused) # The phone pauses the scene, not the authoritative forum timer.
	await create_timer(12).timeout
	var before_close: int = bridge.get("campus_snapshot").revision
	phone.call("_set_open", false)
	await create_timer(8).timeout
	assert(int(bridge.get("campus_snapshot").revision) > before_close)
	phone.call("_set_open", true)
	phone.call("_open_app", "messages", "校园通讯")
	var composer: LineEdit = phone.get("_message_input")
	composer.text = "这是一条尚未发送的草稿"
	composer.grab_focus()
	await create_timer(9).timeout
	assert(composer.text == "这是一条尚未发送的草稿")
	assert(root.gui_get_focus_owner() == composer)
	bridge.get("_social_timer").stop()
	while bridge.call("is_campus_busy"):
		await create_timer(0.1).timeout
	assert(observations.any(func(row: Dictionary): return row.viewed > 0 and row.claimed == 0))
	assert(observations.any(func(row: Dictionary): return row.considering > 0))
	assert(observations.any(func(row: Dictionary): return row.claimed > 1))
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(after.clock == initial.clock)
	assert(after.player.action_budget == initial.player.action_budget)
	assert(not after.forums.night.enabled)
	var task_id := ""
	for key in after.tasks:
		if after.tasks[key].state == "locked" and not after.tasks[key].owned_by_player:
			task_id = key
			break
	assert(not task_id.is_empty())
	phone.call("_open_app", "forums", "双层论坛")
	phone.call("_open_task_detail", task_id)
	await create_timer(1).timeout
	assert(String(phone.get("_forum_detail").text).contains("接下了任务"))
	assert(phone.get("_forum_primary_action").disabled)
	phone.get("_forum_detail").scroll_to_line(maxi(0, phone.get("_forum_detail").get_line_count() - 5))
	if OS.get_environment("GODOT_ATTENTION_INSPECT") == "1":
		print("CAMPUS_ATTENTION_INSPECT_READY")
		await create_timer(45).timeout
	print("CAMPUS_ATTENTION_FLOW_OK real_timer phone_open_and_closed staged_views_consideration_claims no_clock_or_action_cost")
	quit(0)
