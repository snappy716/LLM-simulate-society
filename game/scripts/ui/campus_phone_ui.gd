extends CanvasLayer

const APPS := [
	{"id": "messages", "name": "校园通讯", "icon": "讯", "color": Color("35c96f")},
	{"id": "courses", "name": "课程平台", "icon": "课", "color": Color("3988e8")},
	{"id": "album", "name": "校园相册", "icon": "册", "color": Color("d65bd1")},
	{"id": "notes", "name": "备忘录", "icon": "记", "color": Color("edc84b")},
	{"id": "market", "name": "校园商城", "icon": "商", "color": Color("ed6540")},
	{"id": "wallet", "name": "电子钱包", "icon": "钱", "color": Color("4f73cd")},
	{"id": "health", "name": "健康档案", "icon": "健", "color": Color("e95d70")},
	{"id": "clubs", "name": "社团中心", "icon": "社", "color": Color("c47a46")},
	{"id": "party", "name": "行动小队", "icon": "队", "color": Color("477f8f")},
	{"id": "forums", "name": "双层论坛", "icon": "坛", "color": Color("785bc7")},
]

var _overlay: ColorRect
var _home: Control
var _app_page: VBoxContainer
var _app_title: Label
var _content: RichTextLabel
var _time_label: Label
var _opened := false
var _forum_root: VBoxContainer
var _forum_list_view: VBoxContainer
var _forum_cards: VBoxContainer
var _forum_detail_view: VBoxContainer
var _forum_detail: RichTextLabel
var _forum_primary_action: Button
var _forum_abandon_action: Button
var _forum_feedback: Label
var _forum_filter := "available"
var _selected_task_id := ""
var _club_root: VBoxContainer
var _club_picker: OptionButton
var _club_detail: RichTextLabel
var _club_membership_action: Button
var _club_activity_action: Button
var _club_feedback: Label
var _selected_club_id := ""
var _party_root: VBoxContainer
var _party_detail: RichTextLabel
var _party_candidate_picker: OptionButton
var _party_invite_action: Button
var _party_member_picker: OptionButton
var _party_dismiss_action: Button
var _party_feedback: Label
var _selected_party_candidate_id := ""
var _selected_party_member_id := ""
var _message_root: VBoxContainer
var _message_contact_picker: OptionButton
var _message_log: RichTextLabel
var _message_input: LineEdit
var _message_send_action: Button
var _message_feedback: Label
var _selected_message_contact_id := ""


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("campus_phone_ui")
	_build_ui()
	SimulationBridge.campus_snapshot_updated.connect(_on_campus_snapshot_updated)
	SimulationBridge.campus_task_operation_completed.connect(_on_task_operation_completed)
	SimulationBridge.campus_club_operation_completed.connect(_on_club_operation_completed)
	SimulationBridge.campus_party_operation_completed.connect(_on_party_operation_completed)
	SimulationBridge.campus_phone_message_completed.connect(_on_phone_message_completed)


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
	phone.offset_left = -195
	phone.offset_top = -250
	phone.offset_right = 195
	phone.offset_bottom = 250
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
	_forum_root = _build_forum_page()
	_forum_root.visible = false
	_forum_root.size_flags_vertical = Control.SIZE_EXPAND_FILL
	page.add_child(_forum_root)
	_club_root = _build_club_page()
	_club_root.visible = false
	_club_root.size_flags_vertical = Control.SIZE_EXPAND_FILL
	page.add_child(_club_root)
	_party_root = _build_party_page()
	_party_root.visible = false
	_party_root.size_flags_vertical = Control.SIZE_EXPAND_FILL
	page.add_child(_party_root)
	_message_root = _build_message_page()
	_message_root.visible = false
	_message_root.size_flags_vertical = Control.SIZE_EXPAND_FILL
	page.add_child(_message_root)
	return page


func _build_message_page() -> VBoxContainer:
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 7)
	_message_contact_picker = OptionButton.new()
	_message_contact_picker.item_selected.connect(_select_message_contact)
	root.add_child(_message_contact_picker)
	_message_log = RichTextLabel.new()
	_message_log.bbcode_enabled = true
	_message_log.fit_content = false
	_message_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_message_log.add_theme_font_size_override("normal_font_size", 14)
	root.add_child(_message_log)
	_message_feedback = Label.new()
	_message_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_message_feedback.add_theme_color_override("font_color", Color("e0b86a"))
	root.add_child(_message_feedback)
	var composer := HBoxContainer.new()
	_message_input = LineEdit.new()
	_message_input.placeholder_text = "输入消息（不消耗主要行动）"
	_message_input.max_length = 240
	_message_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_message_input.text_submitted.connect(_send_phone_message_from_input)
	composer.add_child(_message_input)
	_message_send_action = Button.new()
	_message_send_action.text = "发送"
	_message_send_action.pressed.connect(_send_phone_message)
	composer.add_child(_message_send_action)
	root.add_child(composer)
	return root


