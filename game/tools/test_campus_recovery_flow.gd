extends SceneTree
## Requires explicitly started tests.run_campus_recovery_fixture on matching port.


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("recovery test timed out")
			quit(1)
	)
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(.05).timeout
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(not snapshot.is_empty())
	assert(int(snapshot.player.vitals.health) == 15, "run the explicit wounded-player QA fixture")
	var scene = load("res://scenes/campus/campus_collab_test.tscn").instantiate()
	root.add_child(scene)
	current_scene = scene
	await process_frame
	var phone = scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "health", "健康档案")
	var health = phone.get("_health_root")
	assert((health.get("detail") as RichTextLabel).text.contains("生命：15"))
	assert((health.get("rest_button") as Button).disabled, "night rest must not heal")
	phone.call("_open_app", "market", "校园商城")
	var inventory = phone.get("_inventory_root")
	var actions := inventory.get("action_picker") as OptionButton
	actions.select(2)
	actions.item_selected.emit(2)
	var items := inventory.get("item_picker") as OptionButton
	for index in range(items.item_count):
		if items.get_item_metadata(index) == "bandage_roll":
			items.select(index)
			items.item_selected.emit(index)
	(inventory.get("submit") as Button).pressed.emit()
	var treatment = await bridge.campus_inventory_operation_completed
	assert(bool(treatment[0]), "bandage treatment failed: %s" % treatment[1])
	snapshot = bridge.get("campus_snapshot")
	var after_medicine := int(snapshot.player.vitals.health)
	assert(after_medicine > 15 and after_medicine < int(snapshot.player.vitals.max_health))
	assert(int(snapshot.economy.inventory.quantities.bandage_roll) == 1)
	bridge.call("operate_campus_night_world", "EXIT_NIGHT_WORLD")
	var exited = await bridge.campus_night_world_operation_completed
	assert(bool(exited[0]))
	snapshot = bridge.get("campus_snapshot")
	assert(int(snapshot.player.vitals.health) == after_medicine, "returning surface healed without rest")
	phone.call("_open_app", "health", "健康档案")
	assert(not (health.get("rest_button") as Button).disabled)
	(health.get("rest_button") as Button).pressed.emit()
	var rested = await bridge.campus_inventory_operation_completed
	assert(bool(rested[0]), "rest failed: %s" % rested[1])
	snapshot = bridge.get("campus_snapshot")
	assert(int(snapshot.player.vitals.health) == int(snapshot.player.vitals.max_health))
	assert(int(snapshot.player.vitals.focus) == int(snapshot.player.vitals.max_focus))
	assert(int(snapshot.player.action_budget.major_remaining) == 0)
	assert(int(snapshot.economy.inventory.quantities.bandage_roll) == 1, "rest consumed medicine")
	assert((health.get("rest_button") as Button).disabled)
	print("CAMPUS_RECOVERY_FLOW_OK explicit_wounded_fixture_not_enemy_AI")
	if "--keep-open" in OS.get_cmdline_user_args():
		return
	scene.queue_free()
	await process_frame
	quit(0)
