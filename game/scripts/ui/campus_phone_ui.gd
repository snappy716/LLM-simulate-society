extends CanvasLayer

const APPS := [
	{"id": "messages", "name": "校园通讯", "icon": "讯", "color": Color("35c96f")},
	{"id": "courses", "name": "课程平台", "icon": "课", "color": Color("3988e8")},
	{"id": "album", "name": "校园相册", "icon": "册", "color": Color("d65bd1")},
	{"id": "notes", "name": "备忘录", "icon": "记", "color": Color("edc84b")},
	{"id": "market", "name": "校园商城", "icon": "商", "color": Color("ed6540")},
	{"id": "wallet", "name": "电子钱包", "icon": "钱", "color": Color("4f73cd")},
	{"id": "health", "name": "健康档案", "icon": "健", "color": Color("e95d70")},
	{"id": "forums", "name": "双层论坛", "icon": "坛", "color": Color("785bc7")},
]

var _overlay: ColorRect
var _home: Control
var _app_page: VBoxContainer
var _app_title: Label
var _content: RichTextLabel
var _time_label: Label
var _opened := false


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("campus_phone_ui")
	_build_ui()


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("toggle_phone"):
		_set_open(not _opened)
		get_viewport().set_input_as_handled()
	elif _opened and event.is_action_pressed("ui_cancel"):
		if _app_page.visible:
			_show_home()
		else:
			_set_open(false)
		get_viewport().set_input_as_handled()


func is_open() -> bool:
	return _opened


func _build_ui() -> void:
	_overlay = ColorRect.new()
	_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_overlay.color = Color(0.01, 0.015, 0.025, 0.68)
	_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	_overlay.visible = false
	add_child(_overlay)
	var phone := PanelContainer.new()
	phone.set_anchors_preset(Control.PRESET_CENTER)
	phone.position = Vector2(-190, -258)
	phone.size = Vector2(380, 516)
	phone.add_theme_stylebox_override("panel", _panel_style(Color("101522"), 32, 3))
	_overlay.add_child(phone)
	var margin := MarginContainer.new()
	for side in ["left", "top", "right", "bottom"]:
		margin.add_theme_constant_override("margin_%s" % side, 14)
	phone.add_child(margin)
	var column := VBoxContainer.new()
	margin.add_child(column)
	var status_bar := HBoxContainer.new()
	_time_label = Label.new()
	status_bar.add_child(_time_label)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	status_bar.add_child(spacer)
	var status := Label.new()
	status.text = "校园网  86%"
	status_bar.add_child(status)
	column.add_child(status_bar)
	var pages := Control.new()
	pages.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_child(pages)
	_home = _build_home()
	_home.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	pages.add_child(_home)
	_app_page = _build_app_page()
	_app_page.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_app_page.visible = false
	pages.add_child(_app_page)
	var hint := Label.new()
	hint.text = "T 关闭手机"
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(hint)


func _build_home() -> Control:
	var grid := GridContainer.new()
	grid.columns = 4
	grid.add_theme_constant_override("h_separation", 8)
	grid.add_theme_constant_override("v_separation", 18)
	for app in APPS:
		var cell := VBoxContainer.new()
		cell.custom_minimum_size = Vector2(78, 104)
		var button := Button.new()
		button.text = String(app.icon)
		button.custom_minimum_size = Vector2(66, 66)
		button.add_theme_font_size_override("font_size", 28)
		button.add_theme_stylebox_override("normal", _icon_style(app.color))
		button.pressed.connect(_open_app.bind(String(app.id), String(app.name)))
		cell.add_child(button)
		var label := Label.new()
		label.text = String(app.name)
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		label.add_theme_font_size_override("font_size", 12)
		cell.add_child(label)
		grid.add_child(cell)
	return grid


func _build_app_page() -> VBoxContainer:
	var page := VBoxContainer.new()
	var nav := HBoxContainer.new()
	var back := Button.new()
	back.text = "‹ 返回"
	back.pressed.connect(_show_home)
	nav.add_child(back)
	_app_title = Label.new()
	_app_title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_app_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_app_title.add_theme_font_size_override("font_size", 22)
	nav.add_child(_app_title)
	page.add_child(nav)
	_content = RichTextLabel.new()
	_content.bbcode_enabled = true
	_content.fit_content = false
	_content.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_content.add_theme_font_size_override("normal_font_size", 15)
	page.add_child(_content)
	return page


