extends SceneTree
## Explicit UI fixtures below are not evidence of simulated NPC activity.


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(60).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			quit(1)
	)
	var text = preload("res://scripts/ui/campus_ui_text.gd")
	assert(text.operation_feedback(true, {}) == "操作已完成。")
	assert(text.operation_feedback(false, {}).contains("未确认"))
	assert(text.operation_feedback(false, {"error": "余额不足", "result": {"message": "旧消息"}}) == "余额不足")
	assert(text.operation_feedback(true, {"result": {"message": "已恢复"}}) == "已恢复")
	assert(text.operation_feedback(false, {"result": null}).contains("未确认"))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "health", "健康档案")
	var health = phone.get("_health_root")
	var inventory = phone.get("_inventory_root")
	var trade = phone.get("_trade_root")
	var snapshot: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	for panel in [health, inventory, trade]:
		panel.get("feedback").text = "既有结果"
	bridge.campus_inventory_operation_completed.emit(true, {"result": {"message": "其他页面结果"}})
	for panel in [health, inventory, trade]:
		assert(panel.get("feedback").text == "既有结果", "idle panel consumed unrelated completion")
	# Only simulate the UI waiting flag, never send a mutation with fixture data.
	health.set("_pending", true)
	health.call("refresh")
	assert(health.get("rest_button").disabled and health.get("heal_button").disabled)
	assert(health.get("rest_button").tooltip_text == text.PENDING_MESSAGE)
	bridge.campus_inventory_operation_completed.emit(false, {"error": "测试拒绝：条件不满足"})
	assert(not health.get("_pending"))
	assert(health.get("feedback").text == "测试拒绝：条件不满足")
	assert(inventory.get("feedback").text == "既有结果")
	assert(not health.get("rest_button").tooltip_text.is_empty())
	assert(not health.get("home_button").tooltip_text.is_empty())
	assert(not health.get("heal_button").tooltip_text.is_empty())
	assert(not health.get("detail").text.contains("commitment_pressure"))
	assert(bridge.get("campus_snapshot") == snapshot)
	health.get("feedback").text = ""
	print("CAMPUS_OPERATION_FEEDBACK_OK explicit_ui_fixtures idle_isolation waiting refusal neutral_fallback no_world_mutation")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
