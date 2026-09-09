extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(100).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	var initial: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	assert(initial.clock.day == 3)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	await process_frame
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	var npc: Node
	for node in current_scene.get_node("NpcMovementLayer").get_children():
		if node.has_method("get_campus_profile") and String(node.call("get_campus_profile").get("display_name", "")) == "后续关怀验收对象": npc = node
	assert(npc != null)
	current_scene.get_node("Player").global_position = npc.global_position
	inspector.call("inspect_npc", npc)
	while bridge.call("is_campus_busy"): await create_timer(0.05).timeout
	inspector.get("_plan_button").pressed.emit()
	var result: Array = await bridge.campus_goal_operation_completed
	assert(result[0], JSON.stringify(result))
	assert(inspector.get("_details").text.contains("继续学习"))
	assert(inspector.get("_details").text.contains("本人告知"))
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(initial.clock == after.clock and initial.action_economy == after.action_economy)
	var actor_id: String = inspector.get("_selected_profile").npc_id
	assert(not after.population[actor_id].has("long_term_plans"))
	assert(not after.population[actor_id].stated_plan.has("case_id"))
	assert(not after.population[actor_id].stated_plan.has("source_ids"))
	print("CAMPUS_FOLLOWUP_FLOW_OK real_support_real_dawn voluntary_continuing_study private_source_hidden free_inspection no_api explicit_initial_thresholds")
	quit(0)
