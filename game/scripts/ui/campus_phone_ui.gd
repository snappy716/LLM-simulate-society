extends CanvasLayer

const APPS := [
	{"id": "saves", "name": "存读档", "icon": "档", "color": Color("557e91")},
	{"id": "messages", "name": "校园通讯", "icon": "讯", "color": Color("35c96f")},
	{"id": "courses", "name": "课程平台", "icon": "课", "color": Color("3988e8")},
	{"id": "album", "name": "校园相册", "icon": "册", "color": Color("d65bd1")},
	{"id": "notes", "name": "备忘录", "icon": "记", "color": Color("edc84b")},
	{"id": "market", "name": "校园商城", "icon": "商", "color": Color("ed6540")},
	{"id": "trade", "name": "当面交易", "icon": "换", "color": Color("b38354")},
	{"id": "wallet", "name": "电子钱包", "icon": "钱", "color": Color("4f73cd")},
	{"id": "health", "name": "健康档案", "icon": "健", "color": Color("e95d70")},
	{"id": "clubs", "name": "社团中心", "icon": "社", "color": Color("c47a46")},
	{"id": "party", "name": "行动小队", "icon": "队", "color": Color("477f8f")},
	{"id": "combat", "name": "夜战部署", "icon": "战", "color": Color("9a4f62")},
	{"id": "forums", "name": "双层论坛", "icon": "坛", "color": Color("785bc7")},
]

var _overlay: ColorRect
var _home: Control
var _app_page: VBoxContainer
var _app_title: Label
var _content: RichTextLabel
var _inventory_root: VBoxContainer
var _trade_root: VBoxContainer
var _health_root: VBoxContainer
var _save_root: VBoxContainer
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
var _forum_channel := "surface"
var _forum_surface_button: Button
var _forum_night_button: Button
var _forum_access_note: Label
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
var _selected_party_candidate_is_contact := false
var _selected_party_member_id := ""
var _combat_root: VBoxContainer
var _combat_task_picker: OptionButton
var _combat_prepare_action: Button
var _combat_formation_detail: RichTextLabel
var _combat_character_picker: OptionButton
var _combat_row_picker: OptionButton
var _combat_deploy_action: Button
var _combat_withdraw_action: Button
var _combat_confirm_action: Button
var _combat_cancel_action: Button
var _combat_start_action: Button
var _combat_hand_detail: RichTextLabel
var _combat_end_round_action: Button
var _combat_card_picker: OptionButton
var _combat_card_target_picker: OptionButton
var _combat_play_card_action: Button
var _combat_base_picker: OptionButton
var _combat_base_target_picker: OptionButton
var _combat_use_base_action: Button
var _combat_feedback: Label
var _selected_combat_task_id := ""
var _selected_character_card_id := ""
var _selected_combat_card_id := ""
var _selected_combat_base_actor_id := ""
var _message_root: VBoxContainer
var _message_contact_picker: OptionButton
var _message_log: RichTextLabel
var _message_input: LineEdit
var _message_send_action: Button
var _message_feedback: Label
var _message_proposal_picker: OptionButton
var _message_proposal_action: Button
var _incoming_proposal_picker: OptionButton
var _incoming_proposal_accept: Button
var _incoming_proposal_decline: Button
var _selected_message_contact_id := ""


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("campus_phone_ui")
	_build_ui()
	SimulationBridge.campus_snapshot_updated.connect(_on_campus_snapshot_updated)
	SimulationBridge.campus_task_operation_completed.connect(_on_task_operation_completed)
	SimulationBridge.campus_club_operation_completed.connect(_on_club_operation_completed)
	SimulationBridge.campus_party_operation_completed.connect(_on_party_operation_completed)
	SimulationBridge.campus_combat_operation_completed.connect(_on_combat_operation_completed)
	SimulationBridge.campus_phone_message_completed.connect(_on_phone_message_completed)
	SimulationBridge.campus_social_proposal_completed.connect(_on_social_proposal_completed)
	SimulationBridge.campus_social_proposal_response_completed.connect(_on_social_proposal_response_completed)


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
	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	var grid := GridContainer.new()
	scroll.add_child(grid)
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
	return scroll


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
	_inventory_root = preload("res://scripts/ui/campus_inventory_panel.gd").new()
	_inventory_root.visible = false
	page.add_child(_inventory_root)
	_trade_root = preload("res://scripts/ui/campus_trade_panel.gd").new()
	_trade_root.visible = false
	page.add_child(_trade_root)
	_health_root = preload("res://scripts/ui/campus_health_panel.gd").new()
	_health_root.visible = false
	page.add_child(_health_root)
	_save_root = preload("res://scripts/ui/campus_save_panel.gd").new()
	_save_root.visible = false
	page.add_child(_save_root)
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
	_combat_root = _build_combat_page()
	_combat_root.visible = false
	_combat_root.size_flags_vertical = Control.SIZE_EXPAND_FILL
	page.add_child(_combat_root)
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
	var proposal_row := HBoxContainer.new()
	_message_proposal_picker = OptionButton.new()
	_message_proposal_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for proposal in [
		{"id": "party_invite", "name": "邀请加入行动小队"},
		{"id": "task_help", "name": "请求协助当前任务"},
		{"id": "meet_up", "name": "约定稍后见面"},
		{"id": "follow_up", "name": "兑现已有约定"},
	]:
		_message_proposal_picker.add_item(String(proposal["name"]))
		_message_proposal_picker.set_item_metadata(_message_proposal_picker.item_count - 1, String(proposal["id"]))
	proposal_row.add_child(_message_proposal_picker)
	_message_proposal_action = Button.new()
	_message_proposal_action.text = "正式提出"
	_message_proposal_action.pressed.connect(_send_phone_proposal)
	proposal_row.add_child(_message_proposal_action)
	root.add_child(proposal_row)
	var incoming_label := Label.new()
	incoming_label.text = "待处理请求（NPC 会按自己的计划主动提出）"
	incoming_label.add_theme_color_override("font_color", Color("91a4bc"))
	root.add_child(incoming_label)
	_incoming_proposal_picker = OptionButton.new()
	root.add_child(_incoming_proposal_picker)
	var incoming_actions := HBoxContainer.new()
	_incoming_proposal_accept = Button.new()
	_incoming_proposal_accept.text = "接受"
	_incoming_proposal_accept.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_incoming_proposal_accept.pressed.connect(_respond_incoming_proposal.bind(true))
	incoming_actions.add_child(_incoming_proposal_accept)
	_incoming_proposal_decline = Button.new()
	_incoming_proposal_decline.text = "拒绝"
	_incoming_proposal_decline.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_incoming_proposal_decline.pressed.connect(_respond_incoming_proposal.bind(false))
	incoming_actions.add_child(_incoming_proposal_decline)
	root.add_child(incoming_actions)
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