func _build_club_page() -> VBoxContainer:
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 8)
	_club_picker = OptionButton.new()
	_club_picker.item_selected.connect(_select_club)
	root.add_child(_club_picker)
	_club_detail = RichTextLabel.new()
	_club_detail.bbcode_enabled = true
	_club_detail.fit_content = false
	_club_detail.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_club_detail.add_theme_font_size_override("normal_font_size", 14)
	root.add_child(_club_detail)
	_club_feedback = Label.new()
	_club_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_club_feedback.add_theme_color_override("font_color", Color("e0b86a"))
	root.add_child(_club_feedback)
	var actions := HBoxContainer.new()
	_club_membership_action = Button.new()
	_club_membership_action.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_club_membership_action.pressed.connect(_perform_club_membership_action)
	actions.add_child(_club_membership_action)
	_club_activity_action = Button.new()
	_club_activity_action.text = "参加本时段活动"
	_club_activity_action.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_club_activity_action.pressed.connect(_perform_club_activity)
	actions.add_child(_club_activity_action)
	root.add_child(actions)
	return root


func _build_party_page() -> VBoxContainer:
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 7)
	_party_detail = RichTextLabel.new()
	_party_detail.bbcode_enabled = true
	_party_detail.fit_content = false
	_party_detail.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_party_detail.add_theme_font_size_override("normal_font_size", 14)
	root.add_child(_party_detail)
	var invite_label := Label.new()
	invite_label.text = "邀请同行者"
	root.add_child(invite_label)
	var invite_row := HBoxContainer.new()
	_party_candidate_picker = OptionButton.new()
	_party_candidate_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_party_candidate_picker.item_selected.connect(_select_party_candidate)
	invite_row.add_child(_party_candidate_picker)
	_party_invite_action = Button.new()
	_party_invite_action.text = "发出邀请"
	_party_invite_action.pressed.connect(_invite_party_candidate)
	invite_row.add_child(_party_invite_action)
	root.add_child(invite_row)
	var dismiss_row := HBoxContainer.new()
	_party_member_picker = OptionButton.new()
	_party_member_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_party_member_picker.item_selected.connect(_select_party_member)
	dismiss_row.add_child(_party_member_picker)
	_party_dismiss_action = Button.new()
	_party_dismiss_action.text = "解除承诺"
	_party_dismiss_action.pressed.connect(_dismiss_party_member)
	dismiss_row.add_child(_party_dismiss_action)
	root.add_child(dismiss_row)
	_party_feedback = Label.new()
	_party_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_party_feedback.add_theme_color_override("font_color", Color("e0b86a"))
	root.add_child(_party_feedback)
	return root


func _build_forum_page() -> VBoxContainer:
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 8)
	var channel_bar := HBoxContainer.new()
	var surface := Button.new()
	surface.text = "校园广场"
	surface.disabled = true
	surface.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	channel_bar.add_child(surface)
	var night := Button.new()
	night.text = "夜间 · 未解锁"
	night.disabled = true
	night.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	channel_bar.add_child(night)
	root.add_child(channel_bar)

	_forum_list_view = VBoxContainer.new()
	_forum_list_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var filters := HBoxContainer.new()
	for entry in [
		{"id": "available", "name": "可接"},
		{"id": "mine", "name": "我的"},
		{"id": "ended", "name": "已结束"},
	]:
		var button := Button.new()
		button.text = String(entry.name)
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		button.pressed.connect(_set_forum_filter.bind(String(entry.id)))
		filters.add_child(button)
	_forum_list_view.add_child(filters)
	var summary := Label.new()
	summary.name = "TaskSummary"
	summary.add_theme_color_override("font_color", Color("aeb8ca"))
	_forum_list_view.add_child(summary)
	var scroll := ScrollContainer.new()
	scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_forum_cards = VBoxContainer.new()
	_forum_cards.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_forum_cards.add_theme_constant_override("separation", 7)
	scroll.add_child(_forum_cards)
	# A plain Control isolates the scroll content's large minimum height from the
	# phone container, so the handset stays centered on smaller Windows screens.
	var scroll_frame := Control.new()
	scroll_frame.custom_minimum_size = Vector2(0, 160)
	scroll_frame.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll_frame.clip_contents = true
	scroll_frame.add_child(scroll)
	_forum_list_view.add_child(scroll_frame)
	root.add_child(_forum_list_view)

	_forum_detail_view = VBoxContainer.new()
	_forum_detail_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_forum_detail_view.visible = false
	var detail_back := Button.new()
	detail_back.text = "‹ 返回任务列表"
	detail_back.pressed.connect(_show_forum_list)
	_forum_detail_view.add_child(detail_back)
	_forum_detail = RichTextLabel.new()
	_forum_detail.bbcode_enabled = true
	_forum_detail.fit_content = false
	_forum_detail.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_forum_detail.add_theme_font_size_override("normal_font_size", 15)
	_forum_detail_view.add_child(_forum_detail)
	_forum_feedback = Label.new()
	_forum_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_forum_feedback.add_theme_color_override("font_color", Color("e0b86a"))
	_forum_detail_view.add_child(_forum_feedback)
	_forum_primary_action = Button.new()
	_forum_primary_action.pressed.connect(_perform_primary_task_action)
	_forum_detail_view.add_child(_forum_primary_action)
	_forum_abandon_action = Button.new()
	_forum_abandon_action.text = "放弃任务并重新开放"
	_forum_abandon_action.pressed.connect(_abandon_selected_task)
	_forum_detail_view.add_child(_forum_abandon_action)
	root.add_child(_forum_detail_view)
	return root


