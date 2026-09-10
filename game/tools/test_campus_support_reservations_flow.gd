extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(100).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	await process_frame
	var before: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	var npc: Node
	for node in get_nodes_in_group("campus_interactable_npc"):
		if String(node.call("get_campus_profile").get("display_name", "")) == "预约冲突验收对象": npc = node
	assert(npc != null)
	current_scene.get_node("Player").global_position = npc.global_position
	inspector.call("inspect_npc", npc)
	inspector.get("_anomaly_ask").pressed.emit()
	var heard: Array = await bridge.campus_investigation_operation_completed
	assert(heard[0], JSON.stringify(heard[1]))
	assert(inspector.get("_anomaly_support").disabled)
	assert(inspector.get("_anomaly_feedback").text.contains("未扣行动"))
	assert(bridge.get("campus_snapshot").action_economy == before.action_economy)
	inspector.call("_set_open", false)
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "agenda", "日程与约定")
	var outings: Node = phone.get("_agenda_root").get_node("Outings")
	assert(not outings.get("cancel").disabled)
	outings.get("cancel").pressed.emit()
	var cancelled: Array = await bridge.campus_outing_operation_completed
	assert(cancelled[0], JSON.stringify(cancelled[1]))
	assert(bridge.get("campus_snapshot").action_economy == before.action_economy)
	phone.call("_set_open", false)
	inspector.call("inspect_npc", npc)
	assert(not inspector.get("_anomaly_support").disabled)
	inspector.get("_anomaly_support").pressed.emit()
	var supported: Array = await bridge.campus_investigation_operation_completed
	assert(supported[0], JSON.stringify(supported[1]))
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(after.clock == before.clock)
	assert(after.action_economy.player.major_remaining == before.action_economy.player.major_remaining - 1)
	assert(inspector.get("_anomaly_support").disabled)
	assert(inspector.get("_anomaly_feedback").text.contains("现实锚定"))
	print("CAMPUS_SUPPORT_RESERVATIONS_FLOW_OK real_booking visible_refusal no_cost explicit_phone_cancel actual_support unchanged_clock no_api")
	quit(0)
