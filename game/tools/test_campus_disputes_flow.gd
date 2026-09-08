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
	assert(initial.social.disputes.is_empty())
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	await process_frame
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	var npc: Node
	for node in current_scene.get_node("NpcMovementLayer").get_children():
		if node.has_method("get_campus_profile") and String(node.call("get_campus_profile").get("display_name", "")) == "纠纷调解验收":
			npc = node
	assert(npc != null)
	current_scene.get_node("Player").global_position = npc.global_position
	inspector.call("inspect_npc", npc)
	inspector.get("_dispute_ask").pressed.emit()
	var first_reply: Array = await bridge.campus_investigation_operation_completed
	assert(first_reply[0], JSON.stringify(first_reply[1].get("result", {})))
	assert(inspector.get("_dispute_mediate").disabled)
	assert(inspector.get("_dispute_other").visible)
	assert(inspector.get("_dispute_other").text.contains("争执另一方"))
	inspector.get("_dispute_other").pressed.emit()
	var second_reply: Array = await bridge.campus_investigation_operation_completed
	assert(second_reply[0], JSON.stringify(second_reply[1].get("result", {})))
	assert(not inspector.get("_dispute_mediate").disabled)
	inspector.get("_dispute_mediate").pressed.emit()
	var mediation: Array = await bridge.campus_investigation_operation_completed
	assert(mediation[0], JSON.stringify(mediation[1].get("result", {})))
	assert(inspector.get("_dispute_feedback").text.contains("缓和"))
	assert(inspector.get("_dispute_mediate").disabled)
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(after.clock == initial.clock)
	assert(after.social.disputes.size() == 1)
	assert(after.social.disputes[0].status == "easing")
	assert(not after.social.disputes[0].has("source_interaction_ids"))
	print("CAMPUS_DISPUTES_FLOW_OK actual_inspector_buttons two_statements existing_remote_contact consent cooldown free private explicit_fixture no_api")
	quit(0)
