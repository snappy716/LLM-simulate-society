extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(100).timeout.connect(func(): quit(1))
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
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	var npc: Node
	for node in current_scene.get_node("NpcMovementLayer").get_children():
		if node.has_method("get_campus_profile") and String(node.call("get_campus_profile").get("display_name", "")) == "邀约协调验收":
			npc = node
	assert(npc != null)
	current_scene.get_node("Player").global_position = npc.global_position
	inspector.call("inspect_npc", npc)
	inspector.get("_plan_button").pressed.emit()
	var reply: Array = await bridge.campus_goal_operation_completed
	assert(reply[0], JSON.stringify(reply))
	assert(inspector.get("_plan_feedback").text.contains("已经和约好的同学约好碰面"))
	assert(bridge.get("campus_snapshot").clock == initial.clock)
	assert(not bridge.get("campus_snapshot").cognition.has("social_coordination"))
	print("CAMPUS_COORDINATION_FLOW_OK actual_inspector_button confirmed_not_tentative free_query private_ledger explicit_fixture no_api")
	quit(0)
