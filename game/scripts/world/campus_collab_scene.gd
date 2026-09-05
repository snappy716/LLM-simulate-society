extends Node2D

const OUTDOOR_SCENE := "res://scenes/campus/campus_collab_test.tscn"
const LOBBY_SCENE := "res://scenes/debug/campus_lobby_test.tscn"
const EDGE_TRIGGER_SCENE := preload("res://scenes/world/components/campus_transition_trigger.tscn")

@export var edge_strip_width := 18.0
@export var edge_scroll_speed := 115.0
@export var return_speed := 420.0

var _map_size := Vector2(1774, 887)
var _walk_rect := Rect2(30, 620, 1714, 130)
var _rest_camera_offset_y := -180.0
var _camera_offset_y := -180.0
var _map_applied_once := false
var _pending_edge_arrival_ratio: Array = []
var _pending_edge_target_map_id := ""


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
	if player != null:
		if _pending_edge_arrival_ratio.size() == 2:
			player.global_position = Vector2(
				_walk_rect.position.x + _walk_rect.size.x * float(_pending_edge_arrival_ratio[0]),
				_walk_rect.position.y + _walk_rect.size.y * float(_pending_edge_arrival_ratio[1])
			).clamp(_walk_rect.position + Vector2(36, 36), _walk_rect.end - Vector2(36, 36))
			_pending_edge_arrival_ratio.clear()
		elif _map_applied_once or not _walk_rect.has_point(player.global_position):
			player.global_position = Vector2(float(spawn_value[0]), float(spawn_value[1]))
	_configure_camera()
	_layout_route_anchors()
	_configure_map_specific_triggers(entry)
	_configure_edge_transitions(entry)
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


func _configure_map_specific_triggers(entry: Dictionary) -> void:
	var entrance := get_node_or_null("StudentCenterEntrance") as Area2D
	var arrival := get_node_or_null("StudentCenterOutdoorArrival") as Node2D
	var active := String(entry.get("id", "")) == "living_area"
	if entrance != null:
		entrance.visible = active
		entrance.set_deferred("monitoring", active)
		if active:
			entrance.global_position = Vector2(
				_walk_rect.position.x + _walk_rect.size.x * 0.22,
				_walk_rect.position.y + _walk_rect.size.y * 0.18
			)
	if arrival != null and active:
		arrival.global_position = Vector2(entrance.global_position.x, entrance.global_position.y + 48.0)


func _configure_edge_transitions(entry: Dictionary) -> void:
	var container := get_node_or_null("MapEdgeTransitions") as Node2D
	var label_container := get_node_or_null("MapEdgeLabels") as Node2D
	if container == null or label_container == null:
		return
	for child in container.get_children():
		(child as Area2D).set_deferred("monitoring", false)
		container.remove_child(child)
		child.queue_free()
	for child in label_container.get_children():
		label_container.remove_child(child)
		child.queue_free()
	for value in entry.get("edge_exits", []):
		if not value is Dictionary:
			continue
		var exit_config: Dictionary = value
		var trigger = EDGE_TRIGGER_SCENE.instantiate()
		# Physics still holds the old player transform during a map swap.
		# Arm new areas only after the arrival transform has reached physics.
		trigger.monitoring = false
		trigger.name = String(exit_config.get("id", "MapEdge"))
		trigger.passage_id = String(exit_config.get("passage_id", ""))
		trigger.position = _edge_world_position(exit_config)
		trigger.scale = _edge_trigger_scale(exit_config)
		trigger.traversal_resolved.connect(_on_edge_traversal_resolved.bind(exit_config.duplicate(true)))
		container.add_child(trigger)
		_arm_edge_after_arrival(trigger)
		_add_edge_label(label_container, exit_config, trigger.position)