func _open_app(app_id: String, app_name: String) -> void:
	_app_title.text = app_name
	var is_forum := app_id == "forums"
	var is_club := app_id == "clubs"
	var is_party := app_id == "party"
	var is_message := app_id == "messages"
	_content.visible = not is_forum and not is_club and not is_party and not is_message
	_forum_root.visible = is_forum
	_club_root.visible = is_club
	_party_root.visible = is_party
	_message_root.visible = is_message
	if is_forum:
		_forum_feedback.text = ""
		_show_forum_list()
	elif is_club:
		_club_feedback.text = ""
		_refresh_club_page()
	elif is_party:
		_party_feedback.text = ""
		_refresh_party_page()
	elif is_message:
		_message_feedback.text = ""
		_refresh_message_page()
	else:
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
		return "[b]第 %d 天 · %s[/b]\n当前计划：%s\n地点：%s\n主要行动剩余：%d\n\n[b]学院能力 · 心理学院[/b]\n%s\n\n[color=#9aa8bd]能力同时用于表世界检定，并生成角色绑定的战斗卡牌。[/color]" % [int(clock.get("day", 1)), SimulationBridge.phase_display_name(String(clock.get("phase", "morning"))), plan.get("activity_id", "自由安排"), plan.get("location_id", "未安排"), int((player.get("action_budget", {}) as Dictionary).get("major_remaining", 0)), _ability_lines(player.get("abilities", []))]
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
	return "[b]校园通讯[/b]\n\n联系人和持久聊天记录已经接入。"


func _refresh_message_page() -> void:
	var messaging: Dictionary = SimulationBridge.campus_snapshot.get("messaging", {})
	var contacts: Array = messaging.get("contacts", [])
	var previous := _selected_message_contact_id
	_message_contact_picker.clear()
	var selected_index := 0
	for contact in contacts:
		if not contact is Dictionary:
			continue
		var contact_id := String(contact.get("actor_id", ""))
		var unread := int(contact.get("unread_count", 0))
		var prefix := "[%d条未读] " % unread if unread > 0 else ""
		var index := _message_contact_picker.item_count
		_message_contact_picker.add_item("%s%s" % [prefix, contact.get("display_name", contact_id)])
		_message_contact_picker.set_item_metadata(index, contact_id)
		if contact_id == previous:
			selected_index = index
	if _message_contact_picker.item_count == 0:
		_selected_message_contact_id = ""
		_message_log.text = "联系人数据尚未同步。"
		_message_send_action.disabled = true
		return
	_message_contact_picker.select(selected_index)
	_selected_message_contact_id = String(_message_contact_picker.get_item_metadata(selected_index))
	_message_send_action.disabled = false
	_refresh_message_thread()


func _refresh_message_thread() -> void:
	var messaging: Dictionary = SimulationBridge.campus_snapshot.get("messaging", {})
	var threads: Dictionary = messaging.get("threads", {})
	var thread: Dictionary = threads.get(_selected_message_contact_id, {})
	var lines: Array[String] = []
	for message in thread.get("messages", []):
		if not message is Dictionary:
			continue
		var mine := String(message.get("sender_id", "")) == "player"
		var author := "我" if mine else String(thread.get("counterpart_name", "联系人"))
		var safe_text := String(message.get("text", "")).replace("[", "［").replace("]", "］")
		lines.append("[color=#91a4bc]D%d %s[/color]  [b]%s[/b]\n%s" % [
			int(message.get("day", 1)),
			SimulationBridge.phase_display_name(String(message.get("phase", "morning"))),
			author, safe_text,
		])
	if lines.is_empty():
		_message_log.text = "[color=#91a4bc]还没有聊天记录。你们不需要处于同一地点即可联系。[/color]"
	else:
		_message_log.text = "\n\n".join(lines)
		_message_log.scroll_to_line(max(0, _message_log.get_line_count() - 1))
	if int(thread.get("unread_count", 0)) > 0 and not SimulationBridge.is_campus_busy():
		SimulationBridge.operate_campus_message("MARK_PHONE_THREAD_READ", _selected_message_contact_id)


func _select_message_contact(index: int) -> void:
	_selected_message_contact_id = String(_message_contact_picker.get_item_metadata(index))
	_message_feedback.text = ""
	_refresh_message_thread()


