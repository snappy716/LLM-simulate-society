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
var _population: Dictionary = {}
var _active_routes := 0
var _scene_route_points: Dictionary = {}
var _current_map_entry: Dictionary = {}
var _visible_actors: Dictionary = {}


func _ready() -> void:
	add_to_group("campus_npc_movement_layer")
	_refresh_scene_route_anchors()
	SimulationBridge.campus_snapshot_updated.connect(_on_snapshot_updated)
	SimulationBridge.campus_phase_advanced.connect(_on_phase_advanced)
	var presentation := get_node("/root/CampusPresentation")
	presentation.connect("map_changed", _on_map_changed)
	_current_map_entry = presentation.call("get_map")
	if not SimulationBridge.campus_snapshot.is_empty():
		_on_snapshot_updated(SimulationBridge.campus_snapshot)


func _on_snapshot_updated(snapshot: Dictionary) -> void:
	_places = snapshot.get("places", {})
	_population = snapshot.get("population", {})
	if _active_routes == 0:
		call_deferred("_refresh_residents")


func _on_map_changed(entry: Dictionary) -> void:
	_current_map_entry = entry.duplicate(true)
	call_deferred("_refresh_residents")


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
		_refresh_residents()
		movement_replay_finished.emit()


func _spawn_route_actor(actor_id: String, points: PackedVector2Array, data: Dictionary) -> void:
	if npc_scene == null:
		push_error("校园 NPC 移动层没有配置 npc_scene")
		return
	var npc = _create_visible_npc(actor_id, data)
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
	if not _location_is_visible(destination_id) and is_instance_valid(npc):
		_visible_actors.erase(String(npc.npc_id))
		npc.queue_free()
	elif is_instance_valid(npc):
		npc.set_campus_profile(_population.get(String(npc.npc_id), {}))
	if _active_routes == 0:
		_refresh_residents()
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
	if use_scene_route_anchors:
		var anchor_cursor := location_id
		var anchor_visited: Dictionary = {}
		while _places.has(anchor_cursor) and not anchor_visited.has(anchor_cursor):
			anchor_visited[anchor_cursor] = true
			if _scene_route_points.has(anchor_cursor):
				return _scene_route_points[anchor_cursor]
			var anchor_place: Dictionary = _places[anchor_cursor]
			var region_id := String(anchor_place.get("region_id", ""))
			if _scene_route_points.has(region_id):
				return _scene_route_points[region_id]
			anchor_cursor = String(anchor_place.get("parent_id", region_id))
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
	if _active_routes == 0:
		call_deferred("_refresh_residents")


func nearest_interactable_npc(origin: Vector2, max_distance: float = 76.0) -> Node:
	var nearest: Node2D
	var nearest_distance := max_distance
	for actor in _visible_actors.values():
		if not is_instance_valid(actor) or not actor is Node2D:
			continue
		var distance := origin.distance_to(actor.global_position)
		if distance <= nearest_distance:
			nearest = actor
			nearest_distance = distance
	return nearest


func visible_resident_count() -> int:
	var count := 0
	for actor in _visible_actors.values():
		if is_instance_valid(actor):
			count += 1
	return count


func _refresh_residents() -> void:
	if _active_routes > 0 or _places.is_empty() or _population.is_empty():
		return
	var desired_ids: Array[String] = []
	var actor_ids: Array = _population.keys()
	actor_ids.sort()
	for actor_id_value in actor_ids:
		var actor_id := String(actor_id_value)
		if actor_id == "player":
			continue
		var data: Dictionary = _population.get(actor_id, {})
		if not _location_is_visible(String(data.get("current_location_id", ""))):
			continue
		desired_ids.append(actor_id)
		if desired_ids.size() >= max_visible_npcs:
			break

	for actor_id_value in _visible_actors.keys():
		var actor_id := String(actor_id_value)
		if actor_id in desired_ids:
			continue
		var actor = _visible_actors.get(actor_id)
		if is_instance_valid(actor):
			actor.queue_free()
		_visible_actors.erase(actor_id)

	for desired_index in range(desired_ids.size()):
		var actor_id := desired_ids[desired_index]
		var data: Dictionary = _population.get(actor_id, {})
		var actor = _visible_actors.get(actor_id)
		if not is_instance_valid(actor):
			actor = _create_visible_npc(actor_id, data)
		actor.set_campus_profile(data)
		var location_id := String(data.get("current_location_id", ""))
		var point_value = _world_point_for_location(location_id)
		if point_value is Vector2:
			actor.global_position = (
				point_value as Vector2
				if desired_index == 0
				else _resident_world_point(actor_id, point_value as Vector2)
			)
		actor.set_move_direction(Vector2.ZERO)
	last_replayed_count = visible_resident_count()


func _create_visible_npc(actor_id: String, data: Dictionary) -> Node:
	var npc = npc_scene.instantiate()
	npc.npc_id = actor_id
	npc.body_type = "male" if int(data.get("appearance_seed", 0)) % 2 == 0 else "female"
	npc.world_seed = int(data.get("appearance_seed", 42))
	npc.simulation_controlled = true
	npc.show_name_label = false
	npc.collision_layer = 0
	npc.collision_mask = 0
	npc.name = "CampusNpc_%s" % actor_id
	add_child(npc)
	npc.add_to_group("campus_interactable_npc")
	npc.set_campus_profile(data)
	_visible_actors[actor_id] = npc
	return npc


func _location_is_visible(location_id: String) -> bool:
	return _region_for_location(location_id) in _visible_region_ids()


func _visible_region_ids() -> Array[String]:
	var result: Array[String] = []
	for value in _current_map_entry.get(
		"visible_region_ids",
		[String(_current_map_entry.get("semantic_location_id", ""))]
	):
		var region_id := String(value)
		if not region_id.is_empty():
			result.append(region_id)
	return result


func _region_for_location(location_id: String) -> String:
	var cursor := location_id
	var visited: Dictionary = {}
	while _places.has(cursor) and not visited.has(cursor):
		visited[cursor] = true
		var place: Dictionary = _places[cursor]
		if String(place.get("node_type", "")) == "region":
			return cursor
		var region_id := String(place.get("region_id", ""))
		if not region_id.is_empty():
			return region_id
		cursor = String(place.get("parent_id", ""))
	return ""


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


func _stable_route_offset(actor_id: String) -> Vector2:
	var stable := absi(actor_id.hash())
	return Vector2(float(stable % 7 - 3) * 18.0, float(int(stable / 7) % 5 - 2) * 10.0)


func _resident_world_point(actor_id: String, anchor: Vector2) -> Vector2:
	var stable := absi(actor_id.hash())
	var target := anchor + Vector2(
		float(stable % 17 - 8) * 34.0,
		float(int(stable / 17) % 5 - 2) * 12.0
	)
	var rect_value: Array = _current_map_entry.get("walk_rect", [0, 0, 1774, 887])
	var walk_rect := Rect2(
		float(rect_value[0]), float(rect_value[1]),
		float(rect_value[2]), float(rect_value[3])
	)
	return target.clamp(walk_rect.position + Vector2(18, 18), walk_rect.end - Vector2(18, 18))


func _clear_replay() -> void:
	for child in get_children():
		child.queue_free()
	_visible_actors.clear()
	last_replayed_count = 0
	_active_routes = 0
