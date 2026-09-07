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
	var initial: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	await process_frame
	var layer := current_scene.get_node("NpcMovementLayer")
	var target: Node
	for node in layer.get_children():
		if node.has_method("get_campus_profile") and String(node.call("get_campus_profile").get("display_name", "")).contains("研习验收"):
			target = node
	assert(target != null, "real-case fixture NPC must be rendered")
	current_scene.get_node("Player").global_position = target.global_position
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	inspector.call("inspect_npc", target)
	var npc_id: String = inspector.get("_selected_profile").npc_id
	assert(initial.population[npc_id].stated_plan.is_empty())
	assert(inspector.get("_details").text.contains("尚未向对方询问"))
	# Chronicle request may still use the shared bridge; wait before starting the question.
	for _attempt in range(100):
		if not bridge.get("_campus_busy"):
			break
		await create_timer(0.05).timeout
	inspector.get("_plan_button").pressed.emit()
	assert(inspector.get("_plan_button").disabled)
	var result = await bridge.campus_goal_operation_completed
	assert(result[0], JSON.stringify(result))
	await process_frame
	assert(not inspector.get("_plan_button").disabled)
	assert(inspector.get("_details").text.contains("本人告知"))
	assert(inspector.get("_details").text.contains("当时的说法"))
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(snapshot.clock == initial.clock)
	assert(snapshot.population[npc_id].stated_plan.summary.contains("下一步"))
	assert(not snapshot.population[npc_id].stated_plan.has("topic_id"))
	assert(not snapshot.population[npc_id].has("long_term_plans"))
	# Real rejected request releases pending controls, preserving the previous statement.
	inspector.set("_plan_pending_target", npc_id)
	inspector.get("_plan_button").disabled = true
	bridge.call("ask_campus_npc_plan", "missing-npc")
	result = await bridge.campus_goal_operation_completed
	assert(not result[0])
	assert(not inspector.get("_plan_button").disabled)
	assert(inspector.get("_details").text.contains("本人告知"))
	inspector.get("_plan_button").pressed.emit()
	result = await bridge.campus_goal_operation_completed
	assert(result[0])
	await process_frame
	inspector.get("_details").scroll_to_line(12)
	inspector.get("_body_scroll").scroll_vertical = 0
	if OS.get_environment("GODOT_GOALS_INSPECT") == "1":
		print("CAMPUS_GOALS_INSPECT_READY")
		await create_timer(45).timeout
	print("CAMPUS_GOALS_FLOW_OK real_case volunteered_dated_plan private_ledger_hidden free_question pending_failure_release")
	quit(0)