func _build_combat_page() -> VBoxContainer:
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 7)
	var context_label := Label.new()
	context_label.text = "夜相任务与出战阵容"
	context_label.add_theme_color_override("font_color", Color("d7b27a"))
	root.add_child(context_label)
	var task_row := HBoxContainer.new()
	_combat_task_picker = OptionButton.new()
	_combat_task_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_combat_task_picker.item_selected.connect(_select_combat_task)
	task_row.add_child(_combat_task_picker)
	_combat_prepare_action = Button.new()
	_combat_prepare_action.text = "建立准备"
	_combat_prepare_action.pressed.connect(_start_combat_preparation)
	task_row.add_child(_combat_prepare_action)
	root.add_child(task_row)
	_combat_formation_detail = RichTextLabel.new()
	_combat_formation_detail.bbcode_enabled = true
	_combat_formation_detail.fit_content = false
	_combat_formation_detail.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_combat_formation_detail.add_theme_font_size_override("normal_font_size", 14)
	root.add_child(_combat_formation_detail)
	var selection_row := HBoxContainer.new()
	_combat_character_picker = OptionButton.new()
	_combat_character_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_combat_character_picker.item_selected.connect(_select_combat_character)
	selection_row.add_child(_combat_character_picker)
	_combat_row_picker = OptionButton.new()
	for row_entry in [
		{"id": "front", "name": "前排"},
		{"id": "middle", "name": "中排"},
		{"id": "back", "name": "后排"},
	]:
		_combat_row_picker.add_item(String(row_entry.name))
		_combat_row_picker.set_item_metadata(
			_combat_row_picker.item_count - 1, String(row_entry.id)
		)
	selection_row.add_child(_combat_row_picker)
	root.add_child(selection_row)
	var formation_actions := HBoxContainer.new()
	_combat_deploy_action = Button.new()
	_combat_deploy_action.text = "部署 / 换位"
	_combat_deploy_action.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_combat_deploy_action.pressed.connect(_deploy_or_reposition_character)
	formation_actions.add_child(_combat_deploy_action)
	_combat_withdraw_action = Button.new()
	_combat_withdraw_action.text = "撤回候选"
	_combat_withdraw_action.pressed.connect(_withdraw_combat_character)
	formation_actions.add_child(_combat_withdraw_action)
	root.add_child(formation_actions)
	var confirmation_actions := HBoxContainer.new()
	_combat_confirm_action = Button.new()
	_combat_confirm_action.text = "锁定阵型"
	_combat_confirm_action.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_combat_confirm_action.pressed.connect(_confirm_combat_deployment)
	confirmation_actions.add_child(_combat_confirm_action)
	_combat_cancel_action = Button.new()
	_combat_cancel_action.text = "取消准备"
	_combat_cancel_action.pressed.connect(_cancel_combat_preparation)
	confirmation_actions.add_child(_combat_cancel_action)
	root.add_child(confirmation_actions)
	var round_actions := HBoxContainer.new()
	_combat_start_action = Button.new()
	_combat_start_action.text = "开始战斗"
	_combat_start_action.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_combat_start_action.pressed.connect(_start_card_combat)
	round_actions.add_child(_combat_start_action)
	_combat_end_round_action = Button.new()
	_combat_end_round_action.text = "结束本轮"
	_combat_end_round_action.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_combat_end_round_action.pressed.connect(_end_combat_round)
	round_actions.add_child(_combat_end_round_action)
	root.add_child(round_actions)
	_combat_hand_detail = RichTextLabel.new()
	_combat_hand_detail.bbcode_enabled = true
	_combat_hand_detail.custom_minimum_size = Vector2(0, 92)
	_combat_hand_detail.add_theme_font_size_override("normal_font_size", 13)
	root.add_child(_combat_hand_detail)
	var card_action_row := HBoxContainer.new()
	_combat_card_picker = OptionButton.new()
	_combat_card_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_combat_card_picker.item_selected.connect(_select_combat_card)
	card_action_row.add_child(_combat_card_picker)
	_combat_card_target_picker = OptionButton.new()
	_combat_card_target_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card_action_row.add_child(_combat_card_target_picker)
	_combat_play_card_action = Button.new()
	_combat_play_card_action.text = "出牌"
	_combat_play_card_action.pressed.connect(_play_combat_card)
	card_action_row.add_child(_combat_play_card_action)
	root.add_child(card_action_row)
	var base_action_row := HBoxContainer.new()
	_combat_base_picker = OptionButton.new()
	_combat_base_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_combat_base_picker.item_selected.connect(_select_combat_base_command)
	base_action_row.add_child(_combat_base_picker)
	_combat_base_target_picker = OptionButton.new()
	_combat_base_target_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	base_action_row.add_child(_combat_base_target_picker)
	_combat_use_base_action = Button.new()
	_combat_use_base_action.text = "基础指令"
	_combat_use_base_action.pressed.connect(_use_combat_base_command)
	base_action_row.add_child(_combat_use_base_action)
	root.add_child(base_action_row)
	_combat_feedback = Label.new()
	_combat_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_combat_feedback.add_theme_color_override("font_color", Color("e0b86a"))
	root.add_child(_combat_feedback)
	return root


