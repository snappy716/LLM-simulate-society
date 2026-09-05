extends SceneTree


func _initialize() -> void:
	DisplayServer.window_set_title("Campus Save Acceptance")
	call_deferred("_run")


func _run() -> void:
	create_timer(120).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("campus save flow timed out")
			quit(1)
	)
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())
	var scene = load("res://scenes/campus/campus_collab_test.tscn").instantiate()
	root.add_child(scene)
	current_scene = scene
	await process_frame
	var phone = scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "saves", "存读档")
	var listed = await bridge.campus_persistence_completed
	assert(bool(listed[0]) and not bool(listed[1].slots[0].current.exists), "use an isolated empty GODOT_SIM_SAVE_DIR")
	var panel = phone.get("_save_root")
	(panel.get("save_button") as Button).pressed.emit()
	var dialog := panel.get("confirmation") as ConfirmationDialog
	assert(dialog.visible)
	dialog.get_cancel_button().pressed.emit()
	dialog.hide()
	panel.call("refresh")
	listed = await bridge.campus_persistence_completed
	assert(not bool(listed[1].slots[0].current.exists), "cancel must not save")
	(panel.get("save_button") as Button).pressed.emit()
	dialog.confirmed.emit()
	dialog.hide()
	var saved = await bridge.campus_persistence_completed
	assert(bool(saved[0]) and bool(saved[1].slots[0].current.exists))
	assert((panel.get("detail") as RichTextLabel).text.contains("保存成功"))
	phone.call("_open_app", "market", "校园商城")
	var inventory = phone.get("_inventory_root")
	for _step in range(3):
		(inventory.get("travel") as Button).pressed.emit()
		var moved = await bridge.campus_traversal_completed
		assert(bool(moved[0]))
	(inventory.get("submit") as Button).pressed.emit()
	var bought = await bridge.campus_inventory_operation_completed
	assert(bool(bought[0]))
	assert(int((bridge.get("campus_snapshot") as Dictionary).economy.balance) == 496)
	phone.call("_open_app", "saves", "存读档")
	await bridge.campus_persistence_completed
	(panel.get("save_button") as Button).pressed.emit()
	dialog.confirmed.emit()
	dialog.hide()
	saved = await bridge.campus_persistence_completed
	assert(bool(saved[0]) and bool(saved[1].slots[0].backup.exists))
	# Deliberately switch the old presentation; loading must rebuild from the save.
	root.get_node("CampusPresentation").call("select_map", "library")
	(panel.get("load_button") as Button).pressed.emit()
	dialog.confirmed.emit()
	dialog.hide()
	var loaded = await bridge.campus_persistence_completed
	assert(bool(loaded[0]))
	await create_timer(0.5).timeout
	assert(not is_instance_valid(phone), "old scene and selections must be discarded")
	assert(root.get_node("CampusPresentation").get("current_map_id") == "living_area")
	assert(int((bridge.get("campus_snapshot") as Dictionary).economy.balance) == 496)
	phone = current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "saves", "存读档")
	await bridge.campus_persistence_completed
	panel = phone.get("_save_root")
	(panel.get("backup_button") as Button).pressed.emit()
	dialog = panel.get("confirmation")
	dialog.confirmed.emit()
	dialog.hide()
	loaded = await bridge.campus_persistence_completed
	assert(bool(loaded[0]))
	await create_timer(0.5).timeout
	assert(int((bridge.get("campus_snapshot") as Dictionary).economy.balance) == 500)
	assert(root.get_node("CampusPresentation").get("current_map_id") == "campus_gate")
	assert(not paused)
	phone = current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "saves", "存读档")
	await bridge.campus_persistence_completed
	print("CAMPUS_SAVE_FLOW_OK cancel save overwrite backup buy load scene_reset")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
