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
	while current_scene == null:
		await process_frame
	# Avoid background mouse position causing edge-camera drift between UI captures.
	current_scene.set_process(false)
	for _i in range(30): await process_frame
	await _save(output, "01-campus-hud")
	var focused_icon: Button = current_scene.get_node("CampusHUD").entries.cards
	focused_icon.grab_focus()
	await create_timer(0.22).timeout
	assert(float(focused_icon.material.get_shader_parameter("emphasis")) > 0.99)
	await _save(output, "02-hud-focus")
	focused_icon.release_focus()
	await create_timer(0.22).timeout
	assert(float(focused_icon.material.get_shader_parameter("emphasis")) < 0.01)
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
	if "--maps" in OS.get_cmdline_user_args():
		var presentation := root.get_node("CampusPresentation")
		for entry in presentation.all_maps():
			presentation.select_map(entry.id)
			# Explicit visual fixture: this does not pretend that the player travelled.
			current_scene.get_node("CampusHUD").location.text = String(entry.name) + " · 画面适配测试"
			for _i in range(8): await process_frame
			await _save(output, "visual-only-" + String(entry.id))
	print("CAMPUS_MINIMAL_HUD_CAPTURE_OK")
	quit(0)


func _save(directory: String, name_value: String) -> void:
	for _frame in range(4): await process_frame
	RenderingServer.force_draw()
	var frame := root.get_texture().get_image()
	assert(not frame.is_empty())
	assert(frame.save_png(directory.path_join(name_value + ".png")) == OK)
