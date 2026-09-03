extends SceneTree

const COLLAB_SCENE := "res://scenes/campus/campus_collab_test.tscn"


func _initialize() -> void:
	call_deferred("_run_flow")


func _run_flow() -> void:
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(100):
		var snapshot = bridge.get("campus_snapshot")
		if snapshot is Dictionary and not snapshot.is_empty():
			break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())

	var packed := load(COLLAB_SCENE) as PackedScene
	assert(packed != null)
	var outdoor = packed.instantiate()
	root.add_child(outdoor)
	current_scene = outdoor
	await process_frame

	var presentation := root.get_node("CampusPresentation")
	assert((presentation.call("all_maps") as Array).size() == 20)
	var map := outdoor.get_node("CampusMap") as Sprite2D
	assert(map.texture != null)
	assert(map.texture.get_size() == Vector2(1774, 887))
	var camera := outdoor.get_node("Player/Camera2D") as Camera2D
	assert(camera.limit_right == 1774)
	assert(camera.limit_bottom == 887)
	assert(bool(presentation.call("select_map", "living_area_v1")))
	await process_frame
	assert(map.texture.get_size() == Vector2(2040, 771))
	assert(bool(presentation.call("select_map", "dormitory_double_v4")))
	await process_frame
	assert(map.texture.get_size() == Vector2(3548, 887))
	assert(camera.limit_right == 3548)
	assert(bool(presentation.call("select_map", "campus_gate")))
	await process_frame
	assert(map.texture.get_size() == Vector2(1774, 887))
	outdoor.call("set_zoom_multiplier", 2)
	assert(camera.zoom == Vector2(2, 2))
	outdoor.call("set_zoom_multiplier", 1)

	var player = outdoor.get_node("Player")
	assert((player.get("appearance") as Dictionary).size() >= 7)
	var old_appearance: Dictionary = (player.get("appearance") as Dictionary).duplicate(true)
	var randomize_event := InputEventAction.new()
	randomize_event.action = "randomize_outfit"
	randomize_event.pressed = true
	player.call("_unhandled_input", randomize_event)
	assert((player.get("appearance") as Dictionary) != old_appearance)

	var phone_ui = outdoor.get_node("CampusPhoneUI")
	phone_ui.call("_set_open", true)
	assert(bool(phone_ui.call("is_open")))
	assert(paused)
	phone_ui.call("_open_app", "health", "健康档案")
	phone_ui.call("_set_open", false)
	assert(not paused)
	assert(not bool(phone_ui.call("is_open")))
	assert(outdoor.has_node("CampusMapUI"))
	assert(outdoor.has_node("CameraControls"))
	var movement_layer = outdoor.get_node("NpcMovementLayer")
	assert(bool(movement_layer.get("use_scene_route_anchors")))
	assert(get_nodes_in_group("campus_route_anchor").size() >= 10)

	var road = outdoor.get_node("RoadBoundary")
	road.call("request_traversal")
	var road_resolution = await road.traversal_resolved
	assert(bool(road_resolution[0]), "collab road traversal failed: %s" % road_resolution[1])
	var road_snapshot: Dictionary = bridge.get("campus_snapshot")
	assert((road_snapshot.get("player", {}) as Dictionary).get("current_location_id") == "student_life_region")
	assert(current_scene == outdoor)

	var entrance = outdoor.get_node("StudentCenterEntrance")
	entrance.call("request_traversal")
	var entrance_resolution = await entrance.traversal_resolved
	assert(bool(entrance_resolution[0]), "collab entrance failed: %s" % entrance_resolution[1])
	for _attempt in range(30):
		await process_frame
		if current_scene != outdoor:
			break
	assert(current_scene != outdoor)
	assert(current_scene.name == "CampusLobbyGraybox")

	var exit_trigger = current_scene.get_node("StudentCenterExit")
	exit_trigger.call("request_traversal")
	var exit_resolution = await exit_trigger.traversal_resolved
	assert(bool(exit_resolution[0]), "collab exit failed: %s" % exit_resolution[1])
	var lobby = current_scene
	for _attempt in range(30):
		await process_frame
		if current_scene != lobby:
			break
	assert(current_scene != lobby)
	assert(current_scene.name == "CampusCollabTest")
	var returned_player := current_scene.get_node("Player") as Node2D
	for _attempt in range(30):
		if returned_player.position.distance_to(Vector2(294, 646)) < 1.0:
			break
		await process_frame
	assert(returned_player.position.distance_to(Vector2(294, 646)) < 1.0)

	var phase_panel := current_scene.get_node("UI/PhasePanel")
	var advance_button := phase_panel.get_node("Margin/VBox/Advance") as Button
	advance_button.pressed.emit()
	var afternoon_resolution = await bridge.campus_phase_advanced
	assert(bool(afternoon_resolution[0]))
	advance_button.pressed.emit()
	var evening_resolution = await bridge.campus_phase_advanced
	assert(bool(evening_resolution[0]))
	await process_frame
	movement_layer = current_scene.get_node("NpcMovementLayer")
	assert(int(movement_layer.get("last_replayed_count")) > 0)
	for visible_npc in movement_layer.get_children():
		assert(not visible_npc.name_label.visible)

	var before_map_clock: Dictionary = (bridge.get("campus_snapshot") as Dictionary).get("clock", {}).duplicate(true)
	var before_map_budget := int(((bridge.get("campus_snapshot") as Dictionary).get("player", {}) as Dictionary).get("action_budget", {}).get("major_remaining", -1))
	var map_ui = current_scene.get_node("CampusMapUI")
	map_ui.call("_choose_map", "east_dorm_v5")
	var map_travel_resolution = await bridge.campus_fast_travel_completed
	assert(bool(map_travel_resolution[0]), "campus map travel failed: %s" % map_travel_resolution[1])
	await process_frame
	var after_map_snapshot: Dictionary = bridge.get("campus_snapshot")
	assert((after_map_snapshot.get("player", {}) as Dictionary).get("current_location_id") == "east_dorm_region")
	assert(after_map_snapshot.get("clock", {}) == before_map_clock)
	assert(int((after_map_snapshot.get("player", {}) as Dictionary).get("action_budget", {}).get("major_remaining", -1)) == before_map_budget)
	assert(String(presentation.get("current_map_id")) == "east_dorm_v5")
	map = current_scene.get_node("CampusMap") as Sprite2D
	assert(map.texture.get_size() == Vector2(1774, 887))
	var same_region_revision := int(after_map_snapshot.get("revision", -1))
	map_ui.call("_choose_map", "dormitory_double_v4")
	await process_frame
	assert(String(presentation.get("current_map_id")) == "dormitory_double_v4")
	assert(int((bridge.get("campus_snapshot") as Dictionary).get("revision", -2)) == same_region_revision)
	assert((current_scene.get_node("CampusMap") as Sprite2D).texture.get_size() == Vector2(3548, 887))

	print("CAMPUS_COLLAB_FLOW_OK")
	current_scene.queue_free()
	current_scene = null
	await process_frame
	await process_frame
	quit(0)
