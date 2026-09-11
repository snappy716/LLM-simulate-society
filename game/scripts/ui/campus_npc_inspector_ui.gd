extends CanvasLayer

const INTERACTION_DISTANCE := 82.0
const UI_TEXT = preload("res://scripts/ui/campus_ui_text.gd")
var _dialogue_pending_target := ""
var _dialogue_sent_text := ""
var _plan_button: Button
var _plan_feedback: Label
var _plan_pending_target := ""
var _dispute_ask: Button
var _dispute_mediate: Button
var _dispute_other: Button
var _dispute_feedback: Label
var _dispute_case: Dictionary = {}
var _dispute_pending := ""
var _dispute_review: Button
var _welfare_button: Button
var _welfare_feedback: Label
var _welfare_pending := ""
var _anomaly_ask: Button
var _anomaly_support: Button
var _anchor_options: OptionButton
var _anchor_confirm: Button
var _anchor_use: Button
var _anchor_feedback: Label
var _anomaly_feedback: Label
var _anomaly_route_feedback: Label
var _anomaly_case: Dictionary = {}
var _anomaly_pending := ""
var _meeting_options: OptionButton
var _meeting_propose: Button
var _meeting_accept: Button
var _meeting_cancel: Button
var _meeting_status: Label
var _meeting: Dictionary = {}

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

const ACTIVITY_NAMES = preload("res://scripts/ui/campus_ui_text.gd").ACTIVITY_NAMES

const DIALOGUE_INTENTS := [
	{"id": "small_talk", "name": "随口交谈"},
	{"id": "exchange_ideas", "name": "交换想法"},
	{"id": "offer_support", "name": "主动关心"},
	{"id": "coordinate_club", "name": "商量社团"},
	{"id": "ask_task_help", "name": "请求协助"},
	{"id": "follow_up_promise", "name": "兑现约定"},
	{"id": "confront", "name": "当面质疑"},
]

const SOCIAL_PROPOSALS := [
	{"id": "party_invite", "name": "邀请加入行动小队"},
	{"id": "task_help", "name": "请求协助当前任务"},
	{"id": "meet_up", "name": "约定稍后见面"},
	{"id": "follow_up", "name": "兑现已有约定"},
]

