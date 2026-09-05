extends SceneTree


func _initialize() -> void:
	DisplayServer.window_set_title("Campus Inventory Acceptance")
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("campus inventory test timed out")
			quit(1)
	)
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty(), "campus connection timed out")
	var scene = load("res://scenes/campus/campus_collab_test.tscn").instantiate()
	root.add_child(scene)
	current_scene = scene
	await process_frame
	var phone = scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "market", "校园商城")
	var panel = phone.get("_inventory_root")
	var submit := panel.get("submit") as Button
	var travel := panel.get("travel") as Button
	assert(submit.disabled, "remote purchase must be disabled")
	for _step in range(3):
		assert(not travel.disabled, "missing route to shop")
		travel.pressed.emit()
		var moved = await bridge.campus_traversal_completed
		assert(bool(moved[0]), "shop path traversal failed: %s" % moved[1])
	assert(String((bridge.get("campus_snapshot") as Dictionary).player.current_location_id) == "supermarket_sales_floor")
	assert(not submit.disabled)
	submit.pressed.emit()
	var bought = await bridge.campus_inventory_operation_completed
	assert(bool(bought[0]), "campus purchase failed: %s" % bought[1])
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(int(snapshot.economy.balance) == 496)
	assert(int(snapshot.economy.inventory.quantities.bread_loaf) == 3)
	assert(snapshot.clock.phase == "morning" and int(snapshot.clock.minute) == 0)
	assert(int(snapshot.player.action_budget.major_remaining) == 1)
	assert((panel.get("detail") as RichTextLabel).text.contains("496"))
	var picker := panel.get("action_picker") as OptionButton
	picker.select(2)
	picker.item_selected.emit(2)
	submit.pressed.emit()
	var used = await bridge.campus_inventory_operation_completed
	assert(bool(used[0]), "campus food use failed: %s" % used[1])
	snapshot = bridge.get("campus_snapshot")
	assert(int(snapshot.player.needs.food) == 0)
	assert(int(snapshot.economy.inventory.quantities.bread_loaf) == 2)
	picker.select(4)
	picker.item_selected.emit(4)
	submit.pressed.emit()
	var dropped = await bridge.campus_inventory_operation_completed
	assert(bool(dropped[0]))
	picker.select(5)
	picker.item_selected.emit(5)
	submit.pressed.emit()
	var picked = await bridge.campus_inventory_operation_completed
	assert(bool(picked[0]))
	snapshot = bridge.get("campus_snapshot")
	assert(int(snapshot.economy.inventory.quantities.bread_loaf) == 2)
	assert(int(snapshot.economy.balance) == 496)
	phone.call("_open_app", "wallet", "电子钱包")
	assert((phone.get("_content") as RichTextLabel).text.contains("496"))
	phone.call("_open_app", "market", "校园商城")
	print("CAMPUS_INVENTORY_FLOW_OK")
	if "--keep-open" in OS.get_cmdline_user_args():
		return
	scene.queue_free()
	await process_frame
	quit(0)
