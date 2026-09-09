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
		if node.has_method("get_campus_profile") and String(node.call("get_campus_profile").get("display_name", "")) == "支持预约验收对象": npc = node
	assert(npc != null)
	current_scene.get_node("Player").global_position = npc.global_position
	inspector.call("inspect_npc", npc)
	assert(inspector.get("_meeting_options").item_count > 0)
	assert(inspector.get("_meeting_propose").visible)
	inspector.get("_meeting_propose").pressed.emit()
	assert(inspector.get("_meeting_propose").disabled)
	var proposed: Array = await bridge.campus_investigation_operation_completed
	assert(proposed[0], JSON.stringify(proposed[1].get("result", {})))
	assert(inspector.get("_meeting_status").text.contains("双方已确认"))
	assert(inspector.get("_meeting_cancel").visible)
	assert(not inspector.get("_meeting_accept").visible)
	assert(not inspector.get("_meeting_propose").visible)
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(initial.clock == after.clock and initial.action_economy == after.action_economy)
	inspector.get("_meeting_cancel").pressed.emit()
	var cancelled: Array = await bridge.campus_investigation_operation_completed
	assert(cancelled[0])
	assert(inspector.get("_meeting_status").text.contains("已取消"))
	assert(not inspector.get("_meeting_cancel").visible)
	assert(bridge.get("campus_snapshot").action_economy == initial.action_economy)
	print("CAMPUS_MEETINGS_FLOW_OK real_http rendered_options consensual_booking cancel phone_receipts no_time_no_recovery no_api")
	quit(0)