func _build_forum_page() -> VBoxContainer:
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 8)
	var channel_bar := HBoxContainer.new()
	_forum_surface_button = Button.new()
	_forum_surface_button.text = "表世界 · 校园广场"
	_forum_surface_button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_forum_surface_button.pressed.connect(_set_forum_channel.bind("surface"))
	channel_bar.add_child(_forum_surface_button)
	_forum_night_button = Button.new()
	_forum_night_button.text = "里世界 · 未发现"
	_forum_night_button.disabled = true
	_forum_night_button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_forum_night_button.pressed.connect(_set_forum_channel.bind("night"))
	channel_bar.add_child(_forum_night_button)
	root.add_child(channel_bar)
	_forum_access_note = Label.new()
	_forum_access_note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_forum_access_note.add_theme_color_override("font_color", Color("91a4bc"))
	root.add_child(_forum_access_note)

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
	var is_save := app_id == "saves"
	_save_root.visible = is_save
	if is_save:
		_save_root.call("refresh")
	var is_forum := app_id == "forums"
	var is_club := app_id == "clubs"
	var is_party := app_id == "party"
	var is_combat := app_id == "combat"
	var is_message := app_id == "messages"
	var is_inventory := app_id == "market"
	var is_trade := app_id == "trade"
	_trade_root.visible = is_trade
	if is_trade:
		_trade_root.call("refresh")
	var is_health := app_id == "health"
	_health_root.visible = is_health
	if is_health:
		_health_root.call("refresh")
	_inventory_root.visible = is_inventory
	if is_inventory:
		_inventory_root.call("refresh")
	_content.visible = not is_save and not is_forum and not is_club and not is_party and not is_combat and not is_message and not is_inventory and not is_health and not is_trade
	_forum_root.visible = is_forum
	_club_root.visible = is_club
	_party_root.visible = is_party
	_combat_root.visible = is_combat
	_message_root.visible = is_message
	if is_forum:
		_forum_feedback.text = ""
		_refresh_forum_channels()
		_show_forum_list()
	elif is_club:
		_club_feedback.text = ""
		_refresh_club_page()
	elif is_party:
		_party_feedback.text = ""
		_refresh_party_page()
	elif is_combat:
		_combat_feedback.text = ""
		_refresh_combat_page()
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
		return "[b]账户概览[/b]\n\n校园生活资金：%d 元\n\n余额与活动、购物使用同一账户。\n打开校园商城可查看背包、到店交易或操作物品。" % int(player.get("wealth", 0))
	if app_id == "health":
		return "[b]需求[/b]\n%s\n\n[b]情绪[/b]\n%s" % [_dictionary_lines(player.get("needs", {})), _dictionary_lines(player.get("emotions", {}))]
	if app_id == "market":
		return "背包与校园商店已接入校园权威状态；请到店交易。"
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
		_message_proposal_action.disabled = true
		_refresh_incoming_proposals()
		return
	_message_contact_picker.select(selected_index)
	_selected_message_contact_id = String(_message_contact_picker.get_item_metadata(selected_index))
	_message_send_action.disabled = false
	_message_proposal_action.disabled = false
	_refresh_message_thread()
	_refresh_incoming_proposals()


func _refresh_incoming_proposals() -> void:
	var previous_id := ""
	if _incoming_proposal_picker.item_count > 0 and _incoming_proposal_picker.selected >= 0:
		previous_id = String(_incoming_proposal_picker.get_item_metadata(_incoming_proposal_picker.selected))
	_incoming_proposal_picker.clear()
	var proposals: Array = (SimulationBridge.campus_snapshot.get("social", {}) as Dictionary).get("incoming_proposals", [])
	var selected_index := 0
	for proposal in proposals:
		if not proposal is Dictionary or String(proposal.get("status", "")) != "pending":
			continue
		var proposal_id := String(proposal.get("proposal_id", ""))
		var type_name: String = {
			"party_invite": "加入队伍",
			"task_help": "协助任务",
			"meet_up": "稍后见面",
			"follow_up": "兑现约定",
		}.get(String(proposal.get("proposal_type", "")), "社会请求")
		var channel_name: String = "手机" if String(proposal.get("channel", "")) == "phone" else "当面"
		var index := _incoming_proposal_picker.item_count
		_incoming_proposal_picker.add_item("%s · %s（%s）" % [proposal.get("initiator_name", "未知人物"), type_name, channel_name])
		_incoming_proposal_picker.set_item_metadata(index, proposal_id)
		if proposal_id == previous_id:
			selected_index = index
	var has_pending := _incoming_proposal_picker.item_count > 0
	_incoming_proposal_picker.disabled = not has_pending
	_incoming_proposal_accept.disabled = not has_pending
	_incoming_proposal_decline.disabled = not has_pending
	if has_pending:
		_incoming_proposal_picker.select(selected_index)


func _respond_incoming_proposal(accepted: bool) -> void:
	if _incoming_proposal_picker.selected < 0:
		return
	var proposal_id := String(_incoming_proposal_picker.get_item_metadata(_incoming_proposal_picker.selected))
	if proposal_id.is_empty():
		return
	_incoming_proposal_accept.disabled = true
	_incoming_proposal_decline.disabled = true
	_message_feedback.text = "正在记录你的决定……"
	SimulationBridge.respond_campus_social_proposal(proposal_id, accepted)


func _on_social_proposal_response_completed(
	success: bool, result: Dictionary, _proposal_id: String
) -> void:
	var command_result: Dictionary = result.get("result", {})
	_message_feedback.text = String(command_result.get("message", result.get("error", "请求处理失败")))
	_message_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	_refresh_message_page()


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


func _send_phone_proposal() -> void:
	if _selected_message_contact_id.is_empty() or _message_proposal_picker.selected < 0:
		return
	var proposal_type := String(_message_proposal_picker.get_item_metadata(_message_proposal_picker.selected))
	_message_feedback.text = "正在等待对方明确决定……"
	_message_proposal_action.disabled = true
	SimulationBridge.operate_campus_social_proposal(
		_selected_message_contact_id, proposal_type, "phone"
	)


