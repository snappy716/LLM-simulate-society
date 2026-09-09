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
	assert(initial.social.anomalies.is_empty())
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	await process_frame
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	var npc: Node
	for node in current_scene.get_node("NpcMovementLayer").get_children():
		if node.has_method("get_campus_profile") and String(node.call("get_campus_profile").get("display_name", "")) == "月相体验验收对象": npc = node
	assert(npc != null)
	current_scene.get_node("Player").global_position = npc.global_position
	inspector.call("inspect_npc", npc)
	assert(not inspector.get("_anomaly_support").visible)
	inspector.get("_anomaly_ask").pressed.emit()
	var other: Node
	for node in current_scene.get_node("NpcMovementLayer").get_children():
		if node != npc and node.has_method("get_campus_profile"):
			other = node
			break
	assert(other != null)
	current_scene.get_node("Player").global_position = other.global_position
	inspector.call("inspect_npc", other)
	var heard: Array = await bridge.campus_investigation_operation_completed
	assert(heard[0], JSON.stringify(heard[1].get("result", {})))
	assert(not inspector.get("_anomaly_ask").disabled)
	assert(inspector.get("_anomaly_case").is_empty())
	current_scene.get_node("Player").global_position = npc.global_position
	inspector.call("inspect_npc", npc)
	var after_heard: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	assert(after_heard.clock == initial.clock)
	assert(after_heard.action_economy == initial.action_economy)
	assert(inspector.get("_anomaly_feedback").text.contains("本人"))
	assert(inspector.get("_anomaly_support").visible and not inspector.get("_anomaly_support").disabled)
	var row: Dictionary = after_heard.social.anomalies[0]
	for hidden in ["shell", "core", "coherence", "source_task_id", "status"]:
		assert(not row.has(hidden))
	inspector.get("_anomaly_support").pressed.emit()
	var supported: Array = await bridge.campus_investigation_operation_completed
	assert(supported[0], JSON.stringify(supported[1].get("result", {})))
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(after.clock == initial.clock)
	assert(after.action_economy.player.major_remaining == initial.action_economy.player.major_remaining - 1)
	assert(inspector.get("_anomaly_support").disabled)
	assert(inspector.get("_anomaly_feedback").text.contains("现实锚定"))
	inspector.get("_anomaly_ask").pressed.emit()
	var refreshed: Array = await bridge.campus_investigation_operation_completed
	assert(refreshed[0])
	assert(inspector.get("_anomaly_feedback").text.contains("需要时间巩固"))
	assert(inspector.get("_anomaly_support").disabled)
	print("CAMPUS_ANOMALY_FLOW_OK actual_npc_ui voluntary_private_evidence free_listen real_support_cost duplicate_guard no_time_advance explicit_fixture no_api")
	quit(0)
