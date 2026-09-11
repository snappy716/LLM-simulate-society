extends SceneTree

func _initialize() -> void: call_deferred("_run")

func _run() -> void:
	create_timer(110).timeout.connect(func(): push_error("UI capture timeout"); quit(1))
	var output := OS.get_cmdline_user_args()[0]
	DirAccess.make_dir_recursive_absolute(output)
	var bridge := root.get_node("SimulationBridge")
	while not bridge.connected: await create_timer(0.05).timeout
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	for i in range(15): await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	await _save(output, "phone")
	for id in ["feed", "messages", "agenda", "relationships", "market", "notes", "cards", "party", "combat"]:
		phone.call("_open_app", id, {"feed":"校园动态", "messages":"校园通讯", "agenda":"日程与约定", "relationships":"关系", "market":"校园商城", "notes":"调查笔记", "cards":"卡牌库", "party":"行动小队", "combat":"夜战部署"}.get(id, id))
		await _save(output, id)
		if id == "cards":
			var catalog: GridContainer = phone.get("_growth_root").catalog_grid
			if catalog.get_child_count() > 0:
				phone.get("_app_scroll").ensure_control_visible(catalog.get_child(0))
				await _save(output, "cards_catalog")
	phone.call("_set_open", false)
	var map := current_scene.get_node("CampusMapUI")
	map.call("_set_open", true)
	map.call("_select_map", "living_area")
	await _save(output, "map")
	map.call("_set_open", false)
	bridge.call("fast_travel_campus", "student_life_region")
	var travel = await bridge.campus_fast_travel_completed
	assert(travel[0])
	for _i in range(12): await process_frame
	var residents := current_scene.get_node("NpcMovementLayer")
	assert(residents.get_child_count() > 0)
	var npc := residents.get_child(0)
	current_scene.get_node("Player").global_position = npc.global_position
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	inspector.call("inspect_npc", npc)
	await _save(output, "npc")
	inspector.call("_set_open", false)
	root.get_node("SystemMenu").open_pause()
	root.get_node("SystemMenu")._settings()
	await _save(output, "settings")
	print("CAMPUS_UI_PAGES_CAPTURE_OK actual_offline_state")
	quit(0)

func _save(directory: String, label: String) -> void:
	for i in range(10): await process_frame
	RenderingServer.force_draw()
	assert(root.get_texture().get_image().save_png(directory.path_join(label + ".png")) == OK)