func _send_phone_message() -> void:
	_send_phone_message_from_input(_message_input.text)


func _send_phone_message_from_input(text: String) -> void:
	var cleaned := text.strip_edges()
	if cleaned.is_empty() or _selected_message_contact_id.is_empty():
		_message_feedback.text = "请输入要发送的内容。"
		return
	_message_feedback.text = "正在发送……"
	_message_send_action.disabled = true
	SimulationBridge.operate_campus_message(
		"SEND_PHONE_MESSAGE", _selected_message_contact_id, cleaned
	)


func _on_phone_message_completed(
	success: bool, result: Dictionary, action_id: String, target_id: String
) -> void:
	if target_id != _selected_message_contact_id:
		return
	var command_result: Dictionary = result.get("result", {})
	if action_id == "SEND_PHONE_MESSAGE":
		_message_feedback.text = String(command_result.get("message", result.get("error", "消息发送失败")))
		_message_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
		if success:
			_message_input.clear()
	_message_send_action.disabled = false
	_refresh_message_page()


func _set_forum_filter(filter_id: String) -> void:
	_forum_filter = filter_id
	_refresh_forum_list()


func _show_forum_list() -> void:
	_selected_task_id = ""
	_forum_list_view.visible = true
	_forum_detail_view.visible = false
	_refresh_forum_list()


func _refresh_forum_list() -> void:
	if _forum_cards == null:
		return
	for child in _forum_cards.get_children():
		_forum_cards.remove_child(child)
		child.queue_free()
	var campus: Dictionary = SimulationBridge.campus_snapshot
	var summary: Dictionary = campus.get("task_summary", {})
	var summary_label := _forum_list_view.get_node("TaskSummary") as Label
	summary_label.text = "今日动态 · %d 个可接 · %d 个由你锁定" % [
		int(summary.get("available", 0)), int(summary.get("mine", 0))
	]
	var tasks: Dictionary = campus.get("tasks", {})
	var visible_tasks: Array[Dictionary] = []
	for value in tasks.values():
		if value is Dictionary and _task_matches_filter(value):
			visible_tasks.append(value)
	visible_tasks.sort_custom(_sort_tasks)
	for task in visible_tasks:
		var card := Button.new()
		card.custom_minimum_size = Vector2(0, 76)
		card.alignment = HORIZONTAL_ALIGNMENT_LEFT
		card.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		card.text = "%s  %s\n发起：%s  ·  %s  ·  D%d截止\n%d人查看 · %d人考虑" % [
			_task_state_label(task), task.get("title", "未命名任务"),
			task.get("issuer_name", "校园用户"), task.get("scene_name", "未知地点"),
			int(task.get("expires_day", 1)), int(task.get("viewer_count", 0)),
			int(task.get("considering_count", 0)),
		]
		card.add_theme_stylebox_override("normal", _task_card_style(task))
		card.pressed.connect(_open_task_detail.bind(String(task.get("task_id", ""))))
		_forum_cards.add_child(card)
	if visible_tasks.is_empty():
		var empty := Label.new()
		empty.text = "这个分类暂时没有任务。\n推进时段后，论坛状态会继续变化。"
		empty.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		empty.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		_forum_cards.add_child(empty)


func _task_matches_filter(task: Dictionary) -> bool:
	var state := String(task.get("state", ""))
	if _forum_filter == "mine":
		return bool(task.get("owned_by_player", false))
	if _forum_filter == "ended":
		return state in ["completed", "failed", "abandoned", "expired"]
	return state in ["open", "viewed", "considering"]


func _sort_tasks(a: Dictionary, b: Dictionary) -> bool:
	var a_day := int(a.get("expires_day", 999))
	var b_day := int(b.get("expires_day", 999))
	if a_day != b_day:
		return a_day < b_day
	return String(a.get("title", "")) < String(b.get("title", ""))


func _task_state_label(task: Dictionary) -> String:
	if bool(task.get("owned_by_player", false)):
		return "[我的]"
	return {
		"open": "[新]", "viewed": "[浏览中]", "considering": "[竞争中]",
		"locked": "[已被接取]", "in_progress": "[进行中]",
		"completed": "[已完成]", "failed": "[失败]", "expired": "[过期]",
	}.get(String(task.get("state", "")), "[已结束]")


func _task_card_style(task: Dictionary) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = Color("20293a") if not bool(task.get("owned_by_player", false)) else Color("263953")
	style.border_color = Color("536b8f") if int(task.get("considering_count", 0)) == 0 else Color("a46b54")
	style.set_border_width_all(1)
	style.set_corner_radius_all(8)
	style.content_margin_left = 10
	style.content_margin_right = 8
	return style


func _open_task_detail(task_id: String) -> void:
	_selected_task_id = task_id
	_forum_list_view.visible = false
	_forum_detail_view.visible = true
	_refresh_forum_detail()
	var task: Dictionary = (SimulationBridge.campus_snapshot.get("tasks", {}) as Dictionary).get(task_id, {})
	if not task.is_empty() and not bool(task.get("viewed_by_player", false)):
		SimulationBridge.operate_campus_task("VIEW_FORUM_TASK", task_id)