var _overlay: ColorRect
var _panel: PanelContainer
var _body_scroll: ScrollContainer
var _close_button: Button
var _title: Label
var _details: RichTextLabel
var _nearby_hint: Label
var _tab_buttons: Dictionary = {}
var _load_more: Button
var _awaken_button: Button
var _awaken_feedback: Label
var _awaken_pending_target := ""
var _contact_button: Button
var _contact_feedback: Label
var _dialogue_intent: OptionButton
var _dialogue_input: LineEdit
var _dialogue_button: Button
var _dialogue_feedback: Label
var _proposal_picker: OptionButton
var _proposal_button: Button
var _proposal_feedback: Label
var _incoming_proposal_id := ""
var _incoming_proposal_label: Label
var _incoming_proposal_accept: Button
var _incoming_proposal_decline: Button
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
	SimulationBridge.campus_dialogue_completed.connect(_on_dialogue_completed)
	SimulationBridge.campus_goal_operation_completed.connect(_on_plan_completed)
	SimulationBridge.campus_investigation_operation_completed.connect(_on_dispute_completed)
	SimulationBridge.campus_investigation_operation_completed.connect(_on_welfare_completed)
	SimulationBridge.campus_investigation_operation_completed.connect(_on_anomaly_completed)
	SimulationBridge.campus_social_proposal_completed.connect(_on_social_proposal_completed)
	SimulationBridge.campus_social_proposal_response_completed.connect(_on_incoming_proposal_response_completed)


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
	if InterfaceSettings.is_open():
		return
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
	_panel = panel
	panel.set_anchors_preset(Control.PRESET_CENTER)
	_overlay.add_child(panel)
	_overlay.resized.connect(_fit_panel)
	var margin := MarginContainer.new()
	for side in ["left", "top", "right", "bottom"]:
		margin.add_theme_constant_override("margin_%s" % side, 22)
	panel.add_child(margin)
	var shell := VBoxContainer.new()
	shell.add_theme_constant_override("separation", 12)
	margin.add_child(shell)
	_title = Label.new()
	_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_title.add_theme_font_size_override("font_size", 27)
	_title.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	shell.add_child(_title)
	var shortcuts := HBoxContainer.new()
	shell.add_child(shortcuts)
	var kit = preload("res://scripts/ui/campus_ui_kit.gd")
	shortcuts.add_child(kit.button("人物与日志", func(): _body_scroll.scroll_vertical = 0))
	shortcuts.add_child(kit.button("当面交谈", func(): _dialogue_input.grab_focus()))
	shortcuts.add_child(kit.button("联系与深度交互", func(): _contact_button.grab_focus()))
	_body_scroll = ScrollContainer.new()
	_body_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_body_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_body_scroll.follow_focus = true
	shell.add_child(_body_scroll)
	var column := VBoxContainer.new()
	column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	column.add_theme_constant_override("separation", 12)
	_body_scroll.add_child(column)
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
	_details.custom_minimum_size.y = 200
	_details.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_details.add_theme_font_size_override("normal_font_size", 17)
	column.add_child(_details)
	_load_more = Button.new()
	_load_more.text = "加载更早记录"
	_load_more.visible = false
	_load_more.pressed.connect(_load_more_chronicle)
	column.add_child(_load_more)
	_plan_button = Button.new()
	_plan_button.text = "问问最近的打算（免费）"
	_plan_button.pressed.connect(_ask_plan)
	column.add_child(_plan_button)
	_plan_feedback = Label.new()
	_plan_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_plan_feedback)
	column.add_child(preload("res://scripts/ui/campus_ui_kit.gd").label("关心与调查 · 以下操作须由对方回应", 18))
	_dispute_ask = Button.new()
	_dispute_ask.text = "询问是否有未解的争执（免费）"
	_dispute_ask.pressed.connect(_ask_dispute)
	column.add_child(_dispute_ask)
	_dispute_other = Button.new()
	_dispute_other.text = "听取另一方意见（需当面或已有联系方式）"
	_dispute_other.pressed.connect(_ask_dispute_other)
	_dispute_other.visible = false
	column.add_child(_dispute_other)
	_dispute_review = Button.new()
	_dispute_review.text = "核对公开委托记录（免费）"
	_dispute_review.visible = false
	_dispute_review.pressed.connect(func(): _send_dispute("REVIEW_DISPUTE_RECORD", {"case_id": _dispute_case.case_id}))
	column.add_child(_dispute_review)
	_dispute_mediate = Button.new()
	_dispute_mediate.text = "尝试调解（双方可拒绝）"
	_dispute_mediate.pressed.connect(_mediate_dispute)
	_dispute_mediate.visible = false
	column.add_child(_dispute_mediate)
	_dispute_feedback = Label.new()
	_dispute_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_dispute_feedback)
	_welfare_button = Button.new()
	_welfare_button.text = "确认近况 / 报平安回访（免费）"
	_welfare_button.pressed.connect(_check_welfare)
	column.add_child(_welfare_button)
	_welfare_feedback = Label.new()
	_welfare_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_welfare_feedback)
	_anomaly_ask = Button.new()
	_anomaly_ask.text = "听取本人月相体验（免费，可拒绝）"
	_anomaly_ask.pressed.connect(func(): _send_anomaly(false))
	column.add_child(_anomaly_ask)
	_anomaly_support = Button.new()
	_anomaly_support.text = "共同做现实锚定（双方各一次主要行动）"
	_anomaly_support.pressed.connect(func(): _send_anomaly(true))
	_anomaly_support.visible = false
	column.add_child(_anomaly_support)
	_anomaly_feedback = Label.new()
	_anomaly_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_anomaly_feedback)
	_anomaly_route_feedback = Label.new()
	_anomaly_route_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_anomaly_route_feedback)
	_anchor_options = OptionButton.new()
	_anchor_options.clip_text = true
	column.add_child(_anchor_options)
	_anchor_confirm = Button.new()
	_anchor_confirm.text = "询问本人是否认可共同经历（免费，可拒绝）"
	_anchor_confirm.pressed.connect(func(): _send_anchor(false))
	column.add_child(_anchor_confirm)
	_anchor_use = Button.new()
	_anchor_use.text = "结合共同经历深入支持（双方各一次主要行动）"
	_anchor_use.pressed.connect(func(): _send_anchor(true))
	column.add_child(_anchor_use)
	_anchor_feedback = Label.new()
	_anchor_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_anchor_feedback)
	_meeting_status = Label.new()
	_meeting_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_meeting_status)
	_meeting_options = OptionButton.new()
	_meeting_options.clip_text = true
	column.add_child(_meeting_options)
	_meeting_propose = Button.new()
	_meeting_propose.text = "预约白天支持（手机留约，不立即消耗行动）"
	_meeting_propose.pressed.connect(func(): _send_meeting("PROPOSE_ANOMALY_MEETING"))
	column.add_child(_meeting_propose)
	_meeting_accept = Button.new()
	_meeting_accept.text = "同意预约（届时保留一次主要行动）"
	_meeting_accept.pressed.connect(func(): _send_meeting("ACCEPT_ANOMALY_MEETING"))
	column.add_child(_meeting_accept)
	_meeting_cancel = Button.new()
	_meeting_cancel.text = "婉拒 / 取消这次预约"
	_meeting_cancel.pressed.connect(func(): _send_meeting("CANCEL_ANOMALY_MEETING"))
	column.add_child(_meeting_cancel)
	var dialogue_label := Label.new()
	dialogue_label.text = "当面交谈（免费，可继续追问）"
	dialogue_label.add_theme_color_override("font_color", Color("8fb7d6"))
	column.add_child(dialogue_label)
	var dialogue_row := HBoxContainer.new()
	dialogue_row.add_theme_constant_override("separation", 8)
	column.add_child(dialogue_row)
	_dialogue_intent = OptionButton.new()
	_dialogue_intent.custom_minimum_size = Vector2(135, 38)
	for intent in DIALOGUE_INTENTS:
		_dialogue_intent.add_item(String(intent["name"]))
		_dialogue_intent.set_item_metadata(_dialogue_intent.item_count - 1, String(intent["id"]))
	dialogue_row.add_child(_dialogue_intent)
	_dialogue_input = LineEdit.new()
	_dialogue_input.placeholder_text = "输入想说的话（最多 240 字）"
	_dialogue_input.max_length = 240
	_dialogue_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_dialogue_input.text_submitted.connect(_submit_dialogue)
	_dialogue_input.text_changed.connect(_on_dialogue_text_changed)
	dialogue_row.add_child(_dialogue_input)
	_dialogue_button = Button.new()
	_dialogue_button.text = "交谈"
	_dialogue_button.custom_minimum_size = Vector2(82, 38)
	_dialogue_button.disabled = true
	_dialogue_button.pressed.connect(_submit_dialogue.bind(""))
	dialogue_row.add_child(_dialogue_button)
	_dialogue_feedback = Label.new()
	_dialogue_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_dialogue_feedback.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_dialogue_feedback.add_theme_color_override("font_color", Color("8cddff"))
	column.add_child(_dialogue_feedback)
	var proposal_row := HBoxContainer.new()
	proposal_row.add_theme_constant_override("separation", 8)
	column.add_child(proposal_row)
	_proposal_picker = OptionButton.new()
	_proposal_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for proposal in SOCIAL_PROPOSALS:
		_proposal_picker.add_item(String(proposal["name"]))
		_proposal_picker.set_item_metadata(_proposal_picker.item_count - 1, String(proposal["id"]))
	proposal_row.add_child(_proposal_picker)
	_proposal_button = Button.new()
	_proposal_button.text = "正式提出（免费）"
	_proposal_button.pressed.connect(_submit_social_proposal)
	proposal_row.add_child(_proposal_button)
	_proposal_feedback = Label.new()
	_proposal_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_proposal_feedback.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_proposal_feedback.add_theme_color_override("font_color", Color("8cddff"))
	column.add_child(_proposal_feedback)
	_incoming_proposal_label = Label.new()
	_incoming_proposal_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_incoming_proposal_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_incoming_proposal_label.add_theme_color_override("font_color", Color("8cddff"))
	column.add_child(_incoming_proposal_label)
	var incoming_actions := HBoxContainer.new()
	_incoming_proposal_accept = Button.new()
	_incoming_proposal_accept.text = "接受对方请求"
	_incoming_proposal_accept.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_incoming_proposal_accept.pressed.connect(_respond_incoming_proposal.bind(true))
	incoming_actions.add_child(_incoming_proposal_accept)
	_incoming_proposal_decline = Button.new()
	_incoming_proposal_decline.text = "拒绝对方请求"
	_incoming_proposal_decline.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_incoming_proposal_decline.pressed.connect(_respond_incoming_proposal.bind(false))
	incoming_actions.add_child(_incoming_proposal_decline)
	column.add_child(incoming_actions)
	_contact_button = Button.new()
	_contact_button.text = "交换联系方式（免费操作）"
	_contact_button.pressed.connect(_add_selected_contact)
	column.add_child(_contact_button)
	_contact_feedback = Label.new()
	_contact_feedback.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_contact_feedback.add_theme_color_override("font_color", Color("8cddff"))
	column.add_child(_contact_feedback)
	_awaken_button = Button.new()
	_awaken_button.text = "记名觉醒（长期深度认知）"
	_awaken_button.pressed.connect(_awaken_selected_npc)
	column.add_child(_awaken_button)
	_awaken_feedback = Label.new()
	_awaken_feedback.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_awaken_feedback.add_theme_color_override("font_color", Color("8cddff"))
	column.add_child(_awaken_feedback)
	var close := Button.new()
	_close_button = close
	close.text = "关闭（E / Esc）"
	close.pressed.connect(_set_open.bind(false))
	shell.add_child(close)
	_fit_panel()


