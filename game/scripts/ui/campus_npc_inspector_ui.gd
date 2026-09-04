extends CanvasLayer

const INTERACTION_DISTANCE := 82.0

const COLLEGE_NAMES := {
	"math_physics": "数理学院",
	"biochemistry": "生化学院",
	"earth_space": "天地学院",
	"artificial_intelligence": "AI 学院",
	"psychology": "心理学院",
	"humanities": "人文学院",
	"medicine": "医学院",
	"sports": "体育学院",
}

const ROLE_NAMES := {
	"student": "学生",
	"faculty": "教职工",
	"staff": "职工",
}

const OCCUPATION_NAMES := {
	"undergraduate": "本科生",
	"graduate_student": "研究生",
	"student_assistant": "学生助理",
	"academic_faculty": "教师",
	"administration_staff": "行政人员",
	"campus_security": "校园安保",
	"campus_service_staff": "校园服务人员",
	"librarian": "图书馆员",
	"maintenance_staff": "维修人员",
	"medical_staff": "医务人员",
	"psychology_counselor": "心理咨询师",
}

const ACTIVITY_NAMES := {
	"ORIENTATION_OR_CLASS": "报到或上课",
	"RESEARCH": "研究",
	"TEACH": "授课",
	"COURSEWORK": "完成课程任务",
	"CLUB_ACTIVITY": "参加社团活动",
	"CAMPUS_EXPLORATION": "熟悉校园",
	"READ_OR_SOCIALIZE": "阅读或社交",
	"PERSONAL_ACTIVITY": "处理个人事务",
	"WORK": "工作",
	"PATROL": "巡逻",
	"REST": "休息",
	"ADMINISTRATION_SHIFT": "处理行政事务",
	"ASSIST_RESEARCH_OR_TEACHING": "协助研究或教学",
	"ATTEND_CLASS": "上课",
	"CAMPUS_SERVICE_SHIFT": "校园服务值班",
	"CASE_NOTES": "整理咨询记录",
	"CLUB_OR_PERSONAL_ACTIVITY": "参加社团或个人活动",
	"CLUB_OR_SELF_STUDY": "参加社团或自习",
	"COUNSELING_SHIFT": "心理咨询值班",
	"LAB_OR_SEMINAR": "实验或研讨",
	"LIBRARY_SHIFT": "图书馆值班",
	"LITERATURE_REVIEW": "阅读文献",
	"MAINTENANCE_SHIFT": "校园维修值班",
	"MEDICAL_SHIFT": "医疗值班",
	"NIGHT_SECURITY_SHIFT": "夜间安保值班",
	"ON_CALL_MAINTENANCE": "维修待命",
	"ON_CALL_MEDICAL_SHIFT": "医疗待命",
	"ON_CALL_SUPPORT": "值班待命",
	"OPTIONAL_RESEARCH": "自主研究",
	"PREPARE_MATERIALS": "准备教学材料",
	"PREPARE_OR_REVIEW": "备课或复盘",
	"RESEARCH_OR_OFFICE_HOURS": "研究或答疑",
	"SECURITY_PATROL": "校园巡逻",
	"SELF_STUDY": "自习",
	"SOCIAL_OR_SELF_STUDY": "社交或自习",
	"TEACH_CLASS": "授课",
}

var _overlay: ColorRect
var _title: Label
var _details: RichTextLabel
var _nearby_hint: Label
var _tab_buttons: Dictionary = {}
var _load_more: Button
var _awaken_button: Button
var _awaken_feedback: Label
var _contact_button: Button
var _contact_feedback: Label
var _opened := false
var _selected_npc: Node
var _selected_profile: Dictionary = {}
var _active_tab := "overview"
var _chronicle_pages: Dictionary = {}
var _chronicle_loading := false


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("campus_npc_inspector_ui")
	_build_ui()
	SimulationBridge.campus_npc_chronicle_loaded.connect(_on_chronicle_loaded)
	SimulationBridge.campus_cognition_operation_completed.connect(_on_cognition_operation_completed)
	SimulationBridge.campus_phone_message_completed.connect(_on_contact_operation_completed)


