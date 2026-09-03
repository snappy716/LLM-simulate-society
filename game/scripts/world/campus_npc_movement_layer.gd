extends Node2D

signal movement_replay_started(visible_actor_count: int)
signal movement_replay_finished()

@export var npc_scene: PackedScene
@export_range(1, 40, 1) var max_visible_npcs := 18
@export var playback_speed := 320.0
@export var map_origin_cell := Vector2(195, 300)
@export var map_origin_world := Vector2(740, 300)
@export var map_scale := Vector2(3, 5)
@export var visibility_margin := 100.0
@export var use_scene_route_anchors := false

var last_replayed_count := 0
var _places: Dictionary = {}
var _active_routes := 0
var _scene_route_points: Dictionary = {}


func _ready() -> void:
	_refresh_scene_route_anchors()
	SimulationBridge.campus_snapshot_updated.connect(_on_snapshot_updated)
	SimulationBridge.campus_phase_advanced.connect(_on_phase_advanced)
	if not SimulationBridge.campus_snapshot.is_empty():
		_on_snapshot_updated(SimulationBridge.campus_snapshot)


func _on_snapshot_updated(snapshot: Dictionary) -> void:
	_places = snapshot.get("places", {})


func _on_phase_advanced(success: bool, response: Dictionary) -> void:
	if not success:
		return
	var snapshot: Dictionary = response.get("snapshot", {})
	if not snapshot.is_empty():
		_on_snapshot_updated(snapshot)
	var result: Dictionary = response.get("result", {})
	_replay_movement_events(result.get("events", []), snapshot)


func _replay_movement_events(events: Array, snapshot: Dictionary) -> void:
	_clear_replay()
	var route_locations: Dictionary = {}
	for event_value in events:
		if not event_value is Dictionary:
			continue
		var event: Dictionary = event_value
		if String(event.get("event_type", "")) != "ACTOR_LOCATION_CHANGED":
			continue
		var actor_ids: Array = event.get("actor_ids", [])
		if actor_ids.is_empty() or String(actor_ids[0]) == "player":
			continue
		var actor_id := String(actor_ids[0])
		var payload: Dictionary = event.get("payload", {})
		if not route_locations.has(actor_id):
			route_locations[actor_id] = [String(payload.get("from_id", ""))]
		(route_locations[actor_id] as Array).append(String(payload.get("to_id", "")))

	var population: Dictionary = snapshot.get("population", {})
	var actor_ids: Array = route_locations.keys()
	actor_ids.sort()
	for actor_id_value in actor_ids:
		if last_replayed_count >= max_visible_npcs:
			break
		var actor_id := String(actor_id_value)
		var points := _route_world_points(route_locations[actor_id])
		if points.size() < 2 or not _route_intersects_view(points):
			continue
		_spawn_route_actor(actor_id, points, population.get(actor_id, {}))

	movement_replay_started.emit(last_replayed_count)
	if _active_routes == 0:
		movement_replay_finished.emit()


func _spawn_route_actor(actor_id: String, points: PackedVector2Array, data: Dictionary) -> void:
	if npc_scene == null:
		push_error("校园 NPC 移动层没有配置 npc_scene")
		return
	var npc = npc_scene.instantiate()
	npc.npc_id = actor_id
	npc.body_type = "male" if int(data.get("appearance_seed", 0)) % 2 == 0 else "female"
	npc.world_seed = int(data.get("appearance_seed", 42))
	npc.simulation_controlled = true
	npc.show_name_label = false
	npc.collision_layer = 0
	npc.collision_mask = 0
	npc.name = "VisibleNpc_%02d" % last_replayed_count
	add_child(npc)
	var offset := _stable_route_offset(actor_id)
	var offset_points := PackedVector2Array()
	for point in points:
		offset_points.append(point + offset)
	var destination_id := String((data.get("current_activity", {}) as Dictionary).get("location_id", ""))
	npc.simulation_route_finished.connect(_on_route_finished.bind(npc, destination_id))
	_active_routes += 1
	last_replayed_count += 1
	npc.play_simulation_route(offset_points, playback_speed)


func _on_route_finished(_npc_id: String, npc: Node, destination_id: String) -> void:
	_active_routes = maxi(0, _active_routes - 1)
	if _is_indoor_destination(destination_id) and is_instance_valid(npc):
		npc.queue_free()
	if _active_routes == 0:
		movement_replay_finished.emit()


func _route_world_points(location_ids: Array) -> PackedVector2Array:
	var result := PackedVector2Array()
	for location_value in location_ids:
		var point_value = _world_point_for_location(String(location_value))
		if not point_value is Vector2:
			continue
		var point: Vector2 = point_value
		if result.is_empty() or result[result.size() - 1].distance_to(point) > 1.0:
			result.append(point)
	return result


func _world_point_for_location(location_id: String) -> Variant:
	var cursor := location_id
	var visited: Dictionary = {}
	while _places.has(cursor) and not visited.has(cursor):
		visited[cursor] = true
		if use_scene_route_anchors and _scene_route_points.has(cursor):
			return _scene_route_points[cursor]
		var place: Dictionary = _places[cursor]
		var cell_value = place.get("map_cell")
		if cell_value is Array and cell_value.size() == 2:
			var cell := Vector2(float(cell_value[0]), float(cell_value[1]))
			return map_origin_world + (cell - map_origin_cell) * map_scale
		cursor = String(place.get("parent_id", place.get("region_id", "")))
	return null


func _refresh_scene_route_anchors() -> void:
	_scene_route_points.clear()
	if not use_scene_route_anchors:
		return
	for candidate in get_tree().get_nodes_in_group("campus_route_anchor"):
		if not candidate is Node2D:
			continue
		var location_id := String(candidate.get_meta("location_id", ""))
		if location_id.is_empty():
			continue
		_scene_route_points[location_id] = candidate.global_position


func _route_intersects_view(points: PackedVector2Array) -> bool:
	var viewport_size := get_viewport_rect().size
	var inverse_canvas := get_viewport().get_canvas_transform().affine_inverse()
	var visible_top_left := inverse_canvas * Vector2.ZERO
	var visible_bottom_right := inverse_canvas * viewport_size
	var visible_rect := Rect2(
		visible_top_left - Vector2.ONE * visibility_margin,
		visible_bottom_right - visible_top_left + Vector2.ONE * visibility_margin * 2.0
	)
	for point in points:
		if visible_rect.has_point(point):
			return true
	return false


func _is_indoor_destination(location_id: String) -> bool:
	var place: Dictionary = _places.get(location_id, {})
	if String(place.get("node_type", "")) != "location":
		return false
	return String(place.get("kind", "")) != "outdoor_point"


func _stable_route_offset(actor_id: String) -> Vector2:
	var stable := absi(actor_id.hash())
	return Vector2(float(stable % 7 - 3) * 5.0, float(int(stable / 7) % 5 - 2) * 4.0)


func _clear_replay() -> void:
	for child in get_children():
		child.queue_free()
	last_replayed_count = 0
	_active_routes = 0