func _fit_panel() -> void:
	if _panel == null:
		return
	var available := _overlay.size - Vector2(32, 32)
	var fitted := Vector2(minf(680, available.x), minf(700, available.y))
	_panel.offset_left = -fitted.x / 2
	_panel.offset_right = fitted.x / 2
	_panel.offset_top = -fitted.y / 2
	_panel.offset_bottom = fitted.y / 2


func _show_npc(npc: Node) -> void:
	_selected_npc = npc
	_body_scroll.scroll_vertical = 0
	_selected_profile = npc.call("get_campus_profile")
	_plan_feedback.text = ""
	_dispute_case = {}
	_dispute_feedback.text = ""
	_dispute_other.visible = false
	_dispute_mediate.visible = false
	_dispute_ask.disabled = not _dispute_pending.is_empty()
	_dispute_review.visible = false
	_welfare_button.disabled = not _welfare_pending.is_empty()
	_welfare_feedback.text = ""
	_refresh_anomaly()
	for report in SimulationBridge.campus_snapshot.get("social", {}).get("welfare", []):
		if report.get("npc_id", "") == _selected_profile.get("npc_id", ""):
			_welfare_feedback.text = "第 %d 天的近况：%s" % [int(report.day), report.summary]
	_plan_button.disabled = not _plan_pending_target.is_empty()
	_chronicle_pages.clear()
	_chronicle_loading = false
	_title.text = _safe_text(_selected_profile.get("display_name"), _safe_text(_selected_profile.get("npc_id"), "校园成员"))
	_awaken_feedback.text = ""
	_contact_feedback.text = ""
	_dialogue_feedback.text = ""
	_proposal_feedback.text = ""
	_refresh_incoming_proposal()
	_dialogue_input.text = ""
	_dialogue_button.disabled = true
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
		_details.text = "[color=#bdcedb]正在读取人物记录……[/color]"
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
		_details.text = "[b]%s[/b]\n\n目前没有玩家已知的记录。\n\n[color=#bdcedb]%s[/color]" % [
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
	lines.append("[color=#bdcedb]%s[/color]" % _safe_text(page.get("knowledge_note"), "未知行动不会显示。"))
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
	var report: Dictionary = profile.get("stated_plan", {})
	var statement := "尚未向对方询问。"
	if not report.is_empty():
		statement = "第 %s 天 · %s，本人告知：\n%s\n（当时的说法，后续可能改变。）" % [
			str(int(report.get("day", 0))), {"morning": "上午", "afternoon": "下午", "evening": "晚上", "late_night": "深夜"}.get(String(report.get("phase", "")), "当时"),
			String(report.get("summary", "")).replace("[", "[lb]")]
	return "[b]公开身份[/b]\n%s\n\n[b]当前位置[/b]\n%s\n\n[b]正在做的事[/b]\n%s\n\n[b]可观察状态[/b]\n%s\n\n[b]对方说过的打算[/b]\n%s\n\n[color=#bdcedb]内在需求、秘密动机与后续计划不会直接显示；需要通过交流、观察、关系或调查逐渐了解。[/color]" % [
		identity_line,
		String(place.get("name", location_id if not location_id.is_empty() else "未知")),
		ACTIVITY_NAMES.get(activity_id, activity_id if not activity_id.is_empty() else "暂时没有明显行动"),
		_visible_mood(profile.get("emotions", {})),
		statement,
	]


func _ask_plan() -> void:
	if not _plan_pending_target.is_empty() or _selected_profile.is_empty():
		return
	_plan_pending_target = _safe_text(_selected_profile.get("npc_id"))
	_plan_button.disabled = true
	_plan_feedback.text = "正在询问……"
	SimulationBridge.ask_campus_npc_plan(_plan_pending_target)


func _on_plan_completed(success: bool, result: Dictionary) -> void:
	var target := _plan_pending_target
	_plan_pending_target = ""
	_plan_button.disabled = false
	if target.is_empty() or target != _safe_text(_selected_profile.get("npc_id")):
		return
	var command_result: Dictionary = result.get("result", {})
	_plan_feedback.text = String(command_result.get("message", result.get("error", "询问结果尚未确认。")))
	if success:
		_selected_profile = (SimulationBridge.campus_snapshot.get("population", {}) as Dictionary).get(target, _selected_profile)
		if _active_tab == "overview":
			_details.text = _public_profile_text(_selected_profile)


func _refresh_anomaly() -> void:
	_anomaly_case = {}
	_anomaly_feedback.text = ""
	_anomaly_route_feedback.text = ""
	for row in SimulationBridge.campus_snapshot.get("social", {}).get("anomalies", []):
		if row.get("npc_id", "") == _selected_profile.get("npc_id", ""):
			_anomaly_case = row
			_anomaly_feedback.text = "本人第 %d 天的陈述：%s\n%s" % [int(row.report.day), row.report.summary, row.support_hint]
			var feedback: Dictionary = row.get("route_feedback", {})
			if not feedback.is_empty():
				var lines: PackedStringArray = ["经历与处理记录", feedback.statement, "你的参与：" + String(feedback.own_path), feedback.scope_note]
				for record in feedback.get("own_records", []):
					lines.append(String(record.text))
				for guide in feedback.get("route_guide", []):
					lines.append(String(guide.label) + "：" + String(guide.note))
				_anomaly_route_feedback.text = "\n".join(lines)
	_anomaly_ask.disabled = not _anomaly_pending.is_empty()
	_anomaly_support.visible = not _anomaly_case.is_empty()
	_anomaly_support.disabled = not _anomaly_pending.is_empty() or not bool(_anomaly_case.get("can_support", false))
	_anchor_options.clear()
	for choice in _anomaly_case.get("anchor_options", []):
		_anchor_options.add_item(String(choice.label))
		_anchor_options.set_item_metadata(_anchor_options.item_count - 1, choice.source_id)
	var has_case := not _anomaly_case.is_empty()
	_anchor_options.visible = has_case and _anchor_options.item_count > 0
	_anchor_confirm.visible = _anchor_options.visible
	_anchor_confirm.disabled = not _anomaly_pending.is_empty()
	_anchor_use.visible = has_case and not _anomaly_case.get("confirmed_anchor", {}).is_empty()
	_anchor_use.disabled = _anomaly_support.disabled or not bool(_anomaly_case.get("can_use_anchor", false))
	_anchor_feedback.visible = has_case
	_anchor_feedback.text = String(_anomaly_case.get("confirmed_anchor", {}).get("summary", "")) + "\n" + String(_anomaly_case.get("anchor_hint", ""))
	_refresh_meeting()


func _refresh_meeting() -> void:
	_meeting = {}
	_meeting_options.clear()
	for choice in _anomaly_case.get("meeting_options", []):
		_meeting_options.add_item(String(choice.label))
		_meeting_options.set_item_metadata(_meeting_options.item_count - 1, choice)
	for row in SimulationBridge.campus_snapshot.get("social", {}).get("anomaly_meetings", []):
		if row.subject_id == _selected_profile.get("npc_id", ""):
			_meeting = row
	var active: bool = _meeting.get("status", "") in ["pending", "confirmed"]
	var busy := not _anomaly_pending.is_empty()
	_meeting_options.visible = not active and _meeting_options.item_count > 0
	_meeting_propose.visible = _meeting_options.visible
	_meeting_propose.disabled = busy
	_meeting_accept.visible = _meeting.get("status", "") == "pending" and _meeting.get("proposer_id", "") != "player"
	_meeting_cancel.visible = active
	_meeting_accept.disabled = busy
	_meeting_cancel.disabled = busy
	_meeting_status.text = ""
	if not _meeting.is_empty():
		var labels := {"pending": "等待回复", "confirmed": "双方已确认", "completed": "实际支持已完成", "missed": "未完成赴约", "declined": "已婉拒", "cancelled": "已取消"}
		var place: Dictionary = SimulationBridge.campus_snapshot.get("places", {}).get(_meeting.location_id, {})
		_meeting_status.text = "支持预约 · %s\n第 %d 天%s · %s\n%s\n需实际到场，并重新听取本人体验；预约不等于已完成支持。" % [labels.get(_meeting.status, ""), int(_meeting.day), "上午" if _meeting.phase == "morning" else "下午", place.get("name", _meeting.location_id), _meeting.reason]


func _send_meeting(action: String) -> void:
	if not _anomaly_pending.is_empty() or not _welfare_pending.is_empty() or not _dispute_pending.is_empty(): return
	var parameters: Dictionary
	if action == "PROPOSE_ANOMALY_MEETING":
		if _anomaly_case.is_empty() or _meeting_options.selected < 0: return
		parameters = (_meeting_options.get_item_metadata(_meeting_options.selected) as Dictionary).duplicate()
		parameters.erase("label")
		parameters["case_id"] = _anomaly_case.case_id
	else:
		if _meeting.is_empty(): return
		parameters = {"meeting_id": _meeting.meeting_id, "expected_revision": _meeting.revision}
	_anomaly_pending = String(_selected_profile.get("npc_id", ""))
	_refresh_meeting()
	SimulationBridge.operate_campus_investigation(action, parameters)


func _send_anomaly(support: bool) -> void:
	if not _anomaly_pending.is_empty() or not _welfare_pending.is_empty() or not _dispute_pending.is_empty() or _selected_profile.is_empty(): return
	if support and (_anomaly_case.is_empty() or not bool(_anomaly_case.get("can_support", false))): return
	_anomaly_pending = String(_selected_profile.npc_id)
	var parameters := {"npc_id": _anomaly_pending}
	if support:
		parameters["case_id"] = _anomaly_case.case_id
		parameters["expected_case_revision"] = _anomaly_case.report.revision
	_anomaly_ask.disabled = true
	_anomaly_support.disabled = true
	SimulationBridge.operate_campus_investigation("SUPPORT_ANOMALY" if support else "ASK_ANOMALY_EXPERIENCE", parameters)


func _send_anchor(use: bool) -> void:
	if not _anomaly_pending.is_empty() or not _welfare_pending.is_empty() or not _dispute_pending.is_empty() or _anomaly_case.is_empty(): return
	if use and _anchor_use.disabled: return
	if not use and _anchor_options.selected < 0: return
	_anomaly_pending = String(_selected_profile.npc_id)
	var parameters := {"npc_id": _anomaly_pending, "case_id": _anomaly_case.case_id, "expected_case_revision": _anomaly_case.report.revision}
	if use:
		parameters["anchor_id"] = _anomaly_case.confirmed_anchor.anchor_id
	else:
		parameters["source_id"] = _anchor_options.get_item_metadata(_anchor_options.selected)
	_refresh_anomaly()
	SimulationBridge.operate_campus_investigation("SUPPORT_ANOMALY" if use else "CONFIRM_RELATIONSHIP_ANCHOR", parameters)


func _on_anomaly_completed(_success: bool, result: Dictionary) -> void:
	if _anomaly_pending.is_empty(): return
	var target := _anomaly_pending
	_anomaly_pending = ""
	_refresh_anomaly()
	if target != String(_selected_profile.get("npc_id", "")): return
	_anomaly_feedback.text = String(result.get("result", {}).get("message", result.get("error", "尚未确认本人体验。"))) + "\n" + _anomaly_feedback.text


func _check_welfare() -> void:
	if not _anomaly_pending.is_empty(): return
	if not _welfare_pending.is_empty() or not _dispute_pending.is_empty() or _selected_profile.is_empty(): return
	_welfare_pending = String(_selected_profile.npc_id)
	_welfare_button.disabled = true
	_welfare_feedback.text = "正在联系；未回应不等于失踪……"
	SimulationBridge.operate_campus_investigation("CHECK_NPC_WELFARE", {"npc_id": _welfare_pending})


func _on_welfare_completed(success: bool, result: Dictionary) -> void:
	if _welfare_pending.is_empty(): return
	var target := _welfare_pending
	_welfare_pending = ""
	_welfare_button.disabled = false
	if target != String(_selected_profile.get("npc_id", "")): return
	_welfare_feedback.text = String(result.get("result", {}).get("message", result.get("error", "近况尚未确认。")))


func _ask_dispute() -> void:
	if not _dispute_pending.is_empty() or _selected_profile.is_empty(): return
	_send_dispute("ASK_NPC_DISPUTE", {"npc_id": _selected_profile.npc_id})


func _ask_dispute_other() -> void:
	for party in _dispute_case.get("parties", []):
		if not bool(party.get("heard", false)):
			_send_dispute("ASK_NPC_DISPUTE", {"npc_id": party.npc_id, "case_id": _dispute_case.case_id})
			return


func _mediate_dispute() -> void:
	if not _dispute_case.is_empty():
		_send_dispute("MEDIATE_DISPUTE", {"case_id": _dispute_case.case_id, "expected_case_revision": _dispute_case.revision})


func _send_dispute(action: String, parameters: Dictionary) -> void:
	if not _anomaly_pending.is_empty(): return
	if not _dispute_pending.is_empty() or not _welfare_pending.is_empty(): return
	_dispute_pending = String(_selected_profile.get("npc_id", ""))
	_dispute_ask.disabled = true
	_dispute_other.disabled = true
	_dispute_review.disabled = true
	_dispute_mediate.disabled = true
	_dispute_feedback.text = "正在确认对方的意见……"
	SimulationBridge.operate_campus_investigation(action, parameters)


func _on_dispute_completed(success: bool, result: Dictionary) -> void:
	if _dispute_pending.is_empty(): return
	var target := _dispute_pending
	_dispute_pending = ""
	_dispute_ask.disabled = false
	_dispute_other.disabled = false
	_dispute_review.disabled = false
	_dispute_mediate.disabled = false
	if target != String(_selected_profile.get("npc_id", "")): return
	var outcome: Dictionary = result.get("result", {})
	_dispute_feedback.text = String(outcome.get("message", result.get("error", "交谈未完成。")))
	if success:
		_dispute_case = outcome.get("payload", {}).get("case", {})
	var parties: Array = _dispute_case.get("parties", [])
	var missing: Array = parties.filter(func(p): return not bool(p.get("heard", false)))
	_dispute_other.visible = not missing.is_empty()
	if not missing.is_empty():
		_dispute_other.text = "听取 %s 的意见（需当面或已有联系方式）" % missing[0].get("name", "另一方")
	_dispute_mediate.visible = not _dispute_case.is_empty()
	var needs_record := bool(_dispute_case.get("record_required", false)) and not bool(_dispute_case.get("record_reviewed", false))
	_dispute_review.visible = needs_record
	_dispute_mediate.disabled = not missing.is_empty() or needs_record or not bool(_dispute_case.get("can_attempt", false))


func _refresh_awaken_button() -> void:
	if _selected_profile.is_empty():
		_awaken_button.visible = false
		return
	_awaken_button.visible = true
	var cognition: Dictionary = SimulationBridge.campus_snapshot.get("cognition", {})
	var awakened := bool(_selected_profile.get("awakened_by_player", false))
	var eligibility: Dictionary = _selected_profile.get("friend_focus", {})
	var base := bool(_selected_profile.get("base_deep_npc", false))
	_awaken_button.disabled = awakened or base or not bool(eligibility.get("eligible", false)) or not _awaken_pending_target.is_empty()
	_awaken_button.tooltip_text = String(eligibility.get("reason", "请刷新人物关系后再试。")) + "\n接口不可用时按规则运行，不影响游戏继续。"
	_awaken_button.text = "已建立长期认知联系" if awakened else ("基础深度 NPC（长期认知）" if base else "好友觉醒 · 额外接入 LLM")
	if not awakened and not base:
		_awaken_button.tooltip_text += "\n基础 %d 人 + 好友 %d 人；好友不占基础名额。" % [int(cognition.get("base_focused_count", 20)), int(cognition.get("awakened_count", 0))]


func _refresh_contact_button() -> void:
	if _selected_profile.is_empty():
		_contact_button.visible = false
		return
	_contact_button.visible = true
	var is_contact := bool(_selected_profile.get("is_phone_contact", false))
	_contact_button.disabled = is_contact
	_contact_button.tooltip_text = "已经可以通过手机联系。" if is_contact else "与面前的人交换联系方式，不会自动拥有全校联系人。"
	_contact_button.text = "已在手机联系人中" if is_contact else "交换联系方式（免费操作）"


func _add_selected_contact() -> void:
	var npc_id := _safe_text(_selected_profile.get("npc_id"))
	if npc_id.is_empty():
		return
	_contact_button.disabled = true
	_contact_feedback.text = "正在交换联系方式……"
	SimulationBridge.operate_campus_message("ADD_PHONE_CONTACT", npc_id)


func _on_dialogue_text_changed(text: String) -> void:
	_dialogue_button.disabled = not _dialogue_pending_target.is_empty() or text.strip_edges().is_empty()
	_dialogue_button.tooltip_text = UI_TEXT.PENDING_MESSAGE if not _dialogue_pending_target.is_empty() else ("请输入交谈内容。" if text.strip_edges().is_empty() else "不消耗主要行动，不设每日交谈次数上限。")


func _submit_dialogue(_submitted_text: String = "") -> void:
	if not _dialogue_pending_target.is_empty():
		return
	var npc_id := _safe_text(_selected_profile.get("npc_id"))
	var text := _dialogue_input.text.strip_edges()
	if npc_id.is_empty() or text.is_empty():
		return
	_dialogue_pending_target = npc_id
	_dialogue_sent_text = text
	_on_dialogue_text_changed(text)
	var intent_id := "small_talk"
	if _dialogue_intent.selected >= 0:
		intent_id = String(_dialogue_intent.get_item_metadata(_dialogue_intent.selected))
	_dialogue_button.disabled = true
	_dialogue_feedback.text = "对方正在回应……"
	SimulationBridge.operate_campus_dialogue(npc_id, intent_id, text)


func _on_dialogue_completed(success: bool, result: Dictionary, target_id: String) -> void:
	var own_dialogue := _dialogue_pending_target == target_id
	if own_dialogue:
		_dialogue_pending_target = ""
	if _selected_profile.is_empty() or target_id != _safe_text(_selected_profile.get("npc_id")):
		_on_dialogue_text_changed(_dialogue_input.text)
		return
	var command_result: Dictionary = result.get("result", {})
	if success:
		var payload: Dictionary = command_result.get("payload", {})
		_dialogue_feedback.text = "%s：%s" % [
			_safe_text(_selected_profile.get("display_name"), target_id),
			_safe_text(payload.get("reply_text"), "对方没有继续回答。"),
		]
		_dialogue_feedback.add_theme_color_override("font_color", Color("9bcf9b"))
		if own_dialogue and _dialogue_input.text.strip_edges() == _dialogue_sent_text:
			_dialogue_input.text = ""
		_selected_profile = (SimulationBridge.campus_snapshot.get("population", {}) as Dictionary).get(target_id, _selected_profile)
	else:
		_dialogue_feedback.text = UI_TEXT.operation_feedback(success, result)
		_dialogue_feedback.add_theme_color_override("font_color", Color("ee8174"))
	_on_dialogue_text_changed(_dialogue_input.text)
	_refresh_awaken_button()


func _submit_social_proposal() -> void:
	var npc_id := _safe_text(_selected_profile.get("npc_id"))
	if npc_id.is_empty() or _proposal_picker.selected < 0:
		return
	var proposal_type := String(_proposal_picker.get_item_metadata(_proposal_picker.selected))
	_proposal_button.disabled = true
	_proposal_feedback.text = "正在等待对方明确决定……"
	SimulationBridge.operate_campus_social_proposal(npc_id, proposal_type, "in_person")


func _on_social_proposal_completed(
	success: bool, result: Dictionary, target_id: String, _proposal_type: String
) -> void:
	if _selected_profile.is_empty() or target_id != _safe_text(_selected_profile.get("npc_id")):
		return
	var command_result: Dictionary = result.get("result", {})
	var payload: Dictionary = command_result.get("payload", {})
	if payload.has("reply_text"):
		_proposal_feedback.text = "%s：%s" % [
			_safe_text(_selected_profile.get("display_name"), target_id),
			_safe_text(payload.get("reply_text"), command_result.get("message", "对方已经作出决定。")),
		]
	else:
		_proposal_feedback.text = String(command_result.get("message", result.get("error", "提议未能送达")))
	_proposal_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	_proposal_button.disabled = false


func _refresh_incoming_proposal() -> void:
	_incoming_proposal_id = ""
	var npc_id := _safe_text(_selected_profile.get("npc_id"))
	var incoming: Array = (SimulationBridge.campus_snapshot.get("social", {}) as Dictionary).get("incoming_proposals", [])
	for proposal in incoming:
		if (
			proposal is Dictionary
			and String(proposal.get("initiator_id", "")) == npc_id
			and String(proposal.get("status", "")) == "pending"
		):
			_incoming_proposal_id = String(proposal.get("proposal_id", ""))
			_incoming_proposal_label.text = "%s向你提出请求：%s" % [
				_safe_text(_selected_profile.get("display_name"), npc_id),
				_safe_text(proposal.get("request_text"), "希望得到你的明确答复。"),
			]
			break
	var has_pending := not _incoming_proposal_id.is_empty()
	if not has_pending:
		_incoming_proposal_label.text = ""
	_incoming_proposal_accept.visible = has_pending
	_incoming_proposal_decline.visible = has_pending


func _respond_incoming_proposal(accepted: bool) -> void:
	if _incoming_proposal_id.is_empty():
		return
	_incoming_proposal_accept.disabled = true
	_incoming_proposal_decline.disabled = true
	SimulationBridge.respond_campus_social_proposal(_incoming_proposal_id, accepted)


func _on_incoming_proposal_response_completed(
	success: bool, result: Dictionary, proposal_id: String
) -> void:
	if proposal_id != _incoming_proposal_id:
		return
	var command_result: Dictionary = result.get("result", {})
	_proposal_feedback.text = String(command_result.get("message", result.get("error", "请求处理失败")))
	_proposal_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	_incoming_proposal_accept.disabled = false
	_incoming_proposal_decline.disabled = false
	_refresh_incoming_proposal()


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
	if npc_id.is_empty() or not _awaken_pending_target.is_empty():
		return
	_awaken_pending_target = npc_id
	_awaken_button.disabled = true
	_awaken_feedback.text = "正在建立长期认知联系……"
	SimulationBridge.operate_campus_cognition("AWAKEN_NPC", npc_id)


func _on_cognition_operation_completed(success: bool, result: Dictionary, _action_id: String, target_id: String) -> void:
	if _action_id != "AWAKEN_NPC":
		return
	if target_id == _awaken_pending_target:
		_awaken_pending_target = ""
	_refresh_awaken_button()
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