func _process(_delta: float) -> void:
	if _opened:
		return
	if get_tree().paused or _another_modal_is_open():
		_nearby_hint.visible = false
		return
	var npc := _nearest_npc()
	_nearby_hint.visible = npc != null
	if npc != null:
		var profile: Dictionary = npc.call("get_campus_profile")
		_nearby_hint.text = "E  查看 %s" % _safe_text(profile.get("display_name"), "附近的人")


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("interact_npc"):
		if _opened:
			_set_open(false)
		elif not _another_modal_is_open():
			var npc := _nearest_npc()
			if npc != null:
				_show_npc(npc)
		get_viewport().set_input_as_handled()
	elif _opened and event.is_action_pressed("ui_cancel"):
		_set_open(false)
		get_viewport().set_input_as_handled()


func is_open() -> bool:
	return _opened


func inspect_npc(npc: Node) -> void:
	if npc != null and npc.has_method("get_campus_profile"):
		_show_npc(npc)


func _build_ui() -> void:
	_nearby_hint = Label.new()
	_nearby_hint.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	_nearby_hint.position = Vector2(-150, -92)
	_nearby_hint.size = Vector2(300, 38)
	_nearby_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_nearby_hint.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_nearby_hint.add_theme_font_size_override("font_size", 17)
	_nearby_hint.add_theme_color_override("font_shadow_color", Color.BLACK)
	_nearby_hint.add_theme_constant_override("shadow_offset_x", 2)
	_nearby_hint.add_theme_constant_override("shadow_offset_y", 2)
	_nearby_hint.visible = false
	add_child(_nearby_hint)

	_overlay = ColorRect.new()
	_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_overlay.color = Color(0.01, 0.018, 0.03, 0.72)
	_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	_overlay.visible = false
	add_child(_overlay)

	var panel := PanelContainer.new()
	panel.set_anchors_preset(Control.PRESET_CENTER)
	panel.position = Vector2(-340, -260)
	panel.size = Vector2(680, 520)
	_overlay.add_child(panel)
	var margin := MarginContainer.new()
	for side in ["left", "top", "right", "bottom"]:
		margin.add_theme_constant_override("margin_%s" % side, 22)
	panel.add_child(margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 12)
	margin.add_child(column)
	_title = Label.new()
	_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_title.add_theme_font_size_override("font_size", 27)
	column.add_child(_title)
	var tabs := HBoxContainer.new()
	tabs.alignment = BoxContainer.ALIGNMENT_CENTER
	tabs.add_theme_constant_override("separation", 8)
	column.add_child(tabs)
	for tab in [
		{"id": "overview", "label": "人物概况"},
		{"id": "recent", "label": "日程记录"},
		{"id": "important", "label": "重要经历"},
	]:
		var button := Button.new()
		button.text = tab["label"]
		button.toggle_mode = true
		button.custom_minimum_size = Vector2(150, 38)
		button.pressed.connect(_select_tab.bind(tab["id"]))
		tabs.add_child(button)
		_tab_buttons[tab["id"]] = button
	_details = RichTextLabel.new()
	_details.bbcode_enabled = true
	_details.fit_content = false
	_details.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_details.add_theme_font_size_override("normal_font_size", 17)
	column.add_child(_details)
	_load_more = Button.new()
	_load_more.text = "加载更早记录"
	_load_more.visible = false
	_load_more.pressed.connect(_load_more_chronicle)
	column.add_child(_load_more)
	_contact_button = Button.new()
	_contact_button.text = "交换联系方式（免费操作）"
	_contact_button.pressed.connect(_add_selected_contact)
	column.add_child(_contact_button)
	_contact_feedback = Label.new()
	_contact_feedback.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_contact_feedback.add_theme_color_override("font_color", Color("e0b86a"))
	column.add_child(_contact_feedback)
	_awaken_button = Button.new()
	_awaken_button.text = "记名觉醒（长期深度认知）"
	_awaken_button.pressed.connect(_awaken_selected_npc)
	column.add_child(_awaken_button)
	_awaken_feedback = Label.new()
	_awaken_feedback.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_awaken_feedback.add_theme_color_override("font_color", Color("e0b86a"))
	column.add_child(_awaken_feedback)
	var close := Button.new()
	close.text = "关闭（E / Esc）"
	close.pressed.connect(_set_open.bind(false))
	column.add_child(close)


