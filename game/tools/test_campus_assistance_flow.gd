extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	var initial: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "assistance", "互助约定")
	var panel := phone.get("_assistance_root") as Control
	assert(panel.visible)
	assert(not panel.get("accept").disabled)
	assert(panel.get("deliver").disabled)
	assert(initial.assistance.requests[0].status == "pending")
	panel.get("accept").pressed.emit()
	assert(panel.get("accept").disabled and panel.get("decline").disabled)
	var result = await bridge.campus_assistance_operation_completed
	assert(result[0], JSON.stringify(result))
	await process_frame
	var accepted: Dictionary = bridge.get("campus_snapshot")
	assert(accepted.assistance.requests[0].status == "accepted")
	assert(accepted.economy.inventory == initial.economy.inventory)
	assert(accepted.player.action_budget == initial.player.action_budget)
	assert(not panel.get("deliver").disabled)
	panel.get("deliver").pressed.emit()
	assert(panel.get("deliver").disabled)
	result = await bridge.campus_assistance_operation_completed
	assert(result[0], JSON.stringify(result))
	await process_frame
	var delivered: Dictionary = bridge.get("campus_snapshot")
	assert(delivered.clock == initial.clock)
	assert(delivered.economy.inventory.quantities.get("blank_notebook", 0) == initial.economy.inventory.quantities.blank_notebook - 1)
	assert(delivered.assistance.requests[0].status == "fulfilled")
	assert(delivered.assistance.requests[0].receipt.requester_after == delivered.assistance.requests[0].receipt.requester_before + 1)
	assert(panel.get("detail").text.contains("已实际交付"))
	assert(panel.get("deliver").disabled)
	panel.call("_send", "DELIVER_MATERIAL_HELP", {"request_id": delivered.assistance.requests[0].request_id})
	result = await bridge.campus_assistance_operation_completed
	assert(not result[0])
	assert(not panel.get("_pending"))
	assert(panel.get("detail").text.contains("已实际交付"))
	assert(bridge.get("campus_snapshot").economy.inventory == delivered.economy.inventory)
	phone.get("_app_scroll").scroll_vertical = 0
	if OS.get_environment("GODOT_ASSISTANCE_INSPECT") == "1":
		print("CAMPUS_ASSISTANCE_INSPECT_READY")
		await create_timer(45).timeout
	print("CAMPUS_ASSISTANCE_FLOW_OK real_request explicit_player_choice no_goods_on_assent physical_delivery receipt free_time pending_rejection")
	quit(0)