func _on_social_proposal_completed(
	success: bool, result: Dictionary, target_id: String, proposal_type: String
) -> void:
	if proposal_type == "party_invite" and target_id == _selected_party_candidate_id:
		var party_result: Dictionary = result.get("result", {})
		var party_payload: Dictionary = party_result.get("payload", {})
		_party_feedback.text = String(party_payload.get("reply_text", party_result.get("message", result.get("error", "邀请未能送达"))))
		_party_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
		_refresh_party_page()
	if target_id != _selected_message_contact_id:
		return
	var command_result: Dictionary = result.get("result", {})
	var payload: Dictionary = command_result.get("payload", {})
	_message_feedback.text = String(payload.get("reply_text", command_result.get("message", result.get("error", "提议未能送达"))))
	_message_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	_message_proposal_action.disabled = false
	_refresh_message_page()


func _set_forum_filter(filter_id: String) -> void:
	_forum_filter = filter_id
	_refresh_forum_list()


func _set_forum_channel(channel_id: String) -> void:
	if channel_id == "night":
		var forum: Dictionary = (SimulationBridge.campus_snapshot.get("forums", {}) as Dictionary).get("night", {})
		if not bool(forum.get("enabled", false)):
			return
	_forum_channel = channel_id
	_selected_task_id = ""
	_refresh_forum_channels()
	_show_forum_list()


func _refresh_forum_channels() -> void:
	if _forum_surface_button == null or _forum_night_button == null:
		return
	var campus: Dictionary = SimulationBridge.campus_snapshot
	var night_forum: Dictionary = (campus.get("forums", {}) as Dictionary).get("night", {})
	var night_world: Dictionary = campus.get("night_world", {})
	var unlocked := bool(night_forum.get("enabled", false))
	var accessible := bool(night_forum.get("accessible", false))
	_forum_surface_button.disabled = _forum_channel == "surface"
	_forum_night_button.disabled = not unlocked or _forum_channel == "night"
	_forum_night_button.text = (
		"里世界 · 行动中" if accessible
		else "里世界 · 可浏览" if unlocked
		else "里世界 · 未发现"
	)
	if _forum_channel == "night":
		_forum_access_note.text = (
			"夜相频道 · 当前可竞争接取和执行异常委托。今晚有 %d 名 NPC 在行动。" % int(night_world.get("active_npc_count", 0))
			if accessible
			else "夜相频道 · 当前仅可查看记录；进入夜相后才能接取和执行。"
		)
	else:
		_forum_access_note.text = "校园公开频道 · 委托会被玩家与 NPC 持续浏览、锁定和完成。"


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
	_refresh_forum_channels()
	var all_summary: Dictionary = campus.get("task_summary", {})
	var summary: Dictionary = (all_summary.get("by_forum", {}) as Dictionary).get(_forum_channel, {})
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
	if String(task.get("forum", "surface")) != _forum_channel:
		return false
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
	var origin_text := origin_summary if not origin_summary.is_empty() else (
		"夜相巡查网络" if task.get("forum") == "night" else "固定校园委托"
	)
	var preferred_value: Variant = task.get("preferred_assignee_name", "")
	var preferred_name: String = preferred_value if preferred_value is String else ""
	if not preferred_name.is_empty():
		origin_text += " · 原约定对象：%s（其他人仍可接取）" % preferred_name
	var helper_names: Array[String] = []
	for helper_name in task.get("helper_names", []):
		helper_names.append(String(helper_name))
	var helper_text := "、".join(helper_names) if not helper_names.is_empty() else "暂无"
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
	var layer_name := "里世界" if task.get("forum") == "night" else "表世界"
	_forum_detail.text = "[font_size=22][b]%s[/b][/font_size]\n%s\n\n[b]层域[/b]  %s\n[b]发起人[/b]  %s\n[b]任务来源[/b]  %s\n[b]所属组织[/b]  %s\n[b]地点[/b]  %s\n[b]截止[/b]  第 %d 天\n[b]报酬[/b]  %d 校园币\n[b]协助者[/b]  %s\n[b]社会影响[/b]  %s\n\n[b]当前目标[/b]\n%s\n\n[b]竞争情况[/b]\n%d 人查看，%d 人正在考虑\n\n[b]动态记录[/b]\n%s" % [
		task.get("title", "未命名任务"), task.get("description", ""),
		layer_name, task.get("issuer_name", "校园用户"), origin_text,
		organization_name if not organization_name.is_empty() else "个人委托",
		task.get("scene_name", "未知地点"),
		int(task.get("expires_day", 1)), int(reward.get("wealth", 0)), helper_text,
		social_reward_text, task.get("objective", ""), int(task.get("viewer_count", 0)),
		int(task.get("considering_count", 0)), "\n".join(history_lines),
	]
	var state := String(task.get("state", ""))
	var owned := bool(task.get("owned_by_player", false))
	var requires_night: bool = String(task.get("forum", "surface")) == "night"
	var night_accessible := bool((SimulationBridge.campus_snapshot.get("night_world", {}) as Dictionary).get("night_forum_accessible", false))
	_forum_abandon_action.visible = owned and state in ["locked", "in_progress"]
	_forum_primary_action.visible = true
	_forum_primary_action.disabled = false
	if state in ["open", "viewed", "considering"]:
		_forum_primary_action.text = "接下任务 · 免费操作" if not requires_night or night_accessible else "进入夜相后可接取"
		_forum_primary_action.disabled = requires_night and not night_accessible
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
		_forum_primary_action.disabled = not at_location or not phase_allowed or (requires_night and not night_accessible)
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
	_refresh_clock()
	if _forum_root.visible:
		if _selected_task_id.is_empty():
			_refresh_forum_list()
		else:
			_refresh_forum_detail()
	elif _club_root.visible:
		_refresh_club_page()
	elif _party_root.visible:
		_refresh_party_page()
	elif _combat_root.visible:
		_refresh_combat_page()
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
		var contact_note := "" if bool(candidate.get("is_phone_contact", false)) else " · 需先交换联系方式"
		_party_candidate_picker.add_item("%s · %s%s" % [candidate.get("display_name", "未知"), response_names.get(String(candidate.get("expected_response", "")), "未知"), contact_note])
		_party_candidate_picker.set_item_metadata(index, candidate.get("actor_id", ""))
		_party_candidate_picker.set_item_tooltip(index, "phone_contact" if bool(candidate.get("is_phone_contact", false)) else "not_contact")
		if String(candidate.get("actor_id", "")) == previous_candidate:
			candidate_index = index
	if _party_candidate_picker.item_count > 0:
		_party_candidate_picker.select(candidate_index)
		_selected_party_candidate_id = String(_party_candidate_picker.get_item_metadata(candidate_index))
		_selected_party_candidate_is_contact = _party_candidate_picker.get_item_tooltip(candidate_index) == "phone_contact"
	else:
		_selected_party_candidate_id = ""
		_selected_party_candidate_is_contact = false
	_party_invite_action.disabled = bool(party.get("is_full", false)) or _selected_party_candidate_id.is_empty() or not _selected_party_candidate_is_contact
	_party_invite_action.text = "发出邀请" if _selected_party_candidate_is_contact else "先交换联系方式"
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
	_selected_party_candidate_is_contact = _party_candidate_picker.get_item_tooltip(index) == "phone_contact"
	_party_invite_action.disabled = _selected_party_candidate_id.is_empty() or not _selected_party_candidate_is_contact
	_party_invite_action.text = "发出邀请" if _selected_party_candidate_is_contact else "先交换联系方式"