func _refresh_forum_detail() -> void:
	var task: Dictionary = (SimulationBridge.campus_snapshot.get("tasks", {}) as Dictionary).get(_selected_task_id, {})
	if task.is_empty():
		_show_forum_list()
		return
	var reward: Dictionary = task.get("reward", {})
	var completed_social: Dictionary = (task.get("social_consequences", {}) as Dictionary).get("completed", {})
	var relation_reward: Dictionary = completed_social.get("issuer_relationship", {})
	var social_parts: Array[String] = []
	var relationship_labels := {
		"familiarity": "熟悉",
		"trust": "信任",
		"closeness": "亲近",
		"respect": "尊重",
		"suspicion": "怀疑",
		"fear": "畏惧",
		"obligation": "人情",
		"conflict": "冲突",
	}
	for dimension in relationship_labels:
		var amount := int(relation_reward.get(dimension, 0))
		if amount != 0:
			social_parts.append("%s %+d" % [relationship_labels[dimension], amount])
	var organization_name := String(task.get("organization_name", ""))
	var origin_value: Variant = task.get("origin_summary", "")
	var origin_summary: String = origin_value if origin_value is String else ""
	var origin_text := origin_summary if not origin_summary.is_empty() else "固定校园委托"
	var preferred_value: Variant = task.get("preferred_assignee_name", "")
	var preferred_name: String = preferred_value if preferred_value is String else ""
	if not preferred_name.is_empty():
		origin_text += " · 原约定对象：%s（其他人仍可接取）" % preferred_name
	var organization_reputation := int(completed_social.get("organization_reputation", 0))
	if not organization_name.is_empty() and organization_reputation != 0:
		social_parts.append("%s声望 %+d" % [organization_name, organization_reputation])
	var social_reward_text := "预计：%s" % "、".join(social_parts) if not social_parts.is_empty() else "无固定社会影响"
	var settled_social_value: Variant = task.get("social_result", {})
	var settled_social: Dictionary = settled_social_value if settled_social_value is Dictionary else {}
	if not settled_social.is_empty():
		var settled_parts: Array[String] = []
		var settled_relation: Dictionary = settled_social.get("relationship_delta", {})
		for dimension in relationship_labels:
			var amount := int(settled_relation.get(dimension, 0))
			if amount != 0:
				settled_parts.append("%s %+d" % [relationship_labels[dimension], amount])
		var settled_organization: Dictionary = settled_social.get("organization", {})
		var reputation_delta := int(settled_organization.get("reputation_delta", 0))
		if not organization_name.is_empty() and reputation_delta != 0:
			settled_parts.append("%s声望 %+d" % [organization_name, reputation_delta])
		if not settled_parts.is_empty():
			social_reward_text = "已结算：%s" % "、".join(settled_parts)
	var history_lines: Array[String] = []
	for entry in task.get("history", []):
		if entry is Dictionary:
			history_lines.append("D%d %s · %s" % [
				int(entry.get("day", 1)),
				SimulationBridge.phase_display_name(String(entry.get("phase", "morning"))),
				entry.get("message", ""),
			])
	_forum_detail.text = "[font_size=22][b]%s[/b][/font_size]\n%s\n\n[b]发起人[/b]  %s\n[b]任务来源[/b]  %s\n[b]所属组织[/b]  %s\n[b]地点[/b]  %s\n[b]截止[/b]  第 %d 天\n[b]报酬[/b]  %d 校园币\n[b]社会影响[/b]  %s\n\n[b]当前目标[/b]\n%s\n\n[b]竞争情况[/b]\n%d 人查看，%d 人正在考虑\n\n[b]动态记录[/b]\n%s" % [
		task.get("title", "未命名任务"), task.get("description", ""),
		task.get("issuer_name", "校园用户"), origin_text,
		organization_name if not organization_name.is_empty() else "个人委托",
		task.get("scene_name", "未知地点"),
		int(task.get("expires_day", 1)), int(reward.get("wealth", 0)),
		social_reward_text, task.get("objective", ""), int(task.get("viewer_count", 0)),
		int(task.get("considering_count", 0)), "\n".join(history_lines),
	]
	var state := String(task.get("state", ""))
	var owned := bool(task.get("owned_by_player", false))
	_forum_abandon_action.visible = owned and state in ["locked", "in_progress"]
	_forum_primary_action.visible = true
	_forum_primary_action.disabled = false
	if state in ["open", "viewed", "considering"]:
		_forum_primary_action.text = "接下任务 · 免费操作"
	elif owned and state == "locked":
		var player: Dictionary = SimulationBridge.campus_snapshot.get("player", {})
		var player_location = player.get("current_location_id")
		var at_location: bool = player_location in [
			task.get("scene_id"), task.get("execution_region_id")
		]
		var phase: String = String((SimulationBridge.campus_snapshot.get("clock", {}) as Dictionary).get("phase", "morning"))
		var phase_allowed: bool = phase in task.get("allowed_phases", [])
		if not at_location:
			_forum_primary_action.text = "请先前往：%s" % task.get("scene_name", "任务地点")
		elif not phase_allowed:
			_forum_primary_action.text = "当前时段无法执行"
		else:
			_forum_primary_action.text = "完成当前目标"
		_forum_primary_action.disabled = not at_location or not phase_allowed
	else:
		_forum_primary_action.text = _task_state_label(task)
		_forum_primary_action.disabled = true


