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
	assert(initial.cognition.focused_count == 20)
	assert(initial.cognition.daily_call_limit == null and initial.cognition.awakened_slot_limit == null)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	await process_frame
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	var friend: Node
	var ordinary: Node
	for node in current_scene.get_node("NpcMovementLayer").get_children():
		if node.has_method("get_campus_profile"):
			var label := String(node.call("get_campus_profile").get("display_name", ""))
			if label == "好友接入验收":
				friend = node
			if label == "普通同学验收":
				ordinary = node
	assert(friend != null and ordinary != null)
	current_scene.get_node("Player").global_position = ordinary.global_position
	inspector.call("inspect_npc", ordinary)
	var ordinary_id: String = inspector.get("_selected_profile").npc_id
	assert(inspector.get("_awaken_button").disabled)
	assert(inspector.get("_awaken_button").tooltip_text.contains("亲近度"))
	bridge.operate_campus_cognition("AWAKEN_NPC", ordinary_id)
	var reply: Array = await bridge.campus_cognition_operation_completed
	assert(not reply[0])
	assert(bridge.get("campus_snapshot").cognition.focused_count == 20)
	# An ordinary NPC still answers player dialogue through the configured provider.
	inspector.get("_dialogue_input").text = "你好，今天有什么安排？"
	inspector.get("_dialogue_button").pressed.emit()
	reply = await bridge.campus_dialogue_completed
	assert(reply[0] and reply[1].result.payload.wording_source == "llm", JSON.stringify(reply))
	assert(bridge.get("campus_snapshot").clock == initial.clock)
	assert(bridge.get("campus_snapshot").cognition.focused_count == 20)
	current_scene.get_node("Player").global_position = friend.global_position
	inspector.call("inspect_npc", friend)
	var friend_id: String = inspector.get("_selected_profile").npc_id
	assert(not inspector.get("_awaken_button").disabled)
	assert(inspector.get("_awaken_button").tooltip_text.contains("不占基础"))
	inspector.get("_awaken_button").pressed.emit()
	assert(inspector.get("_awaken_button").disabled)
	reply = await bridge.campus_cognition_operation_completed
	assert(reply[0])
	assert(bridge.get("campus_snapshot").cognition.focused_count == 21)
	assert(bridge.get("campus_snapshot").cognition.base_focused_count == 20)
	assert(inspector.get("_awaken_button").disabled)
	assert(inspector.get("_awaken_button").text.contains("已建立"))
	assert(bridge.get("campus_snapshot").clock == initial.clock)
	inspector.call("_set_open", false)
	bridge.advance_campus_phase()
	assert(root.get_node("OvernightTransition").is_active())
	reply = await bridge.campus_phase_advanced
	assert(reply[0])
	await create_timer(0.55).timeout
	assert(not paused and not root.get_node("OvernightTransition").is_active())
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(snapshot.cognition.focused_count == 21)
	assert(snapshot.population[friend_id].awakened_by_player)
	assert(snapshot.cognition.usage.calls >= 21)
	assert(snapshot.cognition.usage.budget_blocks == 0)
	print("CAMPUS_FRIEND_FLOW_OK real_commands fake_provider relationship_gate ordinary_chat free_time base20_plus_friend overnight_all_deep no_budget_drop")
	quit(0)
