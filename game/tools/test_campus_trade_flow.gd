extends SceneTree


func _initialize() -> void:
	DisplayServer.window_set_title("Campus Private Trade Acceptance")
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("campus trade test timed out")
			quit(1)
	)
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	var scene = load("res://scenes/campus/campus_collab_test.tscn").instantiate()
	root.add_child(scene)
	current_scene = scene
	await process_frame
	var phone = scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "trade", "当面交易")
	var panel = phone.get("_trade_root")
	var respond := panel.get("respond") as Button
	var propose := panel.get("propose") as Button
	assert(not respond.disabled, "fixture incoming quote must be actionable")
	respond.pressed.emit()
	var result = await bridge.campus_inventory_operation_completed
	assert(bool(result[0]) and result[1].result.code == "settled")
	assert(int((bridge.get("campus_snapshot") as Dictionary).economy.balance) == 496)
	var targets := panel.get("target_picker") as OptionButton
	for index in range(targets.item_count):
		if String(targets.get_item_metadata(index)) == "campus_student_001":
			targets.select(index)
	(panel.get("price") as SpinBox).value = 1
	propose.pressed.emit()
	result = await bridge.campus_inventory_operation_completed
	assert(bool(result[0]) and result[1].result.code == "offered")
	assert(int((bridge.get("campus_snapshot") as Dictionary).economy.balance) == 496, "proposal must not pay")
	respond.pressed.emit()
	result = await bridge.campus_inventory_operation_completed
	assert(bool(result[0]) and result[1].result.code == "rejected", "NPC must refuse unfair quote")
	(panel.get("price") as SpinBox).value = 4
	propose.pressed.emit()
	result = await bridge.campus_inventory_operation_completed
	assert(bool(result[0]) and result[1].result.code == "offered")
	respond.pressed.emit()
	result = await bridge.campus_inventory_operation_completed
	assert(bool(result[0]) and result[1].result.code == "settled")
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(int(snapshot.economy.balance) == 492)
	assert(int(snapshot.economy.inventory.quantities.bread_loaf) == 4)
	assert(snapshot.clock.phase == "morning" and int(snapshot.player.action_budget.major_remaining) == 1)
	assert((panel.get("detail") as RichTextLabel).text.contains("492"))
	print("CAMPUS_TRADE_FLOW_OK explicit_colocation_fixture incoming_accept unfair_refusal atomic_settlement")
	if "--keep-open" in OS.get_cmdline_user_args():
		return
	scene.queue_free()
	await process_frame
	quit(0)
