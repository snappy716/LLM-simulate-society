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

	var map := outdoor.get_node("CampusMap") as Sprite2D
	assert(map.texture != null)
	assert(map.texture.get_size() == Vector2(1774, 887))
	var camera := outdoor.get_node("Player/Camera2D") as Camera2D
	assert(camera.limit_right == 1774)
	assert(camera.limit_bottom == 887)
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

	print("CAMPUS_COLLAB_FLOW_OK")
	current_scene.queue_free()
	current_scene = null
	await process_frame
	await process_frame
	quit(0)