func _select_party_member(index: int) -> void:
	_selected_party_member_id = String(_party_member_picker.get_item_metadata(index))


func _invite_party_candidate() -> void:
	_party_feedback.text = "正在等待对方决定……"
	SimulationBridge.operate_campus_social_proposal(
		_selected_party_candidate_id, "party_invite", "phone"
	)


func _dismiss_party_member() -> void:
	_party_feedback.text = "正在解除同行承诺……"
	SimulationBridge.operate_campus_party("DISMISS_PARTY_MEMBER", _selected_party_member_id)


func _on_party_operation_completed(success: bool, result: Dictionary, _action_id: String, _target_id: String) -> void:
	var command_result: Dictionary = result.get("result", {})
	_party_feedback.text = String(command_result.get("message", result.get("error", "组队操作失败")))
	_party_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	_refresh_party_page()


func _refresh_combat_page() -> void:
	var combat: Dictionary = SimulationBridge.campus_snapshot.get("combat", {})
	var reason_names := {
		"invalid_phase": "只有晚间或深夜可建立夜战阵型。",
		"night_layer_required": "先从时段面板进入夜相。",
		"owned_night_task_required": "先在里世界论坛锁定一个任务。",
		"task_location_required": "先前往任务所在校园区域。",
		"battle_already_active": "已有进行中的阵型准备。",
		"available": "可建立战斗准备。",
	}
	var previous_task := _selected_combat_task_id
	_combat_task_picker.clear()
	var selected_task_index := 0
	var first_at_scene_index := -1
	for task_value in combat.get("owned_night_tasks", []):
		if not task_value is Dictionary:
			continue
		var task: Dictionary = task_value
		var index := _combat_task_picker.item_count
		var location_note := "已到达" if bool(task.get("at_scene", false)) else "需前往 %s" % task.get("execution_region_id", "目标区域")
		_combat_task_picker.add_item("%s · %s" % [task.get("title", "夜相任务"), location_note])
		_combat_task_picker.set_item_metadata(index, task.get("task_id", ""))
		_combat_task_picker.set_item_tooltip(index, "at_scene" if bool(task.get("at_scene", false)) else "away")
		if bool(task.get("at_scene", false)) and first_at_scene_index < 0:
			first_at_scene_index = index
		if String(task.get("task_id", "")) == previous_task:
			selected_task_index = index
	if _combat_task_picker.item_count > 0:
		if previous_task.is_empty() and first_at_scene_index >= 0:
			selected_task_index = first_at_scene_index
		_combat_task_picker.select(selected_task_index)
		_selected_combat_task_id = String(_combat_task_picker.get_item_metadata(selected_task_index))
	else:
		_selected_combat_task_id = ""
	var active_value: Variant = combat.get("active_battle")
	var active: Dictionary = active_value if active_value is Dictionary else {}
	var selected_task_at_scene := (
		_combat_task_picker.selected >= 0
		and _combat_task_picker.get_item_tooltip(_combat_task_picker.selected) == "at_scene"
	)
	_combat_task_picker.disabled = not active.is_empty()
	_combat_prepare_action.disabled = (
		not active.is_empty()
		or not bool(combat.get("can_prepare", false))
		or _selected_combat_task_id.is_empty()
		or not selected_task_at_scene
	)

	if active.is_empty():
		_combat_formation_detail.text = "[font_size=21][b]人物牌部署[/b][/font_size]\n\n%s\n\n[color=#91a4bc]先接取夜相任务并抵达目标区域。部署不消耗生活主要行动；队友会按真实校园路线前来集合，不会凭空出现。[/color]" % reason_names.get(String(combat.get("preparation_reason", "")), "当前不能建立战斗准备。")
		_combat_character_picker.clear()
		_selected_character_card_id = ""
		_combat_character_picker.disabled = true
		_combat_row_picker.disabled = true
		_combat_deploy_action.disabled = true
		_combat_withdraw_action.disabled = true
		_combat_confirm_action.disabled = true
		_combat_cancel_action.disabled = true
		_combat_start_action.disabled = true
		_combat_end_round_action.disabled = true
		_reset_combat_action_controls()
		_combat_hand_detail.text = "[color=#91a4bc]锁定阵型后可生成个人八张牌组与共享战术手牌。[/color]"
		return

	var row_names := {"front": "前排", "middle": "中排", "back": "后排"}
	var cards: Dictionary = active.get("character_cards", {})
	var formation: Dictionary = (active.get("formations", {}) as Dictionary).get("party:player", {})
	var lines: Array[String] = []
	for row_id in ["front", "middle", "back"]:
		var names: Array[String] = []
		for card_id_value in formation.get(row_id, []):
			var deployed_card: Dictionary = cards.get(String(card_id_value), {})
			names.append(String(deployed_card.get("display_name", "未知人物")))
		lines.append("[b]%s[/b]  %s" % [row_names[row_id], " / ".join(names) if not names.is_empty() else "—"])
	var enemy_lines: Array[String] = []
	var enemy_units: Dictionary = active.get("enemy_units", {})
	var enemy_health: Dictionary = active.get("enemy_health", {})
	var enemy_formation: Dictionary = active.get("enemy_formations", {})
	for row_id in ["front", "middle", "back"]:
		var enemy_names: Array[String] = []
		for enemy_id_value in enemy_formation.get(row_id, []):
			var enemy_id := String(enemy_id_value)
			var enemy: Dictionary = enemy_units.get(enemy_id, {})
			enemy_names.append("%s %d/%d" % [
				enemy.get("display_name", "未知异常"),
				int(enemy_health.get(enemy_id, 0)),
				int(enemy.get("max_health", 0)),
			])
		enemy_lines.append("[b]%s[/b]  %s" % [row_names[row_id], " / ".join(enemy_names) if not enemy_names.is_empty() else "—"])
	var phase_names := {
		"setup": "准备中", "ready": "阵型已锁定", "player_turn": "玩家行动",
		"enemy_turn": "敌方行动", "round_end": "轮次结算", "resolved": "战斗结束",
	}
	var phase_name := String(phase_names.get(String(active.get("phase", "")), "战斗中"))
	_combat_formation_detail.text = "[font_size=21][b]%s[/b][/font_size]  ·  %s\n[b]我方阵型[/b]\n%s\n\n[b]敌方阵型[/b]\n%s\n\n[color=#91a4bc]每排最多两人；玩家必须上场；锁定后本场不能替补。目标与排位限制由模拟内核判定。[/color]" % [
		phase_name, active.get("battle_id", ""), "\n".join(lines), "\n".join(enemy_lines)
	]
	_refresh_combat_hand(active, cards)
	var previous_card := _selected_character_card_id
	_combat_character_picker.clear()
	var card_ids: Array = cards.keys()
	card_ids.sort()
	var selected_card_index := 0
	for card_id_value in card_ids:
		var card_id := String(card_id_value)
		var card: Dictionary = cards[card_id]
		var deployment_state := String(card.get("deployment_state", ""))
		var state_name := "未知"
		if deployment_state == "reserve":
			state_name = "候选"
		elif deployment_state == "deployed":
			state_name = String(row_names.get(card.get("row"), "已部署"))
		elif deployment_state == "withdrawn":
			state_name = "未出战"
		elif deployment_state == "incapacitated":
			state_name = "倒下"
		var index := _combat_character_picker.item_count
		_combat_character_picker.add_item("%s · %s" % [card.get("display_name", "人物牌"), state_name])
		_combat_character_picker.set_item_metadata(index, card_id)
		if card_id == previous_card:
			selected_card_index = index
	if _combat_character_picker.item_count > 0:
		_combat_character_picker.select(selected_card_index)
		_selected_character_card_id = String(_combat_character_picker.get_item_metadata(selected_card_index))
	else:
		_selected_character_card_id = ""
	_refresh_combat_character_controls(active)


