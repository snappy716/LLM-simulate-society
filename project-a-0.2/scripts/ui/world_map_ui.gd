extends CanvasLayer

const MAP_SIZE := Vector2i(400, 400)
const TYPE_NAMES := ["水域", "普通地块", "道路/广场", "建筑占地", "花园"]

@onready var map_panel: Control = $MapPanel
@onready var map_viewport: Control = $MapPanel/Frame/MapViewport
@onready var map_image: TextureRect = $MapPanel/Frame/MapViewport/MapImage
@onready var player_marker: Control = $MapPanel/Frame/MapViewport/MapImage/PlayerMarker
@onready var coordinates_label: Label = $MapPanel/Frame/Coordinates
@onready var editor_bar: Control = $MapPanel/Frame/EditorBar
@onready var edit_button: Button = $MapPanel/Frame/EditMode
@onready var edit_status: Label = $MapPanel/Frame/EditorBar/Status
@onready var zoom_label: Label = $MapPanel/Frame/ZoomLabel

var player: Node2D
var city_tiles: TileMapLayer
var map_model: Node
var edit_mode := false
var selected_kind := 3
var brush_size := 3
var painting := false
var current_stroke := {}
var undo_stack: Array = []
var redo_stack: Array = []
var zoom_level := 1.0
var panning := false


func _ready() -> void:
	map_panel.visible = false
	editor_bar.visible = false
	map_image.gui_input.connect(_on_map_gui_input)
	edit_button.pressed.connect(_toggle_edit_mode)
	$MapPanel/Frame/EditorBar/Water.pressed.connect(func(): _select_kind(0))
	$MapPanel/Frame/EditorBar/Land.pressed.connect(func(): _select_kind(1))
	$MapPanel/Frame/EditorBar/Road.pressed.connect(func(): _select_kind(2))
	$MapPanel/Frame/EditorBar/Building.pressed.connect(func(): _select_kind(3))
	$MapPanel/Frame/EditorBar/Garden.pressed.connect(func(): _select_kind(4))
	$MapPanel/Frame/EditorBar/Brush1.pressed.connect(func(): _select_brush(1))
	$MapPanel/Frame/EditorBar/Brush3.pressed.connect(func(): _select_brush(3))
	$MapPanel/Frame/EditorBar/Brush5.pressed.connect(func(): _select_brush(5))
	$MapPanel/Frame/EditorBar/Undo.pressed.connect(_undo)
	$MapPanel/Frame/EditorBar/Redo.pressed.connect(_redo)
	$MapPanel/Frame/EditorBar/Save.pressed.connect(_save)
	$MapPanel/Frame/ZoomOut.pressed.connect(func(): _set_zoom(zoom_level / 1.25))
	$MapPanel/Frame/ZoomIn.pressed.connect(func(): _set_zoom(zoom_level * 1.25))
	$MapPanel/Frame/ResetView.pressed.connect(_reset_map_view)
	call_deferred("_find_world_nodes")


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("toggle_map"):
		map_panel.visible = not map_panel.visible
		if map_panel.visible:
			_find_world_nodes()
			_update_player_marker()
		else:
			_set_edit_mode(false)
		get_viewport().set_input_as_handled()
	elif map_panel.visible and event.is_action_pressed("toggle_map_edit"):
		_toggle_edit_mode()
		get_viewport().set_input_as_handled()
	elif map_panel.visible and edit_mode and event is InputEventKey and event.pressed:
		if event.ctrl_pressed and event.keycode == KEY_S:
			_save()
		elif event.ctrl_pressed and event.keycode == KEY_Z:
			_undo()
		elif event.ctrl_pressed and event.keycode == KEY_Y:
			_redo()


func _process(_delta: float) -> void:
	if map_panel.visible:
		_update_player_marker()


func _find_world_nodes() -> void:
	player = get_tree().get_first_node_in_group("player") as Node2D
	city_tiles = get_tree().get_first_node_in_group("city_tile_map") as TileMapLayer
	if city_tiles != null:
		map_model = city_tiles.get_parent()
		map_image.texture = map_model.get_layout_texture()


func _update_player_marker() -> void:
	if player == null or city_tiles == null:
		_find_world_nodes()
	if player == null or city_tiles == null:
		player_marker.visible = false
		coordinates_label.text = "正在定位玩家……"
		return
	var cell := city_tiles.local_to_map(city_tiles.to_local(player.global_position))
	cell.x = clampi(cell.x, 0, MAP_SIZE.x - 1)
	cell.y = clampi(cell.y, 0, MAP_SIZE.y - 1)
	var normalized := (Vector2(cell) + Vector2(0.5, 0.5)) / Vector2(MAP_SIZE)
	player_marker.position = normalized * map_image.size - player_marker.size * 0.5
	player_marker.visible = not edit_mode
	coordinates_label.text = "玩家位置  X: %03d  Y: %03d" % [cell.x, cell.y]


