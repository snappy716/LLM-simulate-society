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
var _opened := false
var _selected_npc: Node


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("campus_npc_inspector_ui")
	_build_ui()


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
	panel.position = Vector2(-280, -210)
	panel.size = Vector2(560, 420)
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
	_details = RichTextLabel.new()
	_details.bbcode_enabled = true
	_details.fit_content = false
	_details.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_details.add_theme_font_size_override("normal_font_size", 17)
	column.add_child(_details)
	var close := Button.new()
	close.text = "关闭（E / Esc）"
	close.pressed.connect(_set_open.bind(false))
	column.add_child(close)


func _show_npc(npc: Node) -> void:
	_selected_npc = npc
	var profile: Dictionary = npc.call("get_campus_profile")
	_title.text = _safe_text(profile.get("display_name"), _safe_text(profile.get("npc_id"), "校园成员"))
	_details.text = _public_profile_text(profile)
	_set_open(true)


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
	get_tree().paused = value