func _show_npc(npc: Node) -> void:
	_selected_npc = npc
	_selected_profile = npc.call("get_campus_profile")
	_chronicle_pages.clear()
	_chronicle_loading = false
	_title.text = _safe_text(_selected_profile.get("display_name"), _safe_text(_selected_profile.get("npc_id"), "校园成员"))
	_awaken_feedback.text = ""
	_contact_feedback.text = ""
	_refresh_awaken_button()
	_refresh_contact_button()
	_select_tab("overview")
	_set_open(true)
	_request_chronicle("recent")


func _select_tab(tab_id: String) -> void:
	_active_tab = tab_id
	for id in _tab_buttons:
		(_tab_buttons[id] as Button).button_pressed = id == tab_id
	if tab_id == "overview":
		_details.text = _public_profile_text(_selected_profile)
		_load_more.visible = false
		return
	if not _chronicle_pages.has(tab_id):
		_details.text = "[color=#91a4bc]正在读取人物记录……[/color]"
		_load_more.visible = false
		_request_chronicle(tab_id)
		return
	_render_chronicle(tab_id)


func _request_chronicle(filter_name: String, cursor: String = "") -> void:
	if _chronicle_loading or _selected_profile.is_empty():
		return
	_chronicle_loading = true
	SimulationBridge.request_npc_chronicle(
		_safe_text(_selected_profile.get("npc_id")), filter_name, cursor, 20
	)


func _load_more_chronicle() -> void:
	var page: Dictionary = _chronicle_pages.get(_active_tab, {})
	var cursor := _safe_text(page.get("next_cursor"))
	if not cursor.is_empty():
		_request_chronicle(_active_tab, cursor)


func _on_chronicle_loaded(success: bool, result: Dictionary, npc_id: String, filter_name: String) -> void:
	_chronicle_loading = false
	if _selected_profile.is_empty() or npc_id != _safe_text(_selected_profile.get("npc_id")):
		return
	if not success:
		if _active_tab == filter_name:
			_details.text = "[color=#d98282]人物记录读取失败：%s[/color]" % _safe_text(result.get("error"), "未知错误")
			_load_more.visible = false
		return
	var existing: Dictionary = _chronicle_pages.get(filter_name, {})
	var combined: Array = existing.get("items", []).duplicate(true) if existing.get("items", []) is Array else []
	var incoming = result.get("items", [])
	if incoming is Array:
		combined.append_array(incoming)
	var page := result.duplicate(true)
	page["items"] = combined
	_chronicle_pages[filter_name] = page
	if _active_tab == filter_name:
		_render_chronicle(filter_name)


func _render_chronicle(filter_name: String) -> void:
	var page: Dictionary = _chronicle_pages.get(filter_name, {})
	var items = page.get("items", [])
	if not items is Array or items.is_empty():
		_details.text = "[b]%s[/b]\n\n目前没有玩家已知的记录。\n\n[color=#91a4bc]%s[/color]" % [
		"最近七日日程" if filter_name == "recent" else "重要经历",
		_safe_text(page.get("knowledge_note"), "未知行动不会显示。"),
		]
		_load_more.visible = false
		return
	var lines: Array[String] = [
		"[b]%s[/b]" % ("最近七日日程" if filter_name == "recent" else "重要经历"),
		"",
	]
	var last_day := -1
	for value in items:
		if not value is Dictionary:
			continue
		var entry: Dictionary = value
		var day := int(entry.get("day", 1))
		if day != last_day:
			if last_day >= 0:
				lines.append("")
			lines.append("[b]第 %d 天[/b]" % day)
			last_day = day
		var phase_name := SimulationBridge.phase_display_name(_safe_text(entry.get("phase")))
		var summary := _entry_summary(entry)
		var source := _source_name(_safe_text(entry.get("source")))
		lines.append("  [color=#8fb7d6]%s[/color]  %s  [color=#8491a3]· %s[/color]" % [phase_name, summary, source])
	lines.append("")
	lines.append("[color=#91a4bc]%s[/color]" % _safe_text(page.get("knowledge_note"), "未知行动不会显示。"))
	_details.text = "\n".join(lines)
	_load_more.visible = bool(page.get("has_more", false))


