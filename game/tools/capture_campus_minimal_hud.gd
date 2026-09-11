extends SceneTree
## Run using a background application launch and an isolated offline settings path.

func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func(): push_error("HUD capture timeout"); quit(1))
	var output := OS.get_cmdline_user_args()[0]
	DirAccess.make_dir_recursive_absolute(output)
	var bridge := root.get_node("SimulationBridge")
	for _i in range(400):
		if not bridge.campus_snapshot.is_empty(): break
		await create_timer(0.05).timeout
	assert(not bridge.campus_snapshot.is_empty())
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	for _i in range(30): await process_frame
	await _save(output, "01-campus-hud")
	var phone := current_scene.get_node("CampusPhoneUI")
	for id in ["character", "cards", "relationships"]:
		phone.open_hud_page(id)
		for _i in range(10): await process_frame
		await _save(output, id)
		if id == "character":
			phone._hud_tabs.get_child(1).pressed.emit()
			for _i in range(10): await process_frame
			await _save(output, "inventory")
		phone._set_open(false)
	phone.open_hud_page("phone")
	phone._open_app("time", "时间与镜头")
	for _i in range(10): await process_frame
	await _save(output, "time")
	phone._set_open(false)
	print("CAMPUS_MINIMAL_HUD_CAPTURE_OK")
	quit(0)


func _save(directory: String, name_value: String) -> void:
	await RenderingServer.frame_post_draw
	var frame := root.get_texture().get_image()
	assert(not frame.is_empty())
	assert(frame.save_png(directory.path_join(name_value + ".png")) == OK)
