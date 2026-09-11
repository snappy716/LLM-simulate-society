extends CanvasLayer
## Read-only persistent chrome. All actions remain in the existing authority-backed pages.

const ICONS := {
	"phone": preload("res://assets/ui/campus_moon/phone.svg"),
	"map": preload("res://assets/ui/campus_moon/map.svg"),
	"party": preload("res://assets/ui/campus_moon/party.svg"),
	"character": preload("res://assets/ui/campus_moon/character.svg"),
	"cards": preload("res://assets/ui/campus_moon/cards.svg"),
	"relationships": preload("res://assets/ui/campus_moon/relationships.svg"),
}
const SCENE_INK := preload("res://assets/ui/campus_moon/scene_ink.gdshader")
var location: Label
var clock: Label
var tracking: Button
var tracking_detail: Button
var cycle: Button
var phone: Button
var entries: Dictionary = {}
var _rows: Array[Dictionary] = []
var _selected := ""
var _expanded := true
var _shake: Tween
var _chrome: Control
var pulse_count := 0


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	layer = 24
	add_to_group("campus_hud")
	_selected = String(SimulationBridge.get_meta("hud_tracking_id", ""))
	_expanded = bool(SimulationBridge.get_meta("hud_tracking_expanded", true))
	_chrome = Control.new()
	_chrome.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_chrome.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_chrome)
	var column := VBoxContainer.new()
	column.position = Vector2(26, 24)
	column.custom_minimum_size.x = 340
	column.add_theme_constant_override("separation", 4)
	_chrome.add_child(column)
	location = _label(column, 18)
	clock = _label(column, 13)
	var gap := Control.new()
	gap.custom_minimum_size.y = 9
	column.add_child(gap)
	tracking = _text_button(column, "")
	tracking.pressed.connect(func(): _expanded = not _expanded; _render_tracking())
	tracking_detail = _text_button(column, "")
	tracking_detail.pressed.connect(_open_tracking)
	cycle = _text_button(column, "切换追踪 ›")
	cycle.pressed.connect(func():
		var index := 0
		for i in range(_rows.size()):
			if _rows[i].id == _selected: index = (i + 1) % _rows.size()
		_selected = _rows[index].id
		_render_tracking()
	)
	var right := HBoxContainer.new()
	right.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	right.position = Vector2(-272, 20)
	right.add_theme_constant_override("separation", 4)
	_chrome.add_child(right)
	for entry in [["map", "地图"], ["party", "队友"], ["character", "人物与物品"], ["cards", "卡牌库"], ["relationships", "关系 · 交友与恋爱"]]:
		var button := _icon_button(entry[0], entry[1])
		right.add_child(button)
		entries[entry[0]] = button
		button.pressed.connect(open_entry.bind(entry[0]))
	phone = _icon_button("phone", "手机 · 校园生活、时间与镜头（T）")
	_chrome.add_child(phone)
	phone.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	phone.offset_left = 24
	phone.offset_top = -70
	phone.offset_right = 70
	phone.offset_bottom = -24
	phone.pivot_offset = Vector2(23, 23)
	phone.pressed.connect(open_entry.bind("phone"))
	SimulationBridge.campus_snapshot_updated.connect(_render)
	_render(SimulationBridge.campus_snapshot)


func _label(parent: Node, font_size: int) -> Label:
	var label := Label.new()
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", Color("f5fbff"))
	label.add_theme_color_override("font_outline_color", Color("102536e6"))
	label.add_theme_constant_override("outline_size", 2)
	label.add_theme_color_override("font_shadow_color", Color("102536b3"))
	label.add_theme_constant_override("shadow_offset_x", 1)
	label.add_theme_constant_override("shadow_offset_y", 1)
	parent.add_child(label)
	return label


func _text_button(parent: Node, title: String) -> Button:
	var button := Button.new()
	button.text = title
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.custom_minimum_size.x = 340
	button.clip_text = true
	_flat(button)
	button.add_theme_font_size_override("font_size", 13)
	parent.add_child(button)
	return button


func _flat(button: Button) -> void:
	for state in ["normal", "hover", "pressed", "focus", "disabled"]:
		button.add_theme_stylebox_override(state, StyleBoxEmpty.new())
	button.add_theme_color_override("font_color", Color("f5fbff"))
	button.add_theme_color_override("font_hover_color", Color("8cddff"))
	button.add_theme_color_override("font_focus_color", Color("8cddff"))
	button.add_theme_color_override("font_outline_color", Color("102536e6"))
	button.add_theme_constant_override("outline_size", 2)
	button.add_theme_color_override("font_shadow_color", Color("102536b3"))
	button.add_theme_constant_override("shadow_offset_x", 1)
	button.add_theme_constant_override("shadow_offset_y", 1)


func _icon_button(id: String, title: String) -> Button:
	var button := Button.new()
	button.name = id.capitalize()
	button.icon = ICONS[id]
	button.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	button.expand_icon = true
	button.icon_alignment = HORIZONTAL_ALIGNMENT_CENTER
	button.add_theme_constant_override("icon_max_width", 30)
	button.custom_minimum_size = Vector2(46, 46)
	# Do not let a parent theme dim the already calibrated icon palette.
	for state in ["normal", "hover", "pressed", "focus"]:
		button.add_theme_color_override("icon_" + state + "_color", Color.WHITE)
	var ink := ShaderMaterial.new()
	ink.shader = SCENE_INK
	button.material = ink
	_set_ink_emphasis(0.0, button)
	button.tooltip_text = title
	_flat(button)
	button.mouse_entered.connect(_emphasize.bind(button))
	button.mouse_exited.connect(_emphasize.bind(button))
	button.focus_entered.connect(_emphasize.bind(button))
	button.focus_exited.connect(_emphasize.bind(button))
	return button


