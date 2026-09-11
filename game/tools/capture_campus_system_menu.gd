extends SceneTree

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	create_timer(110).timeout.connect(func(): push_error("system capture timeout"); quit(1))
	var output := OS.get_cmdline_user_args()[0]
	DirAccess.make_dir_recursive_absolute(output)
	var bridge := root.get_node("SimulationBridge")
	var menu := root.get_node("SystemMenu")
	change_scene_to_file("res://scenes/ui/campus_title.tscn")
	for _i in range(400):
		if bridge.connected and menu._pending.is_empty() and menu.page == "home": break
		await create_timer(0.05).timeout
	await _save(output, "01-title")
	menu._new_page()
	await _save(output, "02-new-game")
	menu._confirm("new")
	await _save(output, "03-confirm")
	menu.confirmation.hide()
	menu._confirmed()
	await bridge.campus_persistence_completed
	for _i in range(12): await process_frame
	await _save(output, "04-intro-guide")
	menu._back()
	menu.open_pause()
	await _save(output, "05-pause")
	menu._save_page()
	await bridge.campus_persistence_completed
	var saves: VBoxContainer = menu.body.get_child(0)
	saves._prepare("save", false)
	saves.confirmation.hide()
	saves._confirm()
	var saved = await bridge.campus_persistence_completed
	assert(saved[0])
	await _save(output, "06-save-slots")
	menu._settings()
	await _save(output, "07-settings")
	menu._clear("公共视觉与交互组件", "UI01 验收展示 · 下方状态均为标明的组件样例", "gallery")
	var kit := preload("res://scripts/ui/campus_ui_kit.gd")
	var row := HBoxContainer.new()
	menu.body.add_child(row)
	for role in ["primary", "secondary", "danger"]:
		row.add_child(kit.button({"primary":"主要操作", "secondary":"次要操作", "danger":"危险操作"}[role], func(): pass, role))
	menu.body.add_child(kit.search("搜索人物 / 事项（组件样例）", func(_value): pass))
	menu.body.add_child(kit.tabs(["概况", "记录", "筛选"], func(_value): pass))
	for state in ["loading", "empty", "disabled", "error", "unconfirmed", "success"]:
		menu.body.add_child(kit.status("组件状态样例，不代表世界结果", state))
	menu.body.add_child(kit.pagination(0, 2, func(_value): pass))
	await _save(output, "08-common-components")
	print("CAMPUS_SYSTEM_MENU_CAPTURE_OK actual_new_world offline title pause saves settings component_examples")
	quit(0)

func _save(directory: String, name_value: String) -> void:
	for _i in range(10): await process_frame
	# Hidden, paused title windows may skip idle redraws; request a real render.
	RenderingServer.force_draw()
	var frame := root.get_texture().get_image()
	assert(not frame.is_empty())
	assert(frame.save_png(directory.path_join(name_value + ".png")) == OK)