func _perform_primary_task_action() -> void:
	var task: Dictionary = (SimulationBridge.campus_snapshot.get("tasks", {}) as Dictionary).get(_selected_task_id, {})
	if task.is_empty():
		return
	var state := String(task.get("state", ""))
	_forum_feedback.text = "正在同步论坛状态……"
	if state in ["open", "viewed", "considering"]:
		SimulationBridge.operate_campus_task(
			"CLAIM_FORUM_TASK", _selected_task_id, int(task.get("lock_revision", 0))
		)
	elif bool(task.get("owned_by_player", false)) and state == "locked":
		SimulationBridge.operate_campus_task("COMPLETE_FORUM_TASK", _selected_task_id)


func _abandon_selected_task() -> void:
	_forum_feedback.text = "正在释放任务锁定……"
	SimulationBridge.operate_campus_task("ABANDON_FORUM_TASK", _selected_task_id)


func _on_task_operation_completed(success: bool, result: Dictionary, _action_id: String, task_id: String) -> void:
	if task_id != _selected_task_id:
		return
	var command_result: Dictionary = result.get("result", {})
	_forum_feedback.text = String(command_result.get("message", result.get("error", "操作失败")))
	if not success:
		_forum_feedback.add_theme_color_override("font_color", Color("ee8174"))
	else:
		_forum_feedback.add_theme_color_override("font_color", Color("9bcf9b"))
	_refresh_forum_detail()


func _on_campus_snapshot_updated(_snapshot: Dictionary) -> void:
	if not _opened:
		return
	if _forum_root.visible:
		if _selected_task_id.is_empty():
			_refresh_forum_list()
		else:
			_refresh_forum_detail()
	elif _club_root.visible:
		_refresh_club_page()
	elif _party_root.visible:
		_refresh_party_page()
	elif _message_root.visible:
		_refresh_message_page()


func _refresh_club_page() -> void:
	var clubs: Dictionary = SimulationBridge.campus_snapshot.get("clubs", {})
	if clubs.is_empty():
		_club_detail.text = "社团数据尚未同步。"
		_club_membership_action.disabled = true
		_club_activity_action.disabled = true
		return
	var previous := _selected_club_id
	_club_picker.clear()
	var ids: Array = clubs.keys()
	ids.sort()
	var selected_index := 0
	for index in range(ids.size()):
		var club_id := String(ids[index])
		var club: Dictionary = clubs[club_id]
		var marker := " · 已加入" if club.get("viewer_membership") is Dictionary else ""
		_club_picker.add_item("%s%s" % [club.get("name", club_id), marker])
		_club_picker.set_item_metadata(index, club_id)
		if club_id == previous:
			selected_index = index
	_club_picker.select(selected_index)
	_selected_club_id = String(_club_picker.get_item_metadata(selected_index))
	_refresh_club_detail()


func _select_club(index: int) -> void:
	_selected_club_id = String(_club_picker.get_item_metadata(index))
	_club_feedback.text = ""
	_refresh_club_detail()