func _refresh_combat_hand(active: Dictionary, characters: Dictionary) -> void:
	var phase := String(active.get("phase", ""))
	if phase == "setup":
		_reset_combat_action_controls()
		_combat_hand_detail.text = "[color=#91a4bc]先完成人物牌部署。[/color]"
		return
	if phase == "ready":
		_reset_combat_action_controls()
		_combat_hand_detail.text = "[b]阵型已确认[/b]\n开始后，每名上场角色从个人八张牌组抽取两张，加入共享战术手牌。"
		return
	var team_id := "party:player"
	var points := int((active.get("command_points", {}) as Dictionary).get(team_id, 0))
	var cap := int(active.get("command_point_cap", 0))
	var actor_names: Dictionary = {}
	for character_value in characters.values():
		if character_value is Dictionary:
			actor_names[String(character_value.get("actor_id", ""))] = String(character_value.get("display_name", "人物"))
	var card_instances: Dictionary = active.get("card_instances", {})
	var hand_lines: Array[String] = []
	for instance_id_value in active.get("shared_hand_ids", []):
		var instance: Dictionary = card_instances.get(String(instance_id_value), {})
		if instance.is_empty():
			continue
		hand_lines.append("• %s / %s  [耗%d · %s]" % [
			actor_names.get(String(instance.get("owner_actor_id", "")), "人物"),
			instance.get("display_name", instance.get("card_id", "指令牌")),
			int(instance.get("command_cost", 0)),
			instance.get("card_type", "card"),
		])
	_combat_hand_detail.text = "[b]第 %d 轮 · 共享指令点 %d/%d[/b]\n%s" % [
		int(active.get("round", 1)), points, cap,
		"\n".join(hand_lines) if not hand_lines.is_empty() else "暂无可用手牌",
	]
	_refresh_combat_action_controls(active, characters)


func _reset_combat_action_controls() -> void:
	_selected_combat_card_id = ""
	_selected_combat_base_actor_id = ""
	_combat_card_picker.clear()
	_combat_card_target_picker.clear()
	_combat_base_picker.clear()
	_combat_base_target_picker.clear()
	_combat_card_picker.disabled = true
	_combat_card_target_picker.disabled = true
	_combat_play_card_action.disabled = true
	_combat_base_picker.disabled = true
	_combat_base_target_picker.disabled = true
	_combat_use_base_action.disabled = true


func _combat_target_name(active: Dictionary, characters: Dictionary, target_id: String) -> String:
	for value in characters.values():
		if value is Dictionary and String(value.get("actor_id", "")) == target_id:
			return String(value.get("display_name", target_id))
	var enemy: Dictionary = (active.get("enemy_units", {}) as Dictionary).get(target_id, {})
	if not enemy.is_empty():
		return "%s · %s排" % [
			enemy.get("display_name", target_id),
			{"front": "前", "middle": "中", "back": "后"}.get(enemy.get("row", ""), "未知"),
		]
	return target_id