func _emphasize(button: Button) -> void:
	var old: Tween = button.get_meta("ink_tween") if button.has_meta("ink_tween") else null
	if old != null: old.kill()
	var active := button.has_focus() or button.get_global_rect().has_point(button.get_global_mouse_position())
	var transition := create_tween()
	# Method animation also works in headless builds without shader property reflection.
	transition.tween_method(_set_ink_emphasis.bind(button), float(button.get_meta("ink_emphasis")), 1.0 if active else 0.0, 0.16)
	button.set_meta("ink_tween", transition)


func _set_ink_emphasis(value: float, button: Button) -> void:
	button.set_meta("ink_emphasis", value)
	button.material.set_shader_parameter("emphasis", value)


func open_entry(id: String) -> void:
	if InterfaceSettings.is_open(): return
	var phone_ui := get_tree().get_first_node_in_group("campus_phone_ui")
	if id == "map":
		var map_ui := get_tree().get_first_node_in_group("campus_map_ui")
		if map_ui != null: map_ui.call("_set_open", true)
	elif phone_ui != null:
		phone_ui.call("open_hud_page", id)


func _render(snapshot: Dictionary) -> void:
	var date: Dictionary = snapshot.get("clock", {})
	var day := int(date.get("day", 1))
	var player: Dictionary = snapshot.get("player", {})
	location.text = String(snapshot.get("places", {}).get(player.get("current_location_id", ""), {}).get("name", "校园 · 正在同步"))
	clock.text = "第 %d 天 · %s · %s" % [day, SimulationBridge.weekday_display_name((day - 1) % 7), SimulationBridge.phase_display_name(String(date.get("phase", "morning")))]
	_rows.clear()
	for task in snapshot.get("tasks", {}).values():
		if task.get("owned_by_player", false) and task.get("state", "") in ["locked", "in_progress"]:
			_rows.append({"id": task.task_id, "kind": "task", "title": task.title, "detail": task.get("scene_name", ""), "forum": task.get("forum", "surface")})
	for row in snapshot.get("agenda", {}).get("commitments", []):
		_rows.append({"id": JSON.stringify([row.get("day"), row.get("phase"), row.get("label")]), "kind": "agenda", "title": row.get("label", "约定"), "detail": "第 %d 天 · %s · %s" % [int(row.day), SimulationBridge.phase_display_name(row.phase), row.get("location_name", "")]})
	_render_tracking()
	if not snapshot.is_empty(): _check_messages(snapshot)


func _render_tracking() -> void:
	SimulationBridge.set_meta("hud_tracking_expanded", _expanded)
	tracking.visible = not _rows.is_empty()
	tracking_detail.visible = _expanded and not _rows.is_empty()
	cycle.visible = _expanded and _rows.size() > 1
	if _rows.is_empty(): return
	var row := _rows[0]
	for item in _rows:
		if item.id == _selected: row = item
	_selected = row.id
	SimulationBridge.set_meta("hud_tracking_id", _selected)
	tracking.text = "%s %s · %s" % ["▾" if _expanded else "▸", "追踪事项" if row.kind == "task" else "近期约定", row.title]
	tracking.tooltip_text = row.title + "（点击折叠）"
	tracking_detail.text = "  " + row.detail
	tracking_detail.tooltip_text = row.detail + "（打开详情）"
	cycle.text = "切换事项 / 约定  ›  %d 项" % _rows.size()


func _open_tracking() -> void:
	var phone_ui := get_tree().get_first_node_in_group("campus_phone_ui")
	if phone_ui == null: return
	for row in _rows:
		if row.id != _selected: continue
		phone_ui.call("open_hud_page", "agenda" if row.kind == "agenda" else "forums")
		if row.kind == "task" and phone_ui.is_open():
			phone_ui.call("_set_forum_channel", row.forum)
			phone_ui.call("_open_task_detail", row.id)


func _check_messages(snapshot: Dictionary) -> void:
	# Metadata lives on the autoload, not the HUD/phone: scene changes cannot re-shake.
	var state: Dictionary = SimulationBridge.get_meta("hud_messages", {})
	var incoming: Dictionary = {}
	for thread in snapshot.get("messaging", {}).get("threads", {}).values():
		for message in thread.get("messages", []):
			if message.get("sender_id", "player") != "player": incoming[String(message.get("message_id", ""))] = true
	var date: Dictionary = snapshot.get("clock", {})
	var phase_key := "%s:%s" % [date.get("day", 1), date.get("phase", "morning")]
	var fresh := false
	if state.has("seen") and int(snapshot.get("revision", 0)) >= int(state.get("revision", 0)):
		for id in incoming:
			if not state.seen.has(id): fresh = true
	var last_phase := String(state.get("shaken_phase", ""))
	if fresh and last_phase != phase_key:
		last_phase = phase_key
		pulse_phone()
	SimulationBridge.set_meta("hud_messages", {"seen": incoming, "shaken_phase": last_phase, "revision": snapshot.get("revision", 0)})


func pulse_phone() -> void:
	pulse_count += 1
	if _shake != null: _shake.kill()
	phone.rotation = 0
	_shake = create_tween()
	for angle in [-0.12, 0.12, -0.08, 0.08, 0.0]:
		_shake.tween_property(phone, "rotation", angle, 0.055)