func _entry_summary(entry: Dictionary) -> String:
	var parameters: Dictionary = entry.get("parameters", {}) if entry.get("parameters") is Dictionary else {}
	if _safe_text(entry.get("summary_key")) == "activity_completed":
		var activity_id := _safe_text(parameters.get("activity_id"))
		return "在%s%s" % [
			_safe_text(entry.get("scene_name"), "未知地点"),
			ACTIVITY_NAMES.get(activity_id, "完成了%s" % (activity_id if not activity_id.is_empty() else "一项活动")),
		]
	return _safe_text(entry.get("display_summary"), "发生了一件事")


func _source_name(source: String) -> String:
	return {
		"self": "亲历",
		"participant": "亲历",
		"witnessed": "亲眼所见",
		"public": "公开消息",
		"campus_record": "校内记录",
		"told": "本人告知",
		"rumor": "听说",
		"evidence": "调查所得",
	}.get(source, "来源不明")


func _public_profile_text(profile: Dictionary) -> String:
	var college_id := _safe_text(profile.get("college_id"))
	var role_id := _safe_text(profile.get("role_kind"))
	var occupation := _safe_text(profile.get("occupation_id"))
	var location_id := _safe_text(profile.get("current_location_id"))
	var places: Dictionary = SimulationBridge.campus_snapshot.get("places", {})
	var place: Dictionary = places.get(location_id, {})
	var activity: Dictionary = profile.get("current_activity", {}) if profile.get("current_activity") is Dictionary else {}
	if activity.is_empty() and profile.get("current_plan") is Dictionary:
		activity = profile.get("current_plan", {})
	var activity_id := _safe_text(activity.get("activity_id"))
	var identity_line := "%s · %s" % [
		COLLEGE_NAMES.get(college_id, college_id if not college_id.is_empty() else "校内单位"),
		ROLE_NAMES.get(role_id, role_id if not role_id.is_empty() else "校园成员"),
	]
	if not occupation.is_empty():
		identity_line += "（%s）" % OCCUPATION_NAMES.get(occupation, occupation)
	return "[b]公开身份[/b]\n%s\n\n[b]当前位置[/b]\n%s\n\n[b]正在做的事[/b]\n%s\n\n[b]可观察状态[/b]\n%s\n\n[color=#91a4bc]内在需求、秘密动机与后续计划不会直接显示；需要通过交流、观察、关系或调查逐渐了解。[/color]" % [
		identity_line,
		String(place.get("name", location_id if not location_id.is_empty() else "未知")),
		ACTIVITY_NAMES.get(activity_id, activity_id if not activity_id.is_empty() else "暂时没有明显行动"),
		_visible_mood(profile.get("emotions", {})),
	]


func _refresh_awaken_button() -> void:
	if _selected_profile.is_empty():
		_awaken_button.visible = false
		return
	_awaken_button.visible = true
	var cognition: Dictionary = SimulationBridge.campus_snapshot.get("cognition", {})
	var awakened := bool(_selected_profile.get("awakened_by_player", false))
	_awaken_button.disabled = awakened or int(cognition.get("awakened_count", 0)) >= int(cognition.get("awakened_slot_limit", 6))
	_awaken_button.text = "已记名觉醒" if awakened else "记名觉醒（%d / %d）" % [
		int(cognition.get("awakened_count", 0)), int(cognition.get("awakened_slot_limit", 6)),
	]


