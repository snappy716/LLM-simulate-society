extends SceneTree
## Unsupported historical gameplay content must not be silently relabelled.


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			push_error("campus content migration timed out")
			quit(1)
	)
	var save_dir := OS.get_environment("GODOT_SIM_SAVE_DIR")
	assert(not save_dir.is_empty(), "use an isolated directory with an incompatible historical slot_1.json")
	var path := save_dir.path_join("slot_1.json")
	var original_hash := FileAccess.get_sha256(path)
	assert(not original_hash.is_empty())
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())
	var initial: Dictionary = (bridge.get("campus_snapshot") as Dictionary).duplicate(true)
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
	assert(not bool(loaded[0]), "unconverted old battle semantics must be rejected")
	assert(String(loaded[1].get("error", "")).contains("no approved migration"))
	assert(original_hash == FileAccess.get_sha256(path), "loading must not rewrite the old slot")
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(after.revision == initial.revision)
	assert(after.clock == initial.clock)
	assert(after.economy.balance == initial.economy.balance)
	assert(not bool(panel.get("_pending")))
	assert(not (panel.get("load_button") as Button).disabled)
	assert((panel.get("detail") as RichTextLabel).text.contains("原存档和当前进度均未修改"))
	if OS.get_environment("GODOT_MIGRATION_INSPECT") == "1":
		print("CAMPUS_MIGRATION_INSPECT_READY")
		await create_timer(45).timeout
	print("CAMPUS_CONTENT_MIGRATION_FLOW_OK old_content_refused unchanged_original live_world_preserved controls_released")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
