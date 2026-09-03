extends SceneTree

const OUTDOOR_SCENE := "res://scenes/debug/campus_navigation_test.tscn"


func _initialize() -> void:
	call_deferred("_run_flow")


func _run_flow() -> void:
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(100):
		var snapshot = bridge.get("campus_snapshot")
		if snapshot is Dictionary and not snapshot.is_empty():
			break
		await create_timer(0.05).timeout
	var initial_snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(not initial_snapshot.is_empty(), "campus snapshot did not connect")
	assert(initial_snapshot.get("revision") == 1)
	assert((initial_snapshot.get("player", {}) as Dictionary).get("current_location_id") == "south_gate_region")

	var outdoor_scene := load(OUTDOOR_SCENE) as PackedScene
	assert(outdoor_scene != null)
	var outdoor = outdoor_scene.instantiate()
	root.add_child(outdoor)
	current_scene = outdoor
	await process_frame

	var road = outdoor.get_node("RoadBoundary")
	road.call("request_traversal")
	var road_resolution = await road.traversal_resolved
	assert(bool(road_resolution[0]), "road traversal failed: %s" % road_resolution[1])
	await process_frame
	var road_snapshot: Dictionary = bridge.get("campus_snapshot")
	assert((road_snapshot.get("player", {}) as Dictionary).get("current_location_id") == "student_life_region")
	assert(current_scene == outdoor, "continuous outdoor boundary changed the Godot scene")

	var entrance = outdoor.get_node("StudentCenterEntrance")
	entrance.call("request_traversal")
	var entrance_resolution = await entrance.traversal_resolved
	assert(bool(entrance_resolution[0]), "building entrance failed: %s" % entrance_resolution[1])
	for _attempt in range(30):
		await process_frame
		if current_scene != outdoor:
			break
	assert(current_scene != outdoor, "building entrance did not change to an interior scene")
	assert(current_scene.name == "CampusLobbyGraybox")
	var lobby_player := current_scene.get_node("Player") as Node2D
	for _attempt in range(30):
		if lobby_player.position.distance_to(Vector2(640, 535)) < 1.0:
			break
		await process_frame
	assert(lobby_player.position.distance_to(Vector2(640, 535)) < 1.0, "interior arrival anchor was not applied")

	var exit_trigger = current_scene.get_node("StudentCenterExit")
	exit_trigger.call("request_traversal")
	var exit_resolution = await exit_trigger.traversal_resolved
	assert(bool(exit_resolution[0]), "building exit failed: %s" % exit_resolution[1])
	var lobby_scene = current_scene
	for _attempt in range(30):
		await process_frame
		if current_scene != lobby_scene:
			break
	assert(current_scene != lobby_scene, "building exit did not return outdoors")
	assert(current_scene.name == "CampusNavigationGraybox")
	var returned_player := current_scene.get_node("Player") as Node2D
	for _attempt in range(30):
		if returned_player.position.distance_to(Vector2(301, 280)) < 1.0:
			break
		await process_frame
	assert(returned_player.position.distance_to(Vector2(301, 280)) < 1.0, "outdoor return anchor was not applied")
	var final_snapshot: Dictionary = bridge.get("campus_snapshot")
	assert((final_snapshot.get("player", {}) as Dictionary).get("current_location_id") == "student_life_region")
	assert(final_snapshot.get("revision") == 4)

	print("CAMPUS_NAVIGATION_FLOW_OK")
	quit(0)
