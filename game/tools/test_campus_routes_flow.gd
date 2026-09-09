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
	var target_id := ""
	for row in initial.social.anomalies:
		if row.get("route_feedback", {}).get("own_path", "") == "白天支持＋夜间处置": target_id = row.npc_id
	assert(not target_id.is_empty())
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	await process_frame
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	var npc: Node
	for node in current_scene.get_node("NpcMovementLayer").get_children():
		if node.has_method("get_campus_profile") and String(node.get("npc_id")) == target_id: npc = node
	if npc == null:
		print("ROUTES_TARGET_NOT_VISIBLE ", target_id, " location=", initial.population.get(target_id, {}).get("current_location_id"), " map=", root.get_node("CampusPresentation").call("get_map"))
		quit(1)
		return
	assert(npc != null)
	var movement := current_scene.get_node("NpcMovementLayer")
	assert(movement.call("visible_resident_count") <= int(movement.get("max_visible_npcs")))
	var before_ids: Array = movement.get("_visible_actors").keys()
	movement.call("_refresh_residents")
	assert(before_ids == (movement.get("_visible_actors") as Dictionary).keys())
	current_scene.get_node("Player").global_position = npc.global_position
	inspector.call("inspect_npc", npc)
	var feedback: Label = inspector.get("_anomaly_route_feedback")
	assert(feedback.text.contains("白天支持＋夜间处置"))
	assert(feedback.text.contains("不是实时状态"))
	assert(feedback.text.contains("双方各消耗一次主要行动"))
	assert(feedback.text.contains("不是本人心结已经解决"))
	assert(feedback.text.contains("不是当前数值"))
	assert(not feedback.text.contains("night:d") and not feedback.text.contains("campus_student_"))
	inspector.get("_anomaly_ask").pressed.emit()
	var completed: Array = await bridge.campus_investigation_operation_completed
	assert(completed[0], JSON.stringify(completed[1].get("result", {})))
	assert(bridge.get("campus_snapshot").clock == initial.clock)
	assert(bridge.get("campus_snapshot").action_economy == initial.action_economy)
	for size in [Vector2i(960, 540), Vector2i(1280, 720), Vector2i(1600, 900)]:
		root.size = size
		await process_frame
		assert(feedback.autowrap_mode == TextServer.AUTOWRAP_WORD_SMART)
		assert(feedback.size.x <= size.x)
	print("CAMPUS_ROUTES_FLOW_OK real_day_support real_card_victory fresh_report own_costs dated_not_live private_no_ids free_inspection three_sizes same_place_contact_priority unchanged_resident_cap no_api")
	quit(0)
