extends Node2D

const OUTDOOR_SCENE := "res://scenes/campus/campus_collab_test.tscn"
const LOBBY_SCENE := "res://scenes/debug/campus_lobby_test.tscn"

@export var edge_strip_width := 18.0
@export var edge_scroll_speed := 115.0
@export var return_speed := 420.0

var _map_size := Vector2(1774, 887)
var _walk_rect := Rect2(30, 620, 1714, 130)
var _rest_camera_offset_y := -180.0
var _camera_offset_y := -180.0
var _map_applied_once := false


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("campus_art_camera")
	var navigation := get_node("/root/CampusNavigation")
	navigation.call("register_presentation_scene", "campus_outdoor", OUTDOOR_SCENE)
	navigation.call("register_presentation_scene", "interior_building_lobby", LOBBY_SCENE)
	var presentation := get_node("/root/CampusPresentation")
	presentation.connect("map_changed", _apply_map)
	_apply_map(presentation.call("get_map"))


func _process(delta: float) -> void:
	if get_tree().paused or _ui_is_open():
		return
	var camera := get_node_or_null("Player/Camera2D") as Camera2D
	if camera == null:
		return
	var mouse_y := get_viewport().get_mouse_position().y
	var viewport_height := get_viewport().get_visible_rect().size.y
	if mouse_y <= edge_strip_width:
		_camera_offset_y -= edge_scroll_speed * delta
	elif mouse_y >= viewport_height - edge_strip_width:
		_camera_offset_y += edge_scroll_speed * delta
	else:
		_camera_offset_y = move_toward(_camera_offset_y, _rest_camera_offset_y, return_speed * delta)
	_camera_offset_y = clampf(_camera_offset_y, -360.0, 120.0)
	camera.position.y = _camera_offset_y


func _physics_process(_delta: float) -> void:
	var player := get_node_or_null("Player") as Node2D
	if player != null:
		player.global_position = player.global_position.clamp(_walk_rect.position, _walk_rect.end)


func set_zoom_multiplier(value: int) -> void:
	var multiplier := clampi(value, 1, 3)
	get_node("/root/CampusPresentation").call("set_camera_zoom_multiplier", multiplier)
	var camera := get_node_or_null("Player/Camera2D") as Camera2D
	if camera != null:
		camera.zoom = Vector2(multiplier, multiplier)


func get_zoom_multiplier() -> int:
	return int(get_node("/root/CampusPresentation").call("get_camera_zoom_multiplier"))


func _apply_map(entry: Dictionary) -> void:
	if entry.is_empty():
		return
	var texture_path := String(entry.get("texture_path", ""))
	var texture := load(texture_path) as Texture2D
	if texture == null:
		push_error("校园地图纹理加载失败：%s" % texture_path)
		return
	var map := get_node_or_null("CampusMap") as Sprite2D
	if map != null:
		map.texture = texture
	var size_value: Array = entry.get("map_size", [texture.get_width(), texture.get_height()])
	_map_size = Vector2(float(size_value[0]), float(size_value[1]))
	var rect_value: Array = entry.get("walk_rect", [0, 0, _map_size.x, _map_size.y])
	_walk_rect = Rect2(float(rect_value[0]), float(rect_value[1]), float(rect_value[2]), float(rect_value[3]))
	var spawn_value: Array = entry.get("spawn", [_walk_rect.get_center().x, _walk_rect.get_center().y])
	var player := get_node_or_null("Player") as Node2D
	if player != null and (_map_applied_once or not _walk_rect.has_point(player.global_position)):
		player.global_position = Vector2(float(spawn_value[0]), float(spawn_value[1]))
	_configure_camera()
	_layout_route_anchors()
	_configure_map_specific_triggers(String(entry.get("id", "")))
	var label := get_node_or_null("UI/CurrentMap") as Label
	if label != null:
		label.text = "%s · M 地图 · T 手机" % entry.get("name", "校园")
	_map_applied_once = true


func _configure_camera() -> void:
	var camera := get_node_or_null("Player/Camera2D") as Camera2D
	if camera != null:
		camera.enabled = true
		_camera_offset_y = _rest_camera_offset_y
		camera.position = Vector2(0, _camera_offset_y)
		camera.limit_left = 0
		camera.limit_top = 0
		camera.limit_right = int(_map_size.x)
		camera.limit_bottom = int(_map_size.y)
		set_zoom_multiplier(int(get_node("/root/CampusPresentation").call("get_camera_zoom_multiplier")))


func _layout_route_anchors() -> void:
	var ratios := {
		"sports_health_region": 0.08,
		"humanities_psychology_region": 0.17,
		"west_dorm_region": 0.25,
		"science_teaching_region": 0.34,
		"research_innovation_region": 0.43,
		"central_region": 0.52,
		"student_life_region": 0.66,
		"east_dorm_region": 0.75,
		"south_gate_region": 0.86,
		"service_logistics_region": 0.93,
		"student_center": 0.19,
		"campus_supermarket": 0.58,
		"campus_canteen": 0.63,
		"psychology_center": 0.16,
	}
	for marker in get_tree().get_nodes_in_group("campus_route_anchor"):
		if not marker is Node2D:
			continue
		var location_id := String(marker.get_meta("location_id", ""))
		var ratio := float(ratios.get(location_id, 0.5))
		marker.global_position = Vector2(
			_walk_rect.position.x + _walk_rect.size.x * ratio,
			_walk_rect.position.y + _walk_rect.size.y * (0.54 + float(absi(location_id.hash()) % 5 - 2) * 0.035)
		)
	var movement_layer = get_node_or_null("NpcMovementLayer")
	if movement_layer != null:
		movement_layer.call("_refresh_scene_route_anchors")


func _configure_map_specific_triggers(map_id: String) -> void:
	var active := map_id == "campus_gate"
	for node_name in ["RoadBoundary", "StudentCenterEntrance"]:
		var trigger := get_node_or_null(node_name) as Area2D
		if trigger != null:
			trigger.visible = active
			trigger.set_deferred("monitoring", active)


func _ui_is_open() -> bool:
	for group_name in ["campus_map_ui", "campus_phone_ui"]:
		var ui = get_tree().get_first_node_in_group(group_name)
		if ui != null and ui.is_open():
			return true
	return false