func _toggle_edit_mode() -> void:
	_set_edit_mode(not edit_mode)


func _set_edit_mode(enabled: bool) -> void:
	edit_mode = enabled
	editor_bar.visible = enabled
	edit_button.text = "退出矫正 (E)" if enabled else "进入矫正 (E)"
	player_marker.visible = not enabled
	_update_status("已进入矫正模式" if enabled else "")


func _select_kind(kind: int) -> void:
	selected_kind = kind
	_update_status("类型：%s" % TYPE_NAMES[kind])


func _select_brush(size: int) -> void:
	brush_size = size
	_update_status("画笔：%d×%d" % [size, size])


func _on_map_gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
			_set_zoom(zoom_level * 1.25, map_image.position + event.position)
			map_image.accept_event()
			return
		if event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
			_set_zoom(zoom_level / 1.25, map_image.position + event.position)
			map_image.accept_event()
			return
		if event.button_index == MOUSE_BUTTON_RIGHT or event.button_index == MOUSE_BUTTON_MIDDLE:
			panning = event.pressed
			map_image.accept_event()
			return
	if event is InputEventMouseMotion and panning:
		map_image.position += event.relative
		_clamp_map_position()
		map_image.accept_event()
		return
	if not edit_mode or map_model == null:
		return
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		painting = event.pressed
		if painting:
			current_stroke = {}
			_paint_at(event.position)
		else:
			_commit_stroke()
		map_image.accept_event()
	elif event is InputEventMouseMotion and painting and (event.button_mask & MOUSE_BUTTON_MASK_LEFT):
		_paint_at(event.position)
		map_image.accept_event()


func _paint_at(position: Vector2) -> void:
	var center := Vector2i(floor(position.x / map_image.size.x * MAP_SIZE.x), floor(position.y / map_image.size.y * MAP_SIZE.y))
	var radius := brush_size / 2
	for y in range(center.y - radius, center.y + radius + 1):
		for x in range(center.x - radius, center.x + radius + 1):
			var cell := Vector2i(x, y)
			if x < 0 or y < 0 or x >= MAP_SIZE.x or y >= MAP_SIZE.y:
				continue
			if not current_stroke.has(cell):
				var old_kind: int = map_model.get_cell_kind(cell)
				current_stroke[cell] = {"cell": cell, "old": old_kind, "new": selected_kind}
			map_model.set_cell_kind(cell, selected_kind)
	_update_status("正在绘制 %s  格子(%d,%d)" % [TYPE_NAMES[selected_kind], center.x, center.y])


func _commit_stroke() -> void:
	if current_stroke.is_empty():
		return
	undo_stack.append(current_stroke.values())
	redo_stack.clear()
	current_stroke = {}
	_update_status("修改尚未保存 · Ctrl+S 保存")


func _undo() -> void:
	if undo_stack.is_empty() or map_model == null:
		return
	var action: Array = undo_stack.pop_back()
	for change in action:
		map_model.set_cell_kind(change.cell, change.old)
	redo_stack.append(action)
	_update_status("已撤销 · Ctrl+S 保存")


func _redo() -> void:
	if redo_stack.is_empty() or map_model == null:
		return
	var action: Array = redo_stack.pop_back()
	for change in action:
		map_model.set_cell_kind(change.cell, change.new)
	undo_stack.append(action)
	_update_status("已重做 · Ctrl+S 保存")


func _save() -> void:
	if map_model == null:
		return
	var error: Error = map_model.save_layout()
	_update_status("保存成功：正交蓝图与游戏地图已同步" if error == OK else "保存失败，错误码：%s" % error)


func _update_status(message: String) -> void:
	edit_status.text = message


func _set_zoom(value: float, focus := Vector2(-1, -1)) -> void:
	var new_zoom := clampf(value, 1.0, 6.0)
	if is_equal_approx(new_zoom, zoom_level):
		return
	if focus.x < 0.0:
		focus = map_viewport.size * 0.5
	var point_ratio := (focus - map_image.position) / map_image.size
	zoom_level = new_zoom
	map_image.size = map_viewport.size * zoom_level
	map_image.position = focus - point_ratio * map_image.size
	_clamp_map_position()
	zoom_label.text = "%d%%" % roundi(zoom_level * 100.0)


func _clamp_map_position() -> void:
	var minimum := map_viewport.size - map_image.size
	map_image.position.x = clampf(map_image.position.x, minimum.x, 0.0)
	map_image.position.y = clampf(map_image.position.y, minimum.y, 0.0)


func _reset_map_view() -> void:
	zoom_level = 1.0
	map_image.position = Vector2.ZERO
	map_image.size = map_viewport.size
	zoom_label.text = "100%"
