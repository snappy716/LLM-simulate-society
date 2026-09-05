extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("campus supply flow timed out")
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
	phone.call("_open_app", "market", "校园商城")
	var panel = phone.get("_inventory_root")
	var submit := panel.get("submit") as Button
	var detail := panel.get("detail") as RichTextLabel
	assert(submit.disabled, "in-transit stock is not purchasable")
	assert(detail.text.contains("已付款在途") and detail.text.contains("第 2 天"), detail.text)
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	var balance := int(snapshot.economy.balance)
	for _step in range(3):
		bridge.advance_campus_phase()
		var advanced = await bridge.campus_phase_advanced
		assert(bool(advanced[0]), "supply phase failed: %s" % advanced[1])
		if _step < 2:
			assert(submit.disabled, "goods must not arrive on order day")
	snapshot = bridge.get("campus_snapshot")
	assert(int(snapshot.clock.day) == 2 and snapshot.clock.phase == "morning")
	assert((phone.get("_time_label") as Label).text.begins_with("Day 2"), "phone clock must follow live snapshot while open")
	assert(int(snapshot.economy.balance) == balance, "supplier cannot charge player")
	assert(not submit.disabled, "next-day delivered stock must be purchasable")
	submit.pressed.emit()
	var bought = await bridge.campus_inventory_operation_completed
	assert(bool(bought[0]), "post-delivery purchase failed")
	snapshot = bridge.get("campus_snapshot")
	assert(int(snapshot.economy.balance) == balance - 4)
	assert(int(snapshot.player.action_budget.major_remaining) == 1)
	assert(int(snapshot.economy.inventory.quantities.bread_loaf) == 3)
	print("CAMPUS_SUPPLY_FLOW_OK explicit_empty_shelf paid_order next_day_delivery purchase")
	if "--keep-open" in OS.get_cmdline_user_args():
		return
	scene.queue_free()
	await process_frame
	quit(0)