func _refresh_club_detail() -> void:
	var campus: Dictionary = SimulationBridge.campus_snapshot
	var club: Dictionary = (campus.get("clubs", {}) as Dictionary).get(_selected_club_id, {})
	if club.is_empty():
		return
	var resources: Dictionary = club.get("resources", {})
	var tactic: Dictionary = club.get("team_tactic", {})
	var membership_value: Variant = club.get("viewer_membership")
	var membership: Dictionary = membership_value if membership_value is Dictionary else {}
	var rank_names := {"member": "普通成员", "core_member": "骨干", "leader": "负责人"}
	var identity_text := "尚未加入"
	if not membership.is_empty():
		identity_text = "%s · 贡献 %d · 出勤 %d / 缺勤 %d" % [
			rank_names.get(String(membership.get("rank", "member")), "成员"),
			int(membership.get("contribution", 0)), int(membership.get("attendance_count", 0)),
			int(membership.get("absence_count", 0)),
		]
	var admission: Dictionary = club.get("admission", {})
	var admission_text: String = "已具备申请条件" if bool(admission.get("eligible", false)) else {
		"already_member": "你已经是成员",
		"requirements_not_met": "需要相关学院背景、社团任务声望或足够社交能力",
	}.get(String(admission.get("reason", "")), "暂不符合条件")
	var schedule_lines: Array[String] = []
	var weekday_names := ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
	for slot in club.get("activity_slots", []):
		if slot is Dictionary:
			var days: Array[String] = []
			for day in slot.get("days", []):
				days.append(weekday_names[clampi(int(day), 0, 6)])
			schedule_lines.append("%s %s" % ["、".join(days), SimulationBridge.phase_display_name(String(slot.get("phase", "")))])
	_club_detail.text = "[font_size=22][b]%s[/b][/font_size]\n%s\n\n[b]负责人[/b]  %s\n[b]成员[/b]  %d（无硬性人数上限）\n[b]公共资源[/b]  %d / %d（%s）\n[b]活动时间[/b]  %s\n\n[b]你的身份[/b]\n%s\n[b]入社评估[/b]\n%s\n\n[b]表世界实践[/b]  %s\n[b]团队战术[/b]  %s · 消耗 %d 公共资源\n[color=#91a4bc]可加入多个社团；能否实际参加由活动时间冲突和主要行动次数决定。团队战术需要至少两名同社团成员，并由骨干或负责人组织。[/color]" % [
		club.get("name", _selected_club_id), club.get("category", ""),
		club.get("leader_name", "未知"), int(club.get("member_count", 0)),
		int(resources.get("current", 0)),
		int(resources.get("capacity", 0)), resources.get("resource_id", ""),
		"；".join(schedule_lines), identity_text, admission_text, club.get("surface_skill", ""),
		tactic.get("name", tactic.get("tactic_id", "")), int(tactic.get("resource_cost", 0)),
	]
	var player: Dictionary = campus.get("player", {})
	var clock: Dictionary = campus.get("clock", {})
	var at_club := String(player.get("current_location_id", "")) == "club_room_pool"
	var phase := String(clock.get("phase", "morning"))
	var reception_open := phase != "late_night"
	if membership.is_empty():
		_club_membership_action.text = "申请加入"
		_club_membership_action.disabled = not bool(admission.get("eligible", false)) or not at_club or not reception_open
	else:
		_club_membership_action.text = "退出社团"
		_club_membership_action.disabled = String(membership.get("rank", "")) == "leader"
	var major_remaining := int((player.get("action_budget", {}) as Dictionary).get("major_remaining", 0))
	_club_activity_action.disabled = membership.is_empty() or not at_club or not bool(club.get("activity_open_now", false)) or major_remaining <= 0


func _perform_club_membership_action() -> void:
	var club: Dictionary = (SimulationBridge.campus_snapshot.get("clubs", {}) as Dictionary).get(_selected_club_id, {})
	var action_id := "LEAVE_CAMPUS_CLUB" if club.get("viewer_membership") is Dictionary else "JOIN_CAMPUS_CLUB"
	_club_feedback.text = "正在提交社团申请……"
	SimulationBridge.operate_campus_club(action_id, _selected_club_id)


func _perform_club_activity() -> void:
	_club_feedback.text = "正在结算社团活动……"
	SimulationBridge.operate_campus_club("CLUB_ACTIVITY", _selected_club_id)


func _on_club_operation_completed(success: bool, result: Dictionary, _action_id: String, club_id: String) -> void:
	if club_id != _selected_club_id:
		return
	var command_result: Dictionary = result.get("result", {})
	_club_feedback.text = String(command_result.get("message", result.get("error", "社团操作失败")))
	_club_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	_refresh_club_page()