func _refresh_combat_action_controls(active: Dictionary, characters: Dictionary) -> void:
	var action_options: Dictionary = active.get("action_options", {})
	var card_options: Dictionary = action_options.get("cards", {})
	var previous_card := _selected_combat_card_id
	_combat_card_picker.clear()
	var selected_card_index := 0
	for instance_id_value in active.get("shared_hand_ids", []):
		var instance_id := String(instance_id_value)
		var instance: Dictionary = (active.get("card_instances", {}) as Dictionary).get(instance_id, {})
		var owner: Dictionary = {}
		for character_value in characters.values():
			if character_value is Dictionary and String(character_value.get("actor_id", "")) == String(instance.get("owner_actor_id", "")):
				owner = character_value
				break
		var option: Dictionary = card_options.get(instance_id, {})
		var state_note := "可用" if bool(option.get("playable", false)) else "不可用"
		var index := _combat_card_picker.item_count
		_combat_card_picker.add_item("%s · %s · 耗%d · %s" % [
			owner.get("display_name", "人物"), instance.get("display_name", "指令牌"),
			int(instance.get("command_cost", 0)), state_note,
		])
		_combat_card_picker.set_item_metadata(index, instance_id)
		if instance_id == previous_card:
			selected_card_index = index
	_combat_card_picker.disabled = _combat_card_picker.item_count == 0
	if _combat_card_picker.item_count > 0:
		_combat_card_picker.select(selected_card_index)
		_selected_combat_card_id = String(_combat_card_picker.get_item_metadata(selected_card_index))
		_refresh_combat_card_targets(active, characters)
	else:
		_selected_combat_card_id = ""
		_combat_card_target_picker.clear()
		_combat_card_target_picker.disabled = true
		_combat_play_card_action.disabled = true

	var base_options: Dictionary = action_options.get("base_commands", {})
	var previous_actor := _selected_combat_base_actor_id
	_combat_base_picker.clear()
	var selected_base_index := 0
	var actor_ids: Array = base_options.keys()
	actor_ids.sort()
	for actor_id_value in actor_ids:
		var actor_id := String(actor_id_value)
		var option: Dictionary = base_options[actor_id]
		var actor_name := actor_id
		for character_value in characters.values():
			if character_value is Dictionary and String(character_value.get("actor_id", "")) == actor_id:
				actor_name = String(character_value.get("display_name", actor_id))
				break
		var state_note := "本轮已用" if bool(option.get("used", false)) else "耗%d" % int(option.get("command_cost", 0))
		var index := _combat_base_picker.item_count
		_combat_base_picker.add_item("%s · %s · %s" % [actor_name, option.get("display_name", "基础指令"), state_note])
		_combat_base_picker.set_item_metadata(index, actor_id)
		if actor_id == previous_actor:
			selected_base_index = index
	_combat_base_picker.disabled = _combat_base_picker.item_count == 0
	if _combat_base_picker.item_count > 0:
		_combat_base_picker.select(selected_base_index)
		_selected_combat_base_actor_id = String(_combat_base_picker.get_item_metadata(selected_base_index))
		_refresh_combat_base_targets(active, characters)
	else:
		_selected_combat_base_actor_id = ""
		_combat_base_target_picker.clear()
		_combat_base_target_picker.disabled = true
		_combat_use_base_action.disabled = true


func _refresh_combat_card_targets(active: Dictionary, characters: Dictionary) -> void:
	_combat_card_target_picker.clear()
	var option: Dictionary = (((active.get("action_options", {}) as Dictionary).get("cards", {}) as Dictionary).get(_selected_combat_card_id, {}))
	for target_id_value in option.get("target_ids", []):
		var target_id := String(target_id_value)
		var index := _combat_card_target_picker.item_count
		_combat_card_target_picker.add_item(_combat_target_name(active, characters, target_id))
		_combat_card_target_picker.set_item_metadata(index, target_id)
	_combat_card_target_picker.disabled = _combat_card_target_picker.item_count == 0
	_combat_play_card_action.disabled = not bool(option.get("playable", false)) or _combat_card_target_picker.item_count == 0


func _refresh_combat_base_targets(active: Dictionary, characters: Dictionary) -> void:
	_combat_base_target_picker.clear()
	var option: Dictionary = (((active.get("action_options", {}) as Dictionary).get("base_commands", {}) as Dictionary).get(_selected_combat_base_actor_id, {}))
	for target_id_value in option.get("target_ids", []):
		var target_id := String(target_id_value)
		var index := _combat_base_target_picker.item_count
		_combat_base_target_picker.add_item(_combat_target_name(active, characters, target_id))
		_combat_base_target_picker.set_item_metadata(index, target_id)
	_combat_base_target_picker.disabled = _combat_base_target_picker.item_count == 0
	_combat_use_base_action.disabled = not bool(option.get("playable", false)) or _combat_base_target_picker.item_count == 0


func _refresh_combat_character_controls(active: Dictionary) -> void:
	var cards: Dictionary = active.get("character_cards", {})
	var card: Dictionary = cards.get(_selected_character_card_id, {})
	var phase := String(active.get("phase", ""))
	var setup := phase == "setup"
	var player_turn := phase == "player_turn"
	var deployment_state := String(card.get("deployment_state", ""))
	_combat_character_picker.disabled = not setup and not player_turn
	_combat_row_picker.disabled = (not setup and not player_turn) or deployment_state not in ["reserve", "deployed"]
	_combat_deploy_action.text = "部署" if deployment_state == "reserve" else "换位"
	_combat_deploy_action.disabled = (
		(not setup and not player_turn)
		or deployment_state not in ["reserve", "deployed"]
		or (player_turn and deployment_state != "deployed")
	)
	_combat_withdraw_action.disabled = not setup or deployment_state != "deployed"
	var player_deployed := false
	for card_value in cards.values():
		if card_value is Dictionary and card_value.get("actor_id") == "player" and card_value.get("deployment_state") == "deployed":
			player_deployed = true
			break
	_combat_confirm_action.disabled = not setup or not player_deployed
	_combat_cancel_action.disabled = String(active.get("phase", "")) not in ["setup", "ready"]
	_combat_start_action.disabled = String(active.get("phase", "")) != "ready"
	_combat_end_round_action.disabled = String(active.get("phase", "")) != "player_turn"


