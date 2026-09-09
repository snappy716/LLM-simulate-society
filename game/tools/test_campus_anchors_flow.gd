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
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	await process_frame
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	var npc: Node
	for node in current_scene.get_node("NpcMovementLayer").get_children():
		if node.has_method("get_campus_profile") and String(node.call("get_campus_profile").get("display_name", "")) == "共同经历验收对象": npc = node
	assert(npc != null)
	current_scene.get_node("Player").global_position = npc.global_position
	inspector.call("inspect_npc", npc)
	while bridge.call("is_campus_busy"): await create_timer(0.05).timeout
	assert(inspector.get("_anchor_options").item_count > 0)
	assert(not inspector.get("_anchor_use").visible)
	inspector.get("_anchor_confirm").pressed.emit()
	var confirmation: Array = await bridge.campus_investigation_operation_completed
	assert(confirmation[0], JSON.stringify(confirmation[1].get("result", {})))
	var confirmed: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	assert(confirmed.clock == initial.clock and confirmed.action_economy == initial.action_economy)
	assert(inspector.get("_anchor_feedback").text.contains("当面交付"))
	assert(inspector.get("_anchor_use").visible and not inspector.get("_anchor_use").disabled)
	var row: Dictionary = inspector.get("_anomaly_case")
	for secret in ["shell", "core", "coherence", "history", "anchors"]: assert(not row.has(secret))
	inspector.get("_anchor_use").pressed.emit()
	var supported: Array = await bridge.campus_investigation_operation_completed
	assert(supported[0], JSON.stringify(supported[1].get("result", {})))
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(after.clock == initial.clock)
	assert(after.action_economy.player.major_remaining == initial.action_economy.player.major_remaining - 1)
	assert(inspector.get("_anchor_feedback").text.contains("不能重复叠加"))
	assert(inspector.get("_anomaly_feedback").text.contains("证据洞察"))
	assert(inspector.get("_anchor_use").disabled)
	print("CAMPUS_ANCHORS_FLOW_OK real_request_delivery confirmed_shared_memory private_view genuine_support_cost no_stacking no_api explicit_thresholds")
	quit(0)
