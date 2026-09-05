extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("campus content migration timed out")
			quit(1)
	)
	var save_dir := OS.get_environment("GODOT_SIM_SAVE_DIR")
	assert(not save_dir.is_empty(), "use an isolated directory with the pre-split slot_1.json")
	var path := save_dir.path_join("slot_1.json")
	var original_hash := FileAccess.get_sha256(path)
	assert(not original_hash.is_empty())
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
	phone.call("_open_app", "saves", "存读档")
	var listed = await bridge.campus_persistence_completed
	assert(bool(listed[0]) and bool(listed[1].slots[0].current.exists))
	var panel = phone.get("_save_root")
	(panel.get("load_button") as Button).pressed.emit()
	var dialog := panel.get("confirmation") as ConfirmationDialog
	assert(dialog.visible)
	dialog.confirmed.emit()
	dialog.hide()
	var loaded = await bridge.campus_persistence_completed
	assert(bool(loaded[0]), str(loaded[1]))
	assert("campus-content-split-2026-09-06" in loaded[1].migrations)
	assert(loaded[1].snapshot.clock.phase == "afternoon")
	assert(int(loaded[1].snapshot.economy.balance) == 500)
	assert(original_hash == FileAccess.get_sha256(path), "loading must not rewrite the old slot")
	for _frame in range(10):
		await process_frame
	phone = current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "saves", "存读档")
	listed = await bridge.campus_persistence_completed
	assert(bool(listed[0]))
	panel = phone.get("_save_root")
	assert((panel.get("detail") as RichTextLabel).text.contains("下午"))
	print("CAMPUS_CONTENT_MIGRATION_FLOW_OK pre_split_save ui_load unchanged_original restored_afternoon")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
