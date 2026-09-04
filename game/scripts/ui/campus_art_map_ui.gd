extends CanvasLayer

var _overlay: ColorRect
var _grid: GridContainer
var _status: Label
var _opened := false
var _pending_map_id := ""


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("campus_map_ui")
	_build_ui()
	SimulationBridge.campus_fast_travel_completed.connect(_on_fast_travel_completed)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("toggle_map"):
		_set_open(not _opened)
		get_viewport().set_input_as_handled()
	elif _opened and event.is_action_pressed("ui_cancel"):
		_set_open(false)
		get_viewport().set_input_as_handled()


func is_open() -> bool:
	return _opened


func _build_ui() -> void:
	_overlay = ColorRect.new()
	_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_overlay.color = Color(0.015, 0.025, 0.04, 0.9)
	_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	_overlay.visible = false
	add_child(_overlay)

	var panel := PanelContainer.new()
	panel.set_anchors_preset(Control.PRESET_CENTER)
	panel.position = Vector2(-430, -245)
	panel.size = Vector2(860, 490)
	_overlay.add_child(panel)
	var margin := MarginContainer.new()
	for side in ["left", "top", "right", "bottom"]:
		margin.add_theme_constant_override("margin_%s" % side, 20)
	panel.add_child(margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 10)
	margin.add_child(column)
	var title := Label.new()
	title.text = "校园地图"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 26)
	column.add_child(title)
	var hint := Label.new()
	hint.text = "选择校园区域；校园移动不消耗分钟和主要行动。"
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(hint)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_child(scroll)
	_grid = GridContainer.new()
	_grid.columns = 3
	_grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_grid.add_theme_constant_override("h_separation", 8)
	_grid.add_theme_constant_override("v_separation", 8)
	scroll.add_child(_grid)
	_status = Label.new()
	_status.text = "M 关闭校园地图"
	_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_status)
	var close := Button.new()
	close.text = "关闭地图（M）"
	close.pressed.connect(_set_open.bind(false))
	column.add_child(close)
	_rebuild_buttons()


func _rebuild_buttons() -> void:
	for child in _grid.get_children():
		child.queue_free()
	for entry in get_node("/root/CampusPresentation").call("all_maps"):
		var button := Button.new()
		button.custom_minimum_size = Vector2(255, 54)
		button.text = "%s\n%s" % [
			String(entry.get("name", entry.get("id", ""))),
			String(entry.get("group", "校园")),
		]
		button.pressed.connect(_choose_map.bind(String(entry.get("id", ""))))
		_grid.add_child(button)


func _choose_map(map_id: String) -> void:
	var entry: Dictionary = get_node("/root/CampusPresentation").call("get_map", map_id)
	if entry.is_empty():
		_status.text = "找不到这张地图。"
		return
	var destination_id := String(entry.get("semantic_location_id", ""))
	if destination_id == _current_region_id():
		get_node("/root/CampusPresentation").call("select_map", map_id)
		_set_open(false)
		return
	_pending_map_id = map_id
	_status.text = "正在检查前往%s的校园路线……" % entry.get("name", map_id)
	get_tree().paused = false
	SimulationBridge.fast_travel_campus(destination_id)


func _on_fast_travel_completed(success: bool, result: Dictionary, _destination_id: String) -> void:
	if _pending_map_id.is_empty():
		return
	if not success:
		_status.text = "无法前往：%s" % _result_message(result)
		get_tree().paused = true
		_pending_map_id = ""
		return
	var selected := _pending_map_id
	_pending_map_id = ""
	get_node("/root/CampusPresentation").call("select_map", selected)
	_set_open(false)


func _current_region_id() -> String:
	var snapshot: Dictionary = SimulationBridge.campus_snapshot
	var player: Dictionary = snapshot.get("player", {})
	var current_id := String(player.get("current_location_id", ""))
	var places: Dictionary = snapshot.get("places", {})
	var place: Dictionary = places.get(current_id, {})
	if String(place.get("node_type", "")) == "region":
		return current_id
	return String(place.get("region_id", current_id))


func _result_message(result: Dictionary) -> String:
	var command_result: Dictionary = result.get("result", {})
	return String(command_result.get("message", result.get("error", "未知错误")))


func _set_open(value: bool) -> void:
	if value:
		var phone := get_tree().get_first_node_in_group("campus_phone_ui")
		if phone != null and phone.is_open():
			return
	_opened = value
	_overlay.visible = value
	_pending_map_id = ""
	if value:
		var current_map: Dictionary = get_node("/root/CampusPresentation").call("get_map")
		_status.text = "当前：%s · M 关闭校园地图" % current_map.get("name", "未知地图")
	get_tree().paused = value