func _arm_edge_after_arrival(trigger: Area2D) -> void:
	await get_tree().physics_frame
	await get_tree().physics_frame
	if is_instance_valid(trigger) and not trigger.is_queued_for_deletion() and trigger.is_inside_tree():
		trigger.set_deferred("monitoring", true)


func _edge_world_position(exit_config: Dictionary) -> Vector2:
	var edge := String(exit_config.get("edge", "right"))
	var ratio := clampf(float(exit_config.get("position_ratio", 0.5)), 0.08, 0.92)
	match edge:
		"left":
			return Vector2(_walk_rect.position.x + 10.0, _walk_rect.position.y + _walk_rect.size.y * ratio)
		"right":
			return Vector2(_walk_rect.end.x - 10.0, _walk_rect.position.y + _walk_rect.size.y * ratio)
		"top":
			return Vector2(_walk_rect.position.x + _walk_rect.size.x * ratio, _walk_rect.position.y + 10.0)
		"bottom":
			return Vector2(_walk_rect.position.x + _walk_rect.size.x * ratio, _walk_rect.end.y - 10.0)
	return _walk_rect.get_center()


func _edge_trigger_scale(exit_config: Dictionary) -> Vector2:
	var edge := String(exit_config.get("edge", "right"))
	# Keep a narrow normal axis so small ground strips have a safe arrival zone.
	return Vector2(0.75, 3.0) if edge in ["left", "right"] else Vector2(3.0, 0.75)


func _add_edge_label(container: Node2D, exit_config: Dictionary, edge_position: Vector2) -> void:
	var edge := String(exit_config.get("edge", "right"))
	var label := Label.new()
	label.name = "%sLabel" % String(exit_config.get("id", "MapEdge"))
	label.text = "%s  %s" % [_edge_arrow(edge), String(exit_config.get("label", "前往相邻区域"))]
	label.add_theme_font_size_override("font_size", 15)
	label.add_theme_color_override("font_color", Color(0.88, 0.95, 1.0))
	label.add_theme_color_override("font_shadow_color", Color.BLACK)
	label.add_theme_constant_override("shadow_offset_x", 2)
	label.add_theme_constant_override("shadow_offset_y", 2)
	label.position = edge_position + {
		"left": Vector2(24, -15),
		"right": Vector2(-166, -15),
		"top": Vector2(-72, 22),
		"bottom": Vector2(-72, -44),
	}.get(edge, Vector2.ZERO)
	container.add_child(label)


func _edge_arrow(edge: String) -> String:
	return {"left": "←", "right": "→", "top": "↑", "bottom": "↓"}.get(edge, "→")


func _on_edge_traversal_resolved(success: bool, result: Dictionary, exit_config: Dictionary) -> void:
	if not success:
		var label := get_node_or_null("UI/CurrentMap") as Label
		if label != null:
			var command_result: Dictionary = result.get("result", {})
			label.text = "无法通行：%s" % command_result.get("message", result.get("error", "未知错误"))
		return
	var target_map_id := String(exit_config.get("target_map_id", ""))
	var presentation := get_node("/root/CampusPresentation")
	if (presentation.call("get_map", target_map_id) as Dictionary).is_empty():
		push_error("校园边缘出口指向未知地图：%s" % target_map_id)
		return
	_pending_edge_arrival_ratio = (exit_config.get("target_arrival_ratio", []) as Array).duplicate()
	_pending_edge_target_map_id = target_map_id
	call_deferred("_complete_edge_map_change")


func _complete_edge_map_change() -> void:
	if _pending_edge_target_map_id.is_empty():
		return
	var target_map_id := _pending_edge_target_map_id
	_pending_edge_target_map_id = ""
	get_node("/root/CampusPresentation").call("select_map", target_map_id)


func _ui_is_open() -> bool:
	for group_name in ["campus_map_ui", "campus_phone_ui", "campus_npc_inspector_ui"]:
		var ui = get_tree().get_first_node_in_group(group_name)
		if ui != null and ui.is_open():
			return true
	return false