func _select_combat_task(index: int) -> void:
	_selected_combat_task_id = String(_combat_task_picker.get_item_metadata(index))
	_refresh_combat_page()


func _select_combat_character(index: int) -> void:
	_selected_character_card_id = String(_combat_character_picker.get_item_metadata(index))
	var combat: Dictionary = SimulationBridge.campus_snapshot.get("combat", {})
	var active_value: Variant = combat.get("active_battle")
	if active_value is Dictionary:
		var active: Dictionary = active_value
		var card: Dictionary = (active.get("character_cards", {}) as Dictionary).get(_selected_character_card_id, {})
		var preferred := String(card.get("preferred_row", "middle"))
		for index_value in range(_combat_row_picker.item_count):
			if String(_combat_row_picker.get_item_metadata(index_value)) == preferred:
				_combat_row_picker.select(index_value)
				break
		_refresh_combat_character_controls(active)


func _select_combat_card(index: int) -> void:
	_selected_combat_card_id = String(_combat_card_picker.get_item_metadata(index))
	var active: Dictionary = (SimulationBridge.campus_snapshot.get("combat", {}) as Dictionary).get("active_battle", {})
	if not active.is_empty():
		_refresh_combat_card_targets(active, active.get("character_cards", {}))


func _select_combat_base_command(index: int) -> void:
	_selected_combat_base_actor_id = String(_combat_base_picker.get_item_metadata(index))
	var active: Dictionary = (SimulationBridge.campus_snapshot.get("combat", {}) as Dictionary).get("active_battle", {})
	if not active.is_empty():
		_refresh_combat_base_targets(active, active.get("character_cards", {}))


func _start_combat_preparation() -> void:
	_combat_feedback.text = "正在建立战斗准备……"
	SimulationBridge.operate_campus_combat(
		"START_BATTLE_PREPARATION", {"task_id": _selected_combat_task_id}
	)


func _active_combat_parameters() -> Dictionary:
	var combat: Dictionary = SimulationBridge.campus_snapshot.get("combat", {})
	var active_value: Variant = combat.get("active_battle")
	if not active_value is Dictionary:
		return {}
	var active: Dictionary = active_value
	return {
		"battle_id": String(active.get("battle_id", "")),
		"expected_battle_revision": int(active.get("revision", 0)),
	}


func _deploy_or_reposition_character() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty() or _combat_row_picker.selected < 0:
		return
	var active: Dictionary = (SimulationBridge.campus_snapshot.get("combat", {}) as Dictionary).get("active_battle", {})
	var card: Dictionary = (active.get("character_cards", {}) as Dictionary).get(_selected_character_card_id, {})
	parameters["character_card_instance_id"] = _selected_character_card_id
	parameters["destination_row"] = String(_combat_row_picker.get_item_metadata(_combat_row_picker.selected))
	var action_id := "DEPLOY_COMBAT_CHARACTER" if card.get("deployment_state") == "reserve" else "REPOSITION_COMBAT_CHARACTER"
	_combat_feedback.text = "正在更新三排阵型……"
	SimulationBridge.operate_campus_combat(action_id, parameters)


func _withdraw_combat_character() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty():
		return
	parameters["character_card_instance_id"] = _selected_character_card_id
	_combat_feedback.text = "正在撤回人物牌……"
	SimulationBridge.operate_campus_combat("WITHDRAW_COMBAT_CHARACTER", parameters)


func _confirm_combat_deployment() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty():
		return
	_combat_feedback.text = "正在锁定阵型……"
	SimulationBridge.operate_campus_combat("CONFIRM_BATTLE_DEPLOYMENT", parameters)


func _start_card_combat() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty():
		return
	_combat_feedback.text = "正在洗入个人牌组并抽取首轮手牌……"
	SimulationBridge.operate_campus_combat("START_CARD_COMBAT", parameters)


func _end_combat_round() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty():
		return
	_combat_feedback.text = "正在弃置未保留手牌并进入下一轮……"
	SimulationBridge.operate_campus_combat("END_COMBAT_ROUND", parameters)


func _play_combat_card() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty() or _combat_card_target_picker.selected < 0:
		return
	parameters["card_instance_id"] = _selected_combat_card_id
	parameters["target_ids"] = [String(
		_combat_card_target_picker.get_item_metadata(_combat_card_target_picker.selected)
	)]
	_combat_feedback.text = "正在结算指令牌……"
	SimulationBridge.operate_campus_combat("PLAY_COMBAT_CARD", parameters)


func _use_combat_base_command() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty() or _combat_base_target_picker.selected < 0:
		return
	parameters["source_actor_id"] = _selected_combat_base_actor_id
	parameters["target_ids"] = [String(
		_combat_base_target_picker.get_item_metadata(_combat_base_target_picker.selected)
	)]
	_combat_feedback.text = "正在执行基础指令……"
	SimulationBridge.operate_campus_combat("USE_COMBAT_BASE_COMMAND", parameters)


func _cancel_combat_preparation() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty():
		return
	_combat_feedback.text = "正在取消战斗准备……"
	SimulationBridge.operate_campus_combat("CANCEL_BATTLE_PREPARATION", parameters)


func _on_combat_operation_completed(
	success: bool, result: Dictionary, _action_id: String, _battle_id: String
) -> void:
	var command_result: Dictionary = result.get("result", {})
	_combat_feedback.text = String(command_result.get("message", result.get("error", "战斗准备操作失败")))
	_combat_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	_refresh_combat_page()


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
	_combat_root.visible = false
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
		_refresh_clock()
	get_tree().paused = value


func _refresh_clock() -> void:
	var clock: Dictionary = SimulationBridge.campus_snapshot.get("clock", {})
	_time_label.text = "Day %d · %s" % [int(clock.get("day", 1)), SimulationBridge.phase_display_name(String(clock.get("phase", "morning")))]


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