func _open_app(app_id: String, app_name: String) -> void:
	_app_title.text = app_name
	_content.text = _app_text(app_id)
	_home.visible = false
	_app_page.visible = true


func _app_text(app_id: String) -> String:
	var campus: Dictionary = SimulationBridge.campus_snapshot
	var player: Dictionary = campus.get("player", {})
	var clock: Dictionary = campus.get("clock", {})
	var place_id := String(player.get("current_location_id", ""))
	var place: Dictionary = (campus.get("places", {}) as Dictionary).get(place_id, {})
	if app_id == "courses":
		var plan: Dictionary = player.get("current_plan", {})
		return "[b]第 %d 天 · %s[/b]\n\n当前计划：%s\n地点：%s\n主要行动剩余：%d" % [int(clock.get("day", 1)), SimulationBridge.phase_display_name(String(clock.get("phase", "morning"))), plan.get("activity_id", "自由安排"), plan.get("location_id", "未安排"), int((player.get("action_budget", {}) as Dictionary).get("major_remaining", 0))]
	if app_id == "album":
		var presentation := get_node("/root/CampusPresentation")
		var current_map: Dictionary = presentation.call("get_map")
		return "[b]当前场景[/b]\n%s\n\n已接入校园正式候选场景：%d 张。\n按 M 可查看和切换校园区域。" % [current_map.get("name", "未知"), (presentation.call("all_maps") as Array).size()]
	if app_id == "notes":
		var activity: Dictionary = player.get("current_activity", {})
		return "[b]当前位置[/b]\n%s\n\n[b]最近活动[/b]\n%s\n%s" % [place.get("name", place_id), activity.get("activity_id", "暂无"), activity.get("result", "")]
	if app_id == "wallet":
		return "[b]账户概览[/b]\n\n校园生活资金：%d\n\n交易仍使用现有物品与交易内核，后续把商城按钮直接接到商品目录。" % int(player.get("wealth", 0))
	if app_id == "health":
		return "[b]需求[/b]\n%s\n\n[b]情绪[/b]\n%s" % [_dictionary_lines(player.get("needs", {})), _dictionary_lines(player.get("emotions", {}))]
	if app_id == "market":
		return "[b]校园商城[/b]\n\n物品、商店库存、价格和原子结算已经存在。\n本页目前是手机入口，下一阶段把文字交易面板嵌入此处。"
	if app_id == "forums":
		return "[b]表世界论坛[/b]\n校园生活、求助与公开任务。\n\n[b]里世界论坛[/b]\n异常报告与夜间任务。\n\n任务竞争和锁定系统尚未进入当前程序阶段。"
	return "[b]校园通讯[/b]\n\n联系人、聊天和关系系统入口已经保留。\nNPC 对话与消息内容将在认知层接入后显示。"


func _dictionary_lines(value: Variant) -> String:
	if not value is Dictionary or value.is_empty():
		return "暂无数据"
	var keys: Array = value.keys()
	keys.sort()
	var lines: Array[String] = []
	for key in keys:
		lines.append("%s：%s" % [key, value[key]])
	return "\n".join(lines)


func _show_home() -> void:
	_home.visible = true
	_app_page.visible = false


func _set_open(value: bool) -> void:
	if value:
		for group_name in ["campus_map_ui", "campus_npc_inspector_ui"]:
			var other_ui = get_tree().get_first_node_in_group(group_name)
			if other_ui != null and other_ui.is_open():
				return
	_opened = value
	_overlay.visible = value
	if value:
		_show_home()
		var clock: Dictionary = SimulationBridge.campus_snapshot.get("clock", {})
		_time_label.text = "Day %d · %s" % [int(clock.get("day", 1)), SimulationBridge.phase_display_name(String(clock.get("phase", "morning")))]
	get_tree().paused = value


func _panel_style(color: Color, radius: int, border: int) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.border_color = Color("454d5e")
	style.set_border_width_all(border)
	style.set_corner_radius_all(radius)
	return style


func _icon_style(color: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.set_corner_radius_all(15)
	return style