func _refresh_contact_button() -> void:
	if _selected_profile.is_empty():
		_contact_button.visible = false
		return
	_contact_button.visible = true
	var is_contact := bool(_selected_profile.get("is_phone_contact", false))
	_contact_button.disabled = is_contact
	_contact_button.text = "已在手机联系人中" if is_contact else "交换联系方式（免费操作）"


func _add_selected_contact() -> void:
	var npc_id := _safe_text(_selected_profile.get("npc_id"))
	if npc_id.is_empty():
		return
	_contact_button.disabled = true
	_contact_feedback.text = "正在交换联系方式……"
	SimulationBridge.operate_campus_message("ADD_PHONE_CONTACT", npc_id)


func _on_contact_operation_completed(
	success: bool, result: Dictionary, action_id: String, target_id: String
) -> void:
	if action_id != "ADD_PHONE_CONTACT" or _selected_profile.is_empty() or target_id != _safe_text(_selected_profile.get("npc_id")):
		return
	var command_result: Dictionary = result.get("result", {})
	_contact_feedback.text = String(command_result.get("message", result.get("error", "添加联系人失败")))
	_contact_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	if success:
		_selected_profile = (SimulationBridge.campus_snapshot.get("population", {}) as Dictionary).get(target_id, _selected_profile)
	_refresh_contact_button()


func _awaken_selected_npc() -> void:
	var npc_id := _safe_text(_selected_profile.get("npc_id"))
	if npc_id.is_empty():
		return
	_awaken_button.disabled = true
	_awaken_feedback.text = "正在建立长期认知槽位……"
	SimulationBridge.operate_campus_cognition("AWAKEN_NPC", npc_id)


func _on_cognition_operation_completed(success: bool, result: Dictionary, _action_id: String, target_id: String) -> void:
	if _selected_profile.is_empty() or target_id != _safe_text(_selected_profile.get("npc_id")):
		return
	var command_result: Dictionary = result.get("result", {})
	_awaken_feedback.text = String(command_result.get("message", result.get("error", "觉醒操作失败")))
	if success:
		_selected_profile = (SimulationBridge.campus_snapshot.get("population", {}) as Dictionary).get(target_id, _selected_profile)
	_refresh_awaken_button()


func _visible_mood(value: Variant) -> String:
	if not value is Dictionary or value.is_empty():
		return "看不出明显情绪"
	var emotions: Dictionary = value
	var strongest := ""
	var strength := -1
	for key in emotions:
		var amount := int(emotions[key])
		if amount > strength:
			strongest = String(key)
			strength = amount
	if strength < 18:
		return "神情比较平静"
	return {
		"joy": "看起来心情不错",
		"fear": "神情有些紧张",
		"anger": "似乎有些恼火",
		"sadness": "看起来有些低落",
		"shame": "神情略显不自在",
	}.get(strongest, "情绪不太容易判断")


func _safe_text(value: Variant, fallback: String = "") -> String:
	if value == null:
		return fallback
	var text := str(value)
	return fallback if text.is_empty() else text


func _nearest_npc() -> Node:
	var player := get_tree().get_first_node_in_group("player") as Node2D
	var layer := get_tree().get_first_node_in_group("campus_npc_movement_layer")
	if player == null or layer == null:
		return null
	return layer.call("nearest_interactable_npc", player.global_position, INTERACTION_DISTANCE)


func _another_modal_is_open() -> bool:
	for group_name in ["campus_map_ui", "campus_phone_ui"]:
		var ui = get_tree().get_first_node_in_group(group_name)
		if ui != null and ui.is_open():
			return true
	return false


func _set_open(value: bool) -> void:
	if value and _another_modal_is_open():
		return
	_opened = value
	_overlay.visible = value
	_nearby_hint.visible = false if value else _nearby_hint.visible
	if not value:
		_selected_npc = null
		_selected_profile = {}
		_chronicle_pages.clear()
	get_tree().paused = value
