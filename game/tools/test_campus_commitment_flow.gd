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
		if node.has_method("get_campus_profile") and String(node.call("get_campus_profile").get("display_name", "")) == "履约核对验收": npc = node
	assert(npc != null)
	current_scene.get_node("Player").global_position = npc.global_position
	inspector.call("inspect_npc", npc)
	inspector.get("_dispute_ask").pressed.emit()
	var first: Array = await bridge.campus_investigation_operation_completed
	assert(first[0], JSON.stringify(first[1].get("result", {})))
	assert(inspector.get("_dispute_feedback").text.contains("逾期"))
	inspector.get("_dispute_other").pressed.emit()
	var second: Array = await bridge.campus_investigation_operation_completed
	assert(second[0])
	assert(inspector.get("_dispute_mediate").disabled)
	assert(inspector.get("_dispute_review").visible)
	inspector.get("_dispute_review").pressed.emit()
	var record: Array = await bridge.campus_investigation_operation_completed
	assert(record[0], JSON.stringify(record[1].get("result", {})))
	assert(inspector.get("_dispute_feedback").text.contains("调查笔记"))
	assert(not inspector.get("_dispute_mediate").disabled)
	inspector.get("_dispute_mediate").pressed.emit()
	var result: Array = await bridge.campus_investigation_operation_completed
	assert(result[0])
	assert(inspector.get("_dispute_feedback").text.contains("原委托仍为逾期"))
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(after.clock == initial.clock)
	assert(after.tasks == initial.tasks)
	assert(after.action_economy == initial.action_economy)
	print("CAMPUS_COMMITMENT_FLOW_OK real_claim_expiry two_statements actual_public_record no_fake_completion free explicit_delay no_api")
	quit(0)