func _refresh_party_page() -> void:
	var party: Dictionary = SimulationBridge.campus_snapshot.get("party", {})
	if party.is_empty():
		_party_detail.text = "队伍数据尚未同步。"
		_party_invite_action.disabled = true
		_party_dismiss_action.disabled = true
		return
	var band_names := {"fragile": "脆弱", "uncertain": "磨合中", "steady": "稳定", "cohesive": "默契"}
	var response_names := {"likely_accept": "较愿意", "uncertain": "态度不明", "likely_decline": "较可能拒绝"}
	var member_lines: Array[String] = []
	for member in party.get("members", []):
		if member is Dictionary:
			var status := "队长" if String(member.get("status", "")) == "leader" else "已承诺至第%d天" % int(member.get("commitment_until_day", 1))
			member_lines.append("• %s · %s" % [member.get("display_name", member.get("actor_id", "")), status])
	var skill_lines: Array[String] = []
	var stability: Dictionary = party.get("stability", {})
	for skill in stability.get("active_collaboration_skills", []):
		if skill is Dictionary and bool(skill.get("active", false)):
			skill_lines.append("• %s（%s）" % [skill.get("name", skill.get("skill_id", "")), skill.get("source_name", "")])
	if skill_lines.is_empty():
		skill_lines.append("尚未形成关系协作能力")
	_party_detail.text = "[font_size=22][b]行动小队 %d / %d[/b][/font_size]\n用途：夜相调查准备\n稳定度：%d · %s\n\n[b]当前成员[/b]\n%s\n\n[b]关系协作能力[/b]\n%s\n\n[color=#91a4bc]邀请不会消耗主要行动。NPC 会根据关系、性格、压力、共同学院/社团和夜间行动意愿自行接受或拒绝；拒绝后当天不能反复邀请。[/color]" % [
		int(party.get("member_count", 1)), int(party.get("max_members", 3)),
		int(stability.get("score", 0)), band_names.get(String(stability.get("band", "uncertain")), "未知"),
		"\n".join(member_lines), "\n".join(skill_lines),
	]
	var previous_candidate := _selected_party_candidate_id
	_party_candidate_picker.clear()
	var candidate_index := 0
	for candidate in party.get("candidates", []):
		if not candidate is Dictionary or String(candidate.get("expected_response", "")) == "unavailable":
			continue
		var index := _party_candidate_picker.item_count
		_party_candidate_picker.add_item("%s · %s" % [candidate.get("display_name", "未知"), response_names.get(String(candidate.get("expected_response", "")), "未知")])
		_party_candidate_picker.set_item_metadata(index, candidate.get("actor_id", ""))
		if String(candidate.get("actor_id", "")) == previous_candidate:
			candidate_index = index
	if _party_candidate_picker.item_count > 0:
		_party_candidate_picker.select(candidate_index)
		_selected_party_candidate_id = String(_party_candidate_picker.get_item_metadata(candidate_index))
	else:
		_selected_party_candidate_id = ""
	_party_invite_action.disabled = bool(party.get("is_full", false)) or _selected_party_candidate_id.is_empty()
	var previous_member := _selected_party_member_id
	_party_member_picker.clear()
	var member_index := 0
	for member in party.get("members", []):
		if not member is Dictionary or String(member.get("status", "")) == "leader":
			continue
		var index := _party_member_picker.item_count
		_party_member_picker.add_item(String(member.get("display_name", member.get("actor_id", ""))))
		_party_member_picker.set_item_metadata(index, member.get("actor_id", ""))
		if String(member.get("actor_id", "")) == previous_member:
			member_index = index
	if _party_member_picker.item_count > 0:
		_party_member_picker.select(member_index)
		_selected_party_member_id = String(_party_member_picker.get_item_metadata(member_index))
	else:
		_selected_party_member_id = ""
	_party_dismiss_action.disabled = _selected_party_member_id.is_empty()


func _select_party_candidate(index: int) -> void:
	_selected_party_candidate_id = String(_party_candidate_picker.get_item_metadata(index))


func _select_party_member(index: int) -> void:
	_selected_party_member_id = String(_party_member_picker.get_item_metadata(index))


func _invite_party_candidate() -> void:
	_party_feedback.text = "正在等待对方决定……"
	SimulationBridge.operate_campus_party("INVITE_PARTY_MEMBER", _selected_party_candidate_id)


func _dismiss_party_member() -> void:
	_party_feedback.text = "正在解除同行承诺……"
	SimulationBridge.operate_campus_party("DISMISS_PARTY_MEMBER", _selected_party_member_id)


func _on_party_operation_completed(success: bool, result: Dictionary, _action_id: String, _target_id: String) -> void:
	var command_result: Dictionary = result.get("result", {})
	_party_feedback.text = String(command_result.get("message", result.get("error", "组队操作失败")))
	_party_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	_refresh_party_page()


func _dictionary_lines(value: Variant) -> String:
	if not value is Dictionary or value.is_empty():
		return "暂无数据"
	var keys: Array = value.keys()
	keys.sort()
	var lines: Array[String] = []
	for key in keys:
		lines.append("%s：%s" % [key, value[key]])
	return "\n".join(lines)


func _ability_lines(value: Variant) -> String:
	if not value is Array or value.is_empty():
		return "能力数据尚未同步"
	var type_names := {
		"attack": "攻击", "control": "控制", "defense": "防御",
		"knowledge": "知识", "signature": "专业", "support": "支援",
		"technique": "技巧",
	}
	var lines: Array[String] = []
	var cards: Dictionary = {}
	for card in (SimulationBridge.campus_snapshot.get("player", {}) as Dictionary).get("card_pool", []):
		if card is Dictionary:
			cards[String(card.get("source_ability_id", ""))] = card
	for ability in value:
		if not ability is Dictionary:
			continue
		var ability_id := String(ability.get("ability_id", ""))
		var card: Dictionary = cards.get(ability_id, {})
		var specialization := " · 专业分支" if ability.get("source_kind", "common") == "specialization" else ""
		lines.append("• %s  Lv.%d%s  [%s/耗%d]" % [
			ability.get("name", ability_id), int(ability.get("rank", 1)), specialization,
			type_names.get(String(card.get("card_type", "")), "能力"),
			int(card.get("command_cost", 0)),
		])
	return "\n".join(lines)


func _show_home() -> void:
	_home.visible = true
	_app_page.visible = false
	_forum_root.visible = false
	_club_root.visible = false
	_party_root.visible = false
	_content.visible = true


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
