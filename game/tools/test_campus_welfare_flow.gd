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
		if node.has_method("get_campus_profile") and String(node.call("get_campus_profile").get("display_name", "")) == "近况回访验收": npc = node
	assert(npc != null)
	current_scene.get_node("Player").global_position = npc.global_position
	inspector.call("inspect_npc", npc)
	inspector.get("_welfare_button").pressed.emit()
	var reply: Array = await bridge.campus_investigation_operation_completed
	assert(reply[0], JSON.stringify(reply[1].get("result", {})))
	assert(inspector.get("_welfare_feedback").text.contains("还没恢复"))
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(after.clock == initial.clock)
	assert(after.action_economy == initial.action_economy)
	var reports: Array = after.social.welfare
	assert(not reports.is_empty())
	assert(not reports[-1].has("site_id"))
	assert(not reports[-1].has("location_id"))
	assert(not reports[-1].claim_id.is_empty())
	inspector.get("_welfare_button").pressed.emit()
	var duplicate: Array = await bridge.campus_investigation_operation_completed
	assert(duplicate[0])
	assert(duplicate[1].result.code == "already_checked")
	print("CAMPUS_WELFARE_FLOW_OK actual_npc_button true_injury no_healing free evidence privacy idempotent explicit_fixture no_api")
	quit(0)
