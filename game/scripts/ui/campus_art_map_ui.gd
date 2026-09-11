extends CanvasLayer
const KIT = preload("res://scripts/ui/campus_ui_kit.gd")
const ART = preload("res://scripts/ui/campus_ui_art.gd")

var _overlay: ColorRect
var _grid: GridContainer
var _status: Label
var _opened := false
var _pending_map_id := ""
var _selected_map_id := ""
var _preview: TextureRect
var _detail: Label
var _travel: Button
var _panel: PanelContainer


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("campus_map_ui")
	_build_ui()
	SimulationBridge.campus_fast_travel_completed.connect(_on_fast_travel_completed)


func _unhandled_input(event: InputEvent) -> void:
	if InterfaceSettings.is_open():
		return
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
	_overlay.color = Color(0.015, 0.035, 0.065, 0.68)
	_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	_overlay.visible = false
	add_child(_overlay)

	var panel := PanelContainer.new()
	_panel = panel
	panel.set_anchors_preset(Control.PRESET_CENTER)
	_overlay.add_child(panel)
	_overlay.resized.connect(_fit_panel)
	call_deferred("_fit_panel")
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
	ART.page_header(title, "map")
	var hint := Label.new()
	hint.text = "先查看地点，再确认前往 · 校园移动不消耗主要行动"
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(hint)
	var split := HBoxContainer.new()
	split.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_child(split)
	var scroll := KIT.scroll_body()
	scroll.size_flags_stretch_ratio = 0.8
	split.add_child(scroll)
	_grid = GridContainer.new()
	_grid.columns = 1
	_grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_grid.add_theme_constant_override("h_separation", 8)
	_grid.add_theme_constant_override("v_separation", 8)
	scroll.add_child(_grid)
	var detail_scroll := KIT.scroll_body()
	split.add_child(detail_scroll)
	var details := VBoxContainer.new()
	details.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	detail_scroll.add_child(details)
	_preview = TextureRect.new()
	_preview.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_preview.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	_preview.custom_minimum_size.y = 160
	details.add_child(_preview)
	_detail = KIT.label("选择区域查看入口、公开任务与本人约定。")
	details.add_child(_detail)
	_travel = KIT.button("前往所选区域", func():
		if not _selected_map_id.is_empty() and _pending_map_id.is_empty(): _choose_map(_selected_map_id)
	, "primary")
	_travel.disabled = true
	column.add_child(_travel)
	_status = Label.new()
	_status.text = "M 关闭校园地图"
	_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_status)
	var close := Button.new()
	close.text = "关闭地图（M）"
	ART.apply_icon(close, "close")
	close.pressed.connect(_set_open.bind(false))
	column.add_child(close)
	_rebuild_buttons()


func _rebuild_buttons() -> void:
	for child in _grid.get_children():
		child.queue_free()
	for entry in get_node("/root/CampusPresentation").call("all_maps"):
		var button := Button.new()
		button.custom_minimum_size = Vector2(220, 54)
		button.text = "%s\n%s" % [
			String(entry.get("name", entry.get("id", ""))),
			String(entry.get("group", "校园")),
		]
		button.pressed.connect(_select_map.bind(String(entry.get("id", ""))))
		_grid.add_child(button)
		var symbols := {"campus_gate":"gate", "living_area":"living", "east_dormitory":"dorm", "west_dormitory":"dorm", "psychology_bridge":"bridge", "library":"library", "sports_field":"sport"}
		ART.apply_icon(button, "place_" + String(symbols.get(entry.get("id"), "gate")), 26)


func _fit_panel() -> void:
	var extent := Vector2(minf(1000, _overlay.size.x - 32), minf(720, _overlay.size.y - 32))
	_panel.offset_left = -extent.x / 2
	_panel.offset_right = extent.x / 2
	_panel.offset_top = -extent.y / 2
	_panel.offset_bottom = extent.y / 2


func _select_map(map_id: String) -> void:
	_selected_map_id = map_id
	var entry: Dictionary = get_node("/root/CampusPresentation").call("get_map", map_id)
	if entry.is_empty(): return
	_preview.texture = load(String(entry.texture_path))
	var regions: Array = entry.get("visible_region_ids", [])
	var snapshot := SimulationBridge.campus_snapshot
	var phase := String(snapshot.get("clock", {}).get("phase", "morning"))
	var lines := PackedStringArray([String(entry.get("name", "校园区域")), "\n道路连接"])
	for exit in entry.get("edge_exits", []): lines.append("› " + String(exit.get("label", "道路出口")))
	lines.append("\n建筑与室内 · 开放不等于具备进入资格")
	for place in snapshot.get("places", {}).values():
		if place.get("region_id") not in regions or place.get("node_type") == "region": continue
		if "private" in place.get("tags", []) or "main_story" in place.get("tags", []): continue
		var opened: bool = phase in place.get("open_phases", [])
		lines.append("%s · %s" % [place.get("name", "地点"), "当前开放" if opened else "当前未开放"])
	lines.append("\n已知委托")
	var count := 0
	for task in snapshot.get("tasks", {}).values():
		var place: Dictionary = snapshot.get("places", {}).get(task.get("scene_id", ""), {})
		if place.get("region_id", task.get("scene_id")) in regions and task.get("state") in ["open", "viewed", "considering", "locked", "in_progress"]:
			lines.append("%s%s" % ["我的 · " if task.get("owned_by_player", false) else "", task.get("title", "委托")])
			count += 1
	if count == 0: lines.append("暂无公开的进行中委托。")
	for notice in snapshot.get("forums", {}).get("night", {}).get("situations", []):
		if notice.get("id") in regions: lines.append("\n已知夜相区域 · " + String(notice.get("summary", "")))
	lines.append("\n当前公开活动")
	var offer_count := 0
	for offer in snapshot.get("agenda", {}).get("life", {}).get("offers", []):
		var place: Dictionary = snapshot.get("places", {}).get(offer.get("location_id", ""), {})
		if place.get("region_id", offer.get("location_id")) in regions and int(offer.get("day", 0)) == int(snapshot.get("clock", {}).get("day", 1)) and offer.get("phase") == phase:
			lines.append(String(offer.get("name", "校园活动")) + " · 请在日程页核验报名与到场条件")
			offer_count += 1
	if offer_count == 0: lines.append("此时段没有已公布的活动。")
	for row in snapshot.get("agenda", {}).get("commitments", []):
		var place: Dictionary = snapshot.get("places", {}).get(row.get("location_id", ""), {})
		if place.get("region_id", row.get("location_id")) in regions: lines.append("约定 · 第 %d 天 · %s" % [int(row.day), row.label])
	_detail.text = "\n".join(lines)
	_travel.disabled = not _pending_map_id.is_empty()


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
	_travel.disabled = true
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
		_travel.disabled = false
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
		for group_name in ["campus_phone_ui", "campus_npc_inspector_ui"]:
			var other_ui = get_tree().get_first_node_in_group(group_name)
			if other_ui != null and other_ui.is_open():
				return
	_opened = value
	_overlay.visible = value
	_pending_map_id = ""
	if value:
		var current_map: Dictionary = get_node("/root/CampusPresentation").call("get_map")
		_status.text = "当前：%s · M 关闭校园地图" % current_map.get("name", "未知地图")
		_select_map(String(current_map.get("id", "")))
	get_tree().paused = value
