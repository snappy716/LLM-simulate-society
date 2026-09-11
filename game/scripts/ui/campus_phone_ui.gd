extends CanvasLayer

const UI_TEXT = preload("res://scripts/ui/campus_ui_text.gd")
const COMBAT_ITEM_PANEL = preload("res://scripts/ui/campus_combat_item_panel.gd")
const KIT = preload("res://scripts/ui/campus_ui_kit.gd")
const FEED = preload("res://scripts/ui/campus_activity_feed.gd")

const APPS := [
	{"id": "settings", "name": "接口设置"},
	{"id": "saves", "name": "存读档"},
	{"id": "messages", "name": "校园通讯"},
	{"id": "agenda", "name": "日程与约定"},
	{"id": "assistance", "name": "互助约定"},
	{"id": "courses", "name": "课程平台"},
	{"id": "album", "name": "校园相册"},
	{"id": "notes", "name": "调查笔记"},
	{"id": "market", "name": "校园商城"},
	{"id": "trade", "name": "当面交易"},
	{"id": "wallet", "name": "电子钱包"},
	{"id": "health", "name": "健康档案"},
	{"id": "clubs", "name": "社团中心"},
	{"id": "party", "name": "行动小队"},
	{"id": "combat", "name": "夜战部署"},
	{"id": "forums", "name": "双层论坛"},
]

var _overlay: ColorRect
var _phone_panel: PanelContainer
var _home: Control
var _combat_pending := false
var _contact_check_picker: OptionButton
var _contact_check_button: Button
var _contact_check_target_id := ""
var _message_pending := ""
var _message_pending_target := ""
var _message_sent_text := ""
var _social_pending := {"forum": "", "club": "", "party": ""}
var _home_search: LineEdit
var _home_scroll: ScrollContainer
var _home_sections: Array[Control] = []
var _home_buttons: Array[Button] = []
var _home_empty: Label
var _home_brief: Button
var _feed_root: VBoxContainer
var _contact_search: LineEdit
var _message_drafts: Dictionary = {}
var _app_page: VBoxContainer
var _app_scroll: ScrollContainer
var _back_button: Button
var _close_button: Button
var _app_title: Label
var _content: RichTextLabel
var _inventory_root: VBoxContainer
var _investigation_root: VBoxContainer
var _growth_root: VBoxContainer
var _agenda_root: VBoxContainer
var _hud_tabs: HBoxContainer
var _character_summary: Label
var _relationships_root: VBoxContainer
var _time_root: VBoxContainer
var _character_tab := "status"
var _assistance_root: VBoxContainer
var _trade_root: VBoxContainer
var _health_root: VBoxContainer
var _save_root: VBoxContainer
var _time_label: Label
var _connection_label: Label
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
var _forum_situations: RichTextLabel
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
var _departure_picker: OptionButton
var _departure_reserve: Button
var _departure_cancel: Button
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
var _combat_retreat_action: Button
var _combat_card_picker: OptionButton
var _combat_card_target_picker: OptionButton
var _combat_play_card_action: Button
var _combat_base_picker: OptionButton
var _combat_base_target_picker: OptionButton
var _combat_use_base_action: Button
var _combat_feedback: Label
var _combat_items: VBoxContainer
var _combat_insights: VBoxContainer
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
var _support_appointment_panel: VBoxContainer


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("campus_phone_ui")
	_build_ui()
	call_deferred("_prepare_readable_forms", _app_page)
	SimulationBridge.connection_state_changed.connect(_refresh_connection)
	_refresh_connection(SimulationBridge.connected, "")
	SimulationBridge.campus_snapshot_updated.connect(_on_campus_snapshot_updated)
	SimulationBridge.campus_task_operation_completed.connect(_on_task_operation_completed)
	SimulationBridge.campus_club_operation_completed.connect(_on_club_operation_completed)
	SimulationBridge.campus_party_operation_completed.connect(_on_party_operation_completed)
	SimulationBridge.campus_combat_operation_completed.connect(_on_combat_operation_completed)
	SimulationBridge.campus_phone_message_completed.connect(_on_phone_message_completed)
	SimulationBridge.campus_social_proposal_completed.connect(_on_social_proposal_completed)
	SimulationBridge.campus_social_proposal_response_completed.connect(_on_social_proposal_response_completed)


func _unhandled_input(event: InputEvent) -> void:
	if InterfaceSettings.is_open():
		return
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
	_phone_panel = phone
	phone.set_anchors_preset(Control.PRESET_CENTER)
	phone.theme_type_variation = &"CampusPhone"
	_overlay.add_child(phone)
	_overlay.resized.connect(_fit_shell)
	call_deferred("_fit_shell")
	var margin := MarginContainer.new()
	for side in ["left", "top", "right", "bottom"]:
		margin.add_theme_constant_override("margin_%s" % side, 14)
	phone.add_child(margin)
	var column := VBoxContainer.new()
	margin.add_child(column)
	var status_bar := HBoxContainer.new()
	_time_label = Label.new()
	status_bar.add_child(_time_label)
	var time_menu := Button.new()
	time_menu.name = "TimeAndCamera"
	time_menu.text = "时间与镜头"
	time_menu.pressed.connect(func(): _open_app("time", "时间与镜头"))
	status_bar.add_child(time_menu)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	status_bar.add_child(spacer)
	var status := Label.new()
	_connection_label = status
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
	var hint := Button.new()
	_close_button = hint
	hint.text = "T 关闭手机"
	hint.icon = preload("res://assets/ui/kenney_game_icons/cross.png")
	hint.expand_icon = true
	hint.add_theme_constant_override("icon_max_width", 16)
	hint.pressed.connect(_set_open.bind(false))
	column.add_child(hint)


func _fit_shell() -> void:
	# A desktop terminal, not a narrow physical-phone imitation. Logical canvas
	# dimensions keep the same readable controls on Windows and macOS.
	var available := _overlay.size
	var extent := Vector2(minf(840, available.x - 32), minf(660, available.y - 32))
	_phone_panel.offset_left = -extent.x / 2
	_phone_panel.offset_right = extent.x / 2
	_phone_panel.offset_top = -extent.y / 2
	_phone_panel.offset_bottom = extent.y / 2


func _build_home() -> Control:
	var home := VBoxContainer.new()
	var headline := HBoxContainer.new()
	home.add_child(headline)
	var heading := Label.new()
	heading.text = "校园终端"
	heading.add_theme_font_size_override("font_size", 22)
	headline.add_child(heading)
	_home_brief = KIT.button("通知与校园动态 ›", func(): _open_app("feed", "校园动态与通知"))
	_home_brief.custom_minimum_size.y = 28
	_home_brief.add_theme_font_size_override("font_size", 14)
	_home_brief.name = "NotificationSummary"
	headline.add_child(_home_brief)
	_home_search = LineEdit.new()
	_home_search.placeholder_text = "查找功能：聊天、背包、任务…"
	_home_search.text_changed.connect(_filter_home)
	home.add_child(_home_search)
	_home_scroll = ScrollContainer.new()
	_home_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_home_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_home_scroll.follow_focus = true
	home.add_child(_home_scroll)
	var body := HBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 12)
	_home_scroll.add_child(body)
	for group in preload("res://scripts/ui/campus_phone_catalog.gd").GROUPS:
		var section := VBoxContainer.new()
		section.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		body.add_child(section)
		_home_sections.append(section)
		var label := Label.new()
		label.text = group.title
		label.add_theme_color_override("font_color", KIT.BLUE)
		section.add_child(label)
		var grid := GridContainer.new()
		grid.columns = 1
		grid.add_theme_constant_override("h_separation", 8)
		grid.add_theme_constant_override("v_separation", 6)
		section.add_child(grid)
		for entry in group.entries:
			for app in APPS:
				if app.id != entry.id:
					continue
				var button := Button.new()
				button.text = "%s\n%s" % [app.name, entry.caption]
				button.icon = load("res://assets/ui/kenney_game_icons/%s.png" % entry.icon)
				button.expand_icon = true
				button.add_theme_constant_override("icon_max_width", 26)
				button.add_theme_font_size_override("font_size", 14)
				button.custom_minimum_size = Vector2(152, 42)
				button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
				button.tooltip_text = "%s · %s" % [app.name, entry.caption]
				button.set_meta("search", app.name + entry.caption + entry.keywords)
				button.set_meta("app_id", app.id)
				button.pressed.connect(_open_app.bind(String(app.id), String(app.name)))
				grid.add_child(button)
				_home_buttons.append(button)
	_home_empty = Label.new()
	_home_empty.text = "没有匹配的功能，请换个关键词。"
	_home_empty.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_home_empty.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_home_empty.visible = false
	body.add_child(_home_empty)
	return home


func _filter_home(query: String) -> void:
	var found := false
	for button in _home_buttons:
		button.visible = query.strip_edges().is_empty() or String(button.get_meta("search")).containsn(query.strip_edges())
		found = found or button.visible
	for section in _home_sections:
		section.visible = false
		for button in section.get_child(1).get_children():
			section.visible = section.visible or button.visible
	_home_empty.visible = not found
	_home_scroll.scroll_vertical = 0


func _build_app_page() -> VBoxContainer:
	var page := VBoxContainer.new()
	var nav := HBoxContainer.new()
	var back := Button.new()
	_back_button = back
	back.text = "‹ 返回"
	back.icon = preload("res://assets/ui/kenney_game_icons/arrowLeft.png")
	back.expand_icon = true
	back.add_theme_constant_override("icon_max_width", 16)
	back.pressed.connect(_show_home)
	nav.add_child(back)
	_app_title = Label.new()
	_app_title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_app_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_app_title.add_theme_font_size_override("font_size", 22)
	nav.add_child(_app_title)
	page.add_child(nav)
	_app_scroll = ScrollContainer.new()
	_app_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_app_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_app_scroll.follow_focus = true
	page.add_child(_app_scroll)
	var body := VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_app_scroll.add_child(body)
	_feed_root = FEED.new()
	_feed_root.visible = false
	_feed_root.navigate.connect(_navigate_feed)
	body.add_child(_feed_root)
	_hud_tabs = HBoxContainer.new()
	_hud_tabs.visible = false
	body.add_child(_hud_tabs)
	for entry in [["status", "人物状态"], ["inventory", "随身物品"]]:
		var tab := Button.new()
		tab.text = entry[1]
		tab.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		tab.pressed.connect(func():
			_character_tab = entry[0]
			if _character_tab == "inventory" and _inventory_root.get("action_picker").selected == 0:
				_inventory_root.get("action_picker").select(2) # Start with owned items, not a shop listing.
			_open_app("character", "人物与物品")
		)
		_hud_tabs.add_child(tab)
	_character_summary = Label.new()
	_character_summary.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_character_summary.visible = false
	body.add_child(_character_summary)
	_relationships_root = VBoxContainer.new()
	_relationships_root.visible = false
	body.add_child(_relationships_root)
	_relationships_root.add_child(preload("res://scripts/ui/campus_bond_panel.gd").new())
	_relationships_root.add_child(preload("res://scripts/ui/campus_outing_panel.gd").new())
	_time_root = VBoxContainer.new()
	_time_root.visible = false
	body.add_child(_time_root)
	var time_panel := preload("res://scenes/ui/campus_phase_debug_panel.tscn").instantiate()
	_time_root.add_child(time_panel)
	var camera_row := HBoxContainer.new()
	_time_root.add_child(camera_row)
	for multiplier in [1, 2, 3]:
		var zoom := Button.new()
		zoom.text = "镜头 %d×" % multiplier
		zoom.pressed.connect(func():
			var controller := get_tree().get_first_node_in_group("campus_art_camera")
			if controller != null: controller.call("set_zoom_multiplier", multiplier)
		)
		camera_row.add_child(zoom)
	_content = RichTextLabel.new()
	_content.bbcode_enabled = true
	_content.fit_content = true
	_content.scroll_active = false
	_content.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_content.add_theme_font_size_override("normal_font_size", 15)
	body.add_child(_content)
	_inventory_root = preload("res://scripts/ui/campus_inventory_panel.gd").new()
	_inventory_root.visible = false
	body.add_child(_inventory_root)
	_investigation_root = preload("res://scripts/ui/campus_investigation_panel.gd").new()
	_investigation_root.visible = false
	body.add_child(_investigation_root)
	_growth_root = preload("res://scripts/ui/campus_growth_panel.gd").new()
	_growth_root.visible = false
	body.add_child(_growth_root)
	var public_courses := Button.new()
	public_courses.name = "PublicCourses"
	public_courses.text = "查看课程、兼职与真实参与记录"
	public_courses.pressed.connect(func(): _open_app("agenda", "日程与约定"))
	_growth_root.add_child(public_courses)
	_agenda_root = preload("res://scripts/ui/campus_agenda_panel.gd").new()
	_agenda_root.visible = false
	body.add_child(_agenda_root)
	_agenda_root.connect("open_management", _open_app)
	_assistance_root = preload("res://scripts/ui/campus_assistance_panel.gd").new()
	_assistance_root.visible = false
	body.add_child(_assistance_root)
	_trade_root = preload("res://scripts/ui/campus_trade_panel.gd").new()
	_trade_root.visible = false
	body.add_child(_trade_root)
	_health_root = preload("res://scripts/ui/campus_health_panel.gd").new()
	_health_root.visible = false
	body.add_child(_health_root)
	_save_root = preload("res://scripts/ui/campus_save_panel.gd").new()
	_save_root.visible = false
	body.add_child(_save_root)
	_forum_root = _build_forum_page()
	_forum_root.visible = false
	_forum_root.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(_forum_root)
	_club_root = _build_club_page()
	_club_root.visible = false
	_club_root.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(_club_root)
	_party_root = _build_party_page()
	_party_root.visible = false
	_party_root.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(_party_root)
	_combat_root = _build_combat_page()
	_combat_root.visible = false
	_combat_root.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(_combat_root)
	_message_root = _build_message_page()
	_message_root.visible = false
	_message_root.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(_message_root)
	return page


func _build_message_page() -> VBoxContainer:
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 7)
	_contact_search = KIT.search("搜索已添加的联系人", func(_text): _refresh_message_page())
	root.add_child(_contact_search)
	_message_contact_picker = OptionButton.new()
	_message_contact_picker.item_selected.connect(_select_message_contact)
	root.add_child(_message_contact_picker)
	_support_appointment_panel = preload("res://scripts/ui/campus_support_appointment_panel.gd").new()
	root.add_child(_support_appointment_panel)
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
	_message_input.text_changed.connect(func(_text): _refresh_message_controls())
	composer.add_child(_message_input)
	_message_send_action = Button.new()
	_message_send_action.text = "发送"
	_message_send_action.pressed.connect(_send_phone_message)
	composer.add_child(_message_send_action)
	root.add_child(composer)
	var check_row := HBoxContainer.new()
	_contact_check_picker = OptionButton.new()
	_contact_check_picker.item_selected.connect(func(_index): _refresh_message_thread())
	_contact_check_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	check_row.add_child(_contact_check_picker)
	_contact_check_button = Button.new()
	_contact_check_button.text = "请人实地留意"
	_contact_check_button.pressed.connect(_request_contact_check)
	check_row.add_child(_contact_check_button)
	root.add_child(check_row)
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
	var departure_row := HBoxContainer.new()
	_departure_picker = OptionButton.new()
	_departure_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	departure_row.add_child(_departure_picker)
	_departure_reserve = Button.new()
	_departure_reserve.text = "预约出击"
	_departure_reserve.pressed.connect(_operate_departure.bind(false))
	departure_row.add_child(_departure_reserve)
	_departure_cancel = Button.new()
	_departure_cancel.text = "取消预约"
	_departure_cancel.pressed.connect(_operate_departure.bind(true))
	departure_row.add_child(_departure_cancel)
	root.add_child(departure_row)
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
	var workspace := HBoxContainer.new()
	workspace.add_theme_constant_override("separation", 20)
	root.add_child(workspace)
	var formation := VBoxContainer.new()
	formation.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	formation.size_flags_stretch_ratio = 1.0
	workspace.add_child(formation)
	var commands := VBoxContainer.new()
	commands.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	commands.size_flags_stretch_ratio = 1.0
	workspace.add_child(commands)
	_combat_formation_detail = RichTextLabel.new()
	_combat_formation_detail.bbcode_enabled = true
	_combat_formation_detail.fit_content = true
	_combat_formation_detail.scroll_active = false
	_combat_formation_detail.custom_minimum_size.y = 160
	_combat_formation_detail.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	_combat_formation_detail.add_theme_font_size_override("normal_font_size", 14)
	formation.add_child(_combat_formation_detail)
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
	formation.add_child(selection_row)
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
	formation.add_child(formation_actions)
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
	formation.add_child(confirmation_actions)
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
	commands.add_child(round_actions)
	_combat_retreat_action = Button.new()
	_combat_retreat_action.text = "承受追击并主动撤退"
	_combat_retreat_action.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_combat_retreat_action.pressed.connect(_retreat_from_combat)
	commands.add_child(_combat_retreat_action)
	_combat_hand_detail = RichTextLabel.new()
	_combat_hand_detail.bbcode_enabled = true
	_combat_hand_detail.fit_content = true
	_combat_hand_detail.scroll_active = false
	_combat_hand_detail.custom_minimum_size = Vector2(0, 92)
	_combat_hand_detail.add_theme_font_size_override("normal_font_size", 13)
	commands.add_child(_combat_hand_detail)
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
	commands.add_child(card_action_row)
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
	commands.add_child(base_action_row)
	_combat_items = COMBAT_ITEM_PANEL.new()
	_combat_items.use_requested.connect(_use_combat_item)
	commands.add_child(_combat_items)
	_combat_insights = preload("res://scripts/ui/campus_knowledge_insight_panel.gd").new()
	_combat_insights.use_requested.connect(func(selection):
		var parameters := _active_combat_parameters()
		if not parameters.is_empty():
			parameters.merge(selection)
			_combat_feedback.text = "正在运用知识洞察……"
			_send_combat_operation("USE_KNOWLEDGE_INSIGHT", parameters)
	)
	commands.add_child(_combat_insights)
	_combat_feedback = Label.new()
	_combat_feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_combat_feedback.add_theme_color_override("font_color", Color("e0b86a"))
	root.add_child(_combat_feedback)
	return root


func _build_forum_page() -> VBoxContainer:
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 8)
	root.add_child(KIT.button("校园动态 · 查看真实委托进展 ›", func(): _open_app("feed", "校园动态与通知")))
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
	var opportunities := Button.new()
	opportunities.text = "公开校园活动与参与记录"
	opportunities.pressed.connect(func(): _open_app("agenda", "日程与约定"))
	root.add_child(opportunities)
	_forum_situations = RichTextLabel.new()
	_forum_situations.custom_minimum_size = Vector2(0, 100)
	_forum_situations.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_forum_situations.bbcode_enabled = false
	_forum_situations.add_theme_font_size_override("normal_font_size", 14)
	_forum_situations.visible = false
	root.add_child(_forum_situations)

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
	_app_scroll.scroll_vertical = 0
	_feed_root.visible = app_id == "feed"
	if _feed_root.visible: _feed_root.call("refresh")
	if app_id == "settings":
		_set_open(false)
		InterfaceSettings.open_settings()
		return
	_app_title.text = app_name
	var is_character := app_id == "character"
	_hud_tabs.visible = is_character
	_character_summary.visible = is_character and _character_tab == "status"
	if _character_summary.visible: _refresh_character_summary()
	_relationships_root.visible = app_id == "relationships"
	_time_root.visible = app_id == "time"
	var is_save := app_id == "saves"
	_save_root.visible = is_save
	if is_save:
		_save_root.call("refresh")
	var is_forum := app_id == "forums"
	var is_club := app_id == "clubs"
	var is_party := app_id == "party"
	var is_combat := app_id == "combat"
	var is_message := app_id == "messages"
	var is_inventory := app_id == "market" or (is_character and _character_tab == "inventory")
	var is_investigation := app_id == "notes"
	var is_growth := app_id in ["courses", "cards"]
	var is_agenda := app_id == "agenda"
	_agenda_root.visible = is_agenda
	if is_agenda:
		_agenda_root.call("refresh")
	var is_assistance := app_id == "assistance"
	_assistance_root.visible = is_assistance
	if is_assistance:
		_assistance_root.call("refresh")
	_growth_root.visible = is_growth
	if is_growth:
		_growth_root.call("set_cards_only", app_id == "cards")
		_growth_root.call("refresh")
	_investigation_root.visible = is_investigation
	if is_investigation:
		_investigation_root.call("refresh")
	var is_trade := app_id == "trade"
	_trade_root.visible = is_trade
	if is_trade:
		_trade_root.call("refresh")
	var is_health := app_id == "health" or (is_character and _character_tab == "status")
	_health_root.visible = is_health
	if is_health:
		_health_root.call("refresh")
	_inventory_root.visible = is_inventory
	if is_inventory:
		_inventory_root.call("refresh")
	_content.visible = not is_save and not is_forum and not is_club and not is_party and not is_combat and not is_message and not is_inventory and not is_health and not is_trade and not is_investigation and not is_growth and not is_assistance and not is_agenda
	if app_id in ["relationships", "time", "feed"]: _content.visible = false
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
		return "[b]第 %d 天 · %s[/b]\n当前计划：%s\n地点：%s\n主要行动剩余：%d\n\n[b]学院能力 · 心理学院[/b]\n%s\n\n[color=#9aa8bd]能力同时用于表世界检定，并生成角色绑定的战斗卡牌。[/color]" % [int(clock.get("day", 1)), SimulationBridge.phase_display_name(String(clock.get("phase", "morning"))), UI_TEXT.activity_name(String(plan.get("activity_id", ""))), (campus.get("places", {}) as Dictionary).get(String(plan.get("location_id", "")), {}).get("name", "未安排"), int((player.get("action_budget", {}) as Dictionary).get("major_remaining", 0)), _ability_lines(player.get("abilities", []))]
	if app_id == "album":
		var presentation := get_node("/root/CampusPresentation")
		var current_map: Dictionary = presentation.call("get_map")
		return "[b]当前场景[/b]\n%s\n\n已接入校园正式候选场景：%d 张。\n按 M 可查看和切换校园区域。\n\n开发联调素材：正式发布前需去除真实校名/品牌并补齐授权记录。" % [current_map.get("name", "未知"), (presentation.call("all_maps") as Array).size()]
	if app_id == "notes":
		var activity: Dictionary = player.get("current_activity", {})
		return "[b]当前位置[/b]\n%s\n\n[b]最近活动[/b]\n%s\n%s" % [place.get("name", place_id), UI_TEXT.activity_name(String(activity.get("activity_id", ""))), UI_TEXT.activity_status(String(activity.get("status", "")))]
	if app_id == "wallet":
		return "[b]账户概览[/b]\n\n校园生活资金：%d 元\n\n余额与活动、购物使用同一账户。\n打开校园商城可查看背包、到店交易或操作物品。" % int(player.get("wealth", 0))
	if app_id == "health":
		return "[b]需求[/b]\n%s\n\n[b]情绪[/b]\n%s" % [_dictionary_lines(player.get("needs", {})), _dictionary_lines(player.get("emotions", {}))]
	if app_id == "market":
		return "背包与校园商店已接入校园权威状态；请到店交易。"
	return "[b]校园通讯[/b]\n\n联系人和持久聊天记录已经接入。"


func _refresh_message_page() -> void:
	if not _selected_message_contact_id.is_empty():
		_message_drafts[_selected_message_contact_id] = _message_input.text
	var messaging: Dictionary = SimulationBridge.campus_snapshot.get("messaging", {})
	var contacts: Array = messaging.get("contacts", [])
	var previous := _selected_message_contact_id
	_message_contact_picker.clear()
	var selected_index := 0
	for contact in contacts:
		if not contact is Dictionary:
			continue
		var contact_id := String(contact.get("actor_id", ""))
		if not _contact_search.text.is_empty() and not String(contact.get("display_name", "")).containsn(_contact_search.text): continue
		var unread := int(contact.get("unread_count", 0))
		var prefix := "[%d条未读] " % unread if unread > 0 else ""
		var index := _message_contact_picker.item_count
		_message_contact_picker.add_item("%s%s" % [prefix, contact.get("display_name", contact_id)])
		_message_contact_picker.set_item_metadata(index, contact_id)
		if contact_id == previous:
			selected_index = index
	if _message_contact_picker.item_count == 0:
		_selected_message_contact_id = ""
		_message_log.text = "没有匹配的联系人，请调整搜索。" if not _contact_search.text.is_empty() else ("暂无联系人。请先在校园结识他人并交换联系方式。" if SimulationBridge.campus_snapshot.has("messaging") else "联系人数据尚未同步。")
		_message_input.text = ""
		_message_send_action.disabled = true
		_message_proposal_action.disabled = true
		_refresh_incoming_proposals()
		_refresh_message_controls()
		return
	_message_contact_picker.select(selected_index)
	_selected_message_contact_id = String(_message_contact_picker.get_item_metadata(selected_index))
	_message_input.text = String(_message_drafts.get(_selected_message_contact_id, ""))
	_message_send_action.disabled = false
	_message_proposal_action.disabled = false
	_refresh_message_thread()
	_refresh_incoming_proposals()
	_refresh_message_controls()


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
	_incoming_proposal_accept.tooltip_text = "回应所选请求。" if has_pending else "目前没有待处理请求。"
	_incoming_proposal_decline.tooltip_text = _incoming_proposal_accept.tooltip_text
	if not _message_pending.is_empty():
		_lock_waiting_controls(_message_root)


func _respond_incoming_proposal(accepted: bool) -> void:
	if _incoming_proposal_picker.selected < 0 or not _message_pending.is_empty():
		return
	var proposal_id := String(_incoming_proposal_picker.get_item_metadata(_incoming_proposal_picker.selected))
	if proposal_id.is_empty():
		return
	_message_pending = "response"
	_message_pending_target = proposal_id
	_refresh_message_controls()
	_incoming_proposal_accept.disabled = true
	_incoming_proposal_decline.disabled = true
	_message_feedback.text = "正在记录你的决定……"
	SimulationBridge.respond_campus_social_proposal(proposal_id, accepted)


func _on_social_proposal_response_completed(
	success: bool, result: Dictionary, _proposal_id: String
) -> void:
	if _message_pending == "response" and _message_pending_target == _proposal_id:
		_message_pending = ""
	_message_feedback.text = UI_TEXT.operation_feedback(success, result)
	_message_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	_refresh_message_page()


func _refresh_message_thread() -> void:
	_support_appointment_panel.call("refresh_contact", _selected_message_contact_id)
	var messaging: Dictionary = SimulationBridge.campus_snapshot.get("messaging", {})
	var threads: Dictionary = messaging.get("threads", {})
	var thread: Dictionary = threads.get(_selected_message_contact_id, {})
	var selected_point := ""
	if _contact_check_target_id == _selected_message_contact_id and _contact_check_picker.selected >= 0:
		selected_point = String(_contact_check_picker.get_item_metadata(_contact_check_picker.selected))
	_contact_check_target_id = _selected_message_contact_id
	var check_options: Array = messaging.get("check_options_by_contact", {}).get(_selected_message_contact_id, messaging.get("check_points", []))
	_contact_check_picker.clear()
	for point in check_options:
		var point_label := String(point.get("name", "公共会面点"))
		if point.get("lead") is Dictionary: point_label += " · 有已知记录"
		if not bool(point.get("open_now", true)): point_label += " · 待开放"
		_contact_check_picker.add_item(point_label)
		_contact_check_picker.set_item_metadata(_contact_check_picker.item_count - 1, point.get("location_id", ""))
		if point.get("location_id", "") == selected_point:
			_contact_check_picker.select(_contact_check_picker.item_count - 1)
	_contact_check_button.disabled = String(thread.get("contact_status", {}).get("status", "")) != "awaiting" or not _message_pending.is_empty()
	_contact_check_button.tooltip_text = "基于本人未回应记录，请人在所选公共地点留意；不代表确认失踪。"
	var lines: Array[String] = []
	if _contact_check_picker.selected >= 0 and _contact_check_picker.selected < check_options.size():
		var option: Dictionary = check_options[_contact_check_picker.selected]
		_contact_check_button.disabled = _contact_check_button.disabled or not bool(option.get("available", true))
		lines.append("[color=#91a4bc]寻访选择依据：%s[/color]" % option.get("basis", "公开会面点，不代表对方位置。"))
		if not bool(option.get("available", true)):
			lines.append("[color=#91a4bc]本次联系经历已有待处理/已见到的寻访，或此点已核对。[/color]")
	var contact_status: Dictionary = thread.get("contact_status", {})
	match String(contact_status.get("status", "")):
		"awaiting":
			lines.append("[color=#d9bc83]已有 %d 个时段尝试联系，暂未收到回应。尚不能据此确认失踪或原因。[/color]" % int(contact_status.get("distinct_phases", 1)))
		"contact_resumed":
			lines.append("[color=#91a4bc]对方已恢复联系；不代表此前的问题或委托已经解决。[/color]")
		"record_expired":
			lines.append("[color=#91a4bc]先前未回应消息已超出记录保留范围，尚未确认联系恢复。[/color]")
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
	if not _selected_message_contact_id.is_empty(): _message_drafts[_selected_message_contact_id] = _message_input.text
	_selected_message_contact_id = String(_message_contact_picker.get_item_metadata(index))
	_message_input.text = String(_message_drafts.get(_selected_message_contact_id, ""))
	_message_feedback.text = ""
	_refresh_message_thread()


func _send_phone_message() -> void:
	_send_phone_message_from_input(_message_input.text)


func _request_contact_check() -> void:
	if not _message_pending.is_empty() or _contact_check_picker.selected < 0:
		return
	_message_pending = "inquiry"
	_message_pending_target = _selected_message_contact_id
	_contact_check_button.disabled = true
	_message_feedback.text = "正在发布公共地点寻访……"
	SimulationBridge.operate_campus_message("REQUEST_CONTACT_CHECK", _selected_message_contact_id, String(_contact_check_picker.get_item_metadata(_contact_check_picker.selected)))


func _send_phone_message_from_input(text: String) -> void:
	if not _message_pending.is_empty():
		return
	var cleaned := text.strip_edges()
	if cleaned.is_empty() or _selected_message_contact_id.is_empty():
		_message_feedback.text = "请输入要发送的内容。"
		return
	_message_pending = "send"
	_message_pending_target = _selected_message_contact_id
	_message_sent_text = cleaned
	_refresh_message_controls()
	_message_feedback.text = "正在发送……"
	_message_send_action.disabled = true
	SimulationBridge.operate_campus_message(
		"SEND_PHONE_MESSAGE", _selected_message_contact_id, cleaned
	)


func _on_phone_message_completed(
	success: bool, result: Dictionary, action_id: String, target_id: String
) -> void:
	var own_send := action_id == "SEND_PHONE_MESSAGE" and _message_pending == "send" and _message_pending_target == target_id
	if action_id == "REQUEST_CONTACT_CHECK" and _message_pending == "inquiry" and _message_pending_target == target_id:
		_message_pending = ""
	if own_send:
		_message_pending = ""
		if success and String(_message_drafts.get(target_id, "")).strip_edges() == _message_sent_text:
			_message_drafts.erase(target_id)
	if target_id != _selected_message_contact_id:
		_refresh_message_page()
		return
	if action_id in ["SEND_PHONE_MESSAGE", "REQUEST_CONTACT_CHECK"]:
		_message_feedback.text = UI_TEXT.operation_feedback(success, result)
		_message_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
		if success and own_send and _message_input.text.strip_edges() == _message_sent_text:
			_message_input.clear()
	_message_send_action.disabled = false
	_refresh_message_page()


func _send_phone_proposal() -> void:
	if _selected_message_contact_id.is_empty() or _message_proposal_picker.selected < 0 or not _message_pending.is_empty():
		return
	var proposal_type := String(_message_proposal_picker.get_item_metadata(_message_proposal_picker.selected))
	_message_pending = "proposal"
	_message_pending_target = _selected_message_contact_id
	_refresh_message_controls()
	_message_feedback.text = "正在等待对方明确决定……"
	_message_proposal_action.disabled = true
	SimulationBridge.operate_campus_social_proposal(
		_selected_message_contact_id, proposal_type, "phone"
	)


func _on_social_proposal_completed(
	success: bool, result: Dictionary, target_id: String, proposal_type: String
) -> void:
	if _message_pending == "proposal" and _message_pending_target == target_id:
		_message_pending = ""
	var is_party_response := proposal_type == "party_invite" and (String(_social_pending.party) == target_id or target_id == _selected_party_candidate_id)
	if proposal_type == "party_invite" and String(_social_pending.party) == target_id:
		_social_pending.party = ""
	if is_party_response:
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
		_forum_access_note.text = "校园公开频道 · NPC 会陆续查看、考虑和接单。查看手机不消耗时段，其他人仍会继续浏览。"
	var notices: Array = (campus.get("forums", {}).get(_forum_channel, {}) as Dictionary).get("situations", [])
	var lines := PackedStringArray()
	for notice in notices:
		if notice is Dictionary:
			lines.append(String(notice.get("summary", "")))
	_forum_situations.text = "持续动态（可滚动）\n" + "\n".join(lines)
	_forum_situations.visible = not lines.is_empty()


func _show_forum_list() -> void:
	_selected_task_id = ""
	_forum_list_view.visible = true
	_forum_detail_view.visible = false
	_refresh_forum_list()


func _refresh_forum_list() -> void:
	if _forum_cards == null:
		return
	var scroll_position := _app_scroll.scroll_vertical
	var focused_task := ""
	var focused := get_viewport().gui_get_focus_owner()
	if focused != null and focused.has_meta("forum_task_id"):
		focused_task = String(focused.get_meta("forum_task_id"))
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
		card.set_meta("forum_task_id", String(task.get("task_id", "")))
		if String(task.get("task_id", "")) == focused_task:
			card.grab_focus()
	if visible_tasks.is_empty():
		var empty := Label.new()
		empty.text = "这个分类暂时没有任务。\nNPC 的浏览和接单仍会陆续更新，新委托随校园事件发布。"
		empty.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		empty.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		_forum_cards.add_child(empty)
	_app_scroll.set_deferred("scroll_vertical", scroll_position)


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
	if task.get("contact_inquiry", {}).get("status") == "withdrawn":
		return "联系恢复 · 已撤回（不计失约）"
	if bool(task.get("owned_by_player", false)) and String(task.get("state", "")) in ["locked", "in_progress"]:
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
	var fieldwork: Dictionary = task.get("fieldwork", {})
	var inquiry: Dictionary = task.get("contact_inquiry", {})
	var regional_choice: Dictionary = task.get("situation_choice", {}) if task.get("situation_choice") is Dictionary else {}
	if not regional_choice.is_empty() and regional_choice.get("actor_id") == task.get("assignee_id"):
		_forum_detail.text += "\n\n[b]承接者留言[/b]\n%s：%s" % [task.get("assignee_name", "校园用户"), regional_choice.get("reason", "")]
	if not inquiry.is_empty():
		var inquiry_status: String = {"open": "待实地核对", "observed": "已在指定点见到", "not_observed": "此次实地未见", "expired": "委托到期", "withdrawn": "联系恢复，已撤回"}.get(String(inquiry.get("status", "")), "待确认")
		_forum_detail.text += "\n\n[b]公共地点寻访[/b]\n%s\n状态：%s\n%s\n%s" % [inquiry.get("rule_note", ""), inquiry_status, inquiry.get("target_name", "承接后可查看具体对象"), inquiry.get("report", {}).get("summary", "") if inquiry.get("report") is Dictionary else ""]
		if inquiry.get("decision_basis") is Dictionary:
			_forum_detail.text += "\n选择依据：%s" % inquiry.decision_basis.get("summary", "")
	var night_site: Dictionary = task.get("night_site", {})
	var afterimage: Dictionary = task.get("afterimage", {})
	if not afterimage.is_empty():
		_forum_detail.text += "\n\n[b]月相残像 · 不是人物本身[/b]\n%s\n%s" % [afterimage.get("rule_note", ""), afterimage.get("outcome", "")]
	if not night_site.is_empty():
		_forum_detail.text += "\n\n[b]实际现场 · %s[/b]\n%s\n%s" % [night_site.get("label", ""), night_site.get("status", ""), night_site.get("rule_note", "")]
		if not String(night_site.get("victim_name", "")).is_empty():
			_forum_detail.text += "\n被困者：%s · 安全地点：%s" % [night_site.victim_name, night_site.destination_name]
	if not fieldwork.is_empty():
		_forum_detail.text += "\n\n[b]调查方法[/b]\n%s" % fieldwork.get("rule_note", "")
	var night_accessible := bool((SimulationBridge.campus_snapshot.get("night_world", {}) as Dictionary).get("night_forum_accessible", false))
	_forum_abandon_action.visible = owned and state in ["locked", "in_progress"]
	_forum_abandon_action.disabled = false
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
		if not fieldwork.is_empty() or not night_site.is_empty() or not inquiry.is_empty():
			at_location = player_location == task.get("scene_id")
		var phase: String = String((SimulationBridge.campus_snapshot.get("clock", {}) as Dictionary).get("phase", "morning"))
		var phase_allowed: bool = phase in task.get("allowed_phases", [])
		if requires_night:
			phase_allowed = phase in ["evening", "late_night"]
		if not at_location:
			_forum_primary_action.text = "请先前往：%s" % task.get("scene_name", "任务地点")
		elif not phase_allowed:
			_forum_primary_action.text = "当前时段无法执行"
		else:
			_forum_primary_action.text = "前往夜战部署 · 实际战斗结算" if requires_night else "完成当前目标"
			if not inquiry.is_empty():
				_forum_primary_action.text = "实地核对并报告 · 1 次主要行动"
			if not fieldwork.is_empty():
				_forum_primary_action.text = "提交实地报告 · 免费" if fieldwork.get("ready_to_report", false) else "打开调查笔记 · 深入搜查现场"
			elif night_site.get("can_follow_through", false):
				_forum_primary_action.text = "继续处理现场 · 不重打已胜战斗"
		_forum_primary_action.disabled = not at_location or not phase_allowed or (requires_night and not night_accessible)
	else:
		_forum_primary_action.text = _task_state_label(task)
		_forum_primary_action.disabled = true
	_forum_primary_action.tooltip_text = _forum_primary_action.text if _forum_primary_action.disabled else "提交后由系统检查任务锁、行动条件与资源。"
	_forum_abandon_action.tooltip_text = "释放自己的任务锁定，不保证之后仍可接回。"
	_lock_social_controls("forum", [_forum_primary_action, _forum_abandon_action])


func _perform_primary_task_action() -> void:
	if _forum_primary_action.disabled or not String(_social_pending.forum).is_empty():
		return
	var task: Dictionary = (SimulationBridge.campus_snapshot.get("tasks", {}) as Dictionary).get(_selected_task_id, {})
	if task.is_empty():
		return
	var state := String(task.get("state", ""))
	if bool(task.get("owned_by_player", false)) and state == "locked" and task.get("forum") == "night":
		var fieldwork: Dictionary = task.get("fieldwork", {})
		var site_ready: bool = (task.get("night_site", {}) as Dictionary).get("can_follow_through", false)
		if fieldwork.is_empty() and not site_ready:
			_open_app("combat", "夜战部署")
			return
		if not fieldwork.is_empty() and not fieldwork.get("ready_to_report", false):
			_open_app("notes", "调查笔记")
			return
	_social_pending.forum = _selected_task_id
	_refresh_forum_detail()
	_forum_feedback.text = "正在同步论坛状态……"
	if state in ["open", "viewed", "considering"]:
		SimulationBridge.operate_campus_task(
			"CLAIM_FORUM_TASK", _selected_task_id, int(task.get("lock_revision", 0))
		)
	elif bool(task.get("owned_by_player", false)) and state == "locked":
		if task.get("resolution_kind") == "contact_inquiry":
			SimulationBridge.operate_campus_task("CHECK_CONTACT_LOCATION", _selected_task_id, int(task.get("lock_revision", 0)))
		elif task.get("resolution_kind") == "field_recon":
			SimulationBridge.operate_campus_task("SUBMIT_FIELD_REPORT", _selected_task_id, int(task.get("lock_revision", 0)))
		elif (task.get("night_site", {}) as Dictionary).get("can_follow_through", false):
			SimulationBridge.operate_campus_task("RESOLVE_NIGHT_SITE", _selected_task_id, int(task.get("lock_revision", 0)))
		else:
			SimulationBridge.operate_campus_task("COMPLETE_FORUM_TASK", _selected_task_id)


func _abandon_selected_task() -> void:
	if _forum_abandon_action.disabled or not String(_social_pending.forum).is_empty():
		return
	_social_pending.forum = _selected_task_id
	_refresh_forum_detail()
	_forum_feedback.text = "正在释放任务锁定……"
	SimulationBridge.operate_campus_task("ABANDON_FORUM_TASK", _selected_task_id)


func _on_task_operation_completed(success: bool, result: Dictionary, _action_id: String, task_id: String) -> void:
	if String(_social_pending.forum) == task_id:
		_social_pending.forum = ""
	if task_id != _selected_task_id:
		_refresh_forum_detail()
		return
	_forum_feedback.text = UI_TEXT.operation_feedback(success, result)
	if not success:
		_forum_feedback.add_theme_color_override("font_color", Color("ee8174"))
	else:
		_forum_feedback.add_theme_color_override("font_color", Color("9bcf9b"))
	_refresh_forum_detail()


func _on_campus_snapshot_updated(_snapshot: Dictionary) -> void:
	if _character_summary.visible: _refresh_character_summary()
	if not _opened:
		return
	if _home.visible: _refresh_home_brief()
	if _feed_root.is_visible_in_tree(): _feed_root.call("refresh")
	# Passive forum traffic must not rebuild a hand of cards or a chat form
	# while the player is choosing a target or typing.
	if SimulationBridge.last_campus_update_kind == "social_pulse" and not _forum_root.visible:
		return
	_refresh_clock()
	if _forum_root.visible:
		if _selected_task_id.is_empty():
			_refresh_forum_list()
		else:
			var detail_scroll := _forum_detail.get_v_scroll_bar().value
			_refresh_forum_detail()
			_forum_detail.get_v_scroll_bar().set_deferred("value", detail_scroll)
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
		_club_picker.clear()
		_selected_club_id = ""
		_club_detail.text = "社团数据尚未同步。"
		_club_membership_action.disabled = true
		_club_activity_action.disabled = true
		_club_membership_action.tooltip_text = "暂无可用社团数据。"
		_club_activity_action.tooltip_text = "暂无可用社团数据。"
		return
	var previous := _selected_club_id
	_club_picker.disabled = false
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
		club.get("name", _selected_club_id), UI_TEXT.CLUB_TERMS.get(club.get("category", ""), "校园社团"),
		club.get("leader_name", "未知"), int(club.get("member_count", 0)),
		int(resources.get("current", 0)),
		int(resources.get("capacity", 0)), UI_TEXT.CLUB_TERMS.get(resources.get("resource_id", ""), "社团资源"),
		"；".join(schedule_lines), identity_text, admission_text, UI_TEXT.CLUB_TERMS.get(club.get("surface_skill", ""), "社团实践"),
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
	_club_membership_action.tooltip_text = "负责人不能直接退出社团。" if not membership.is_empty() and _club_membership_action.disabled else (admission_text if not bool(admission.get("eligible", false)) and membership.is_empty() else ("请先前往社团活动室。" if not at_club and membership.is_empty() else ("深夜不办理入社。" if not reception_open and membership.is_empty() else "提交申请后由系统检验资格。")))
	_club_activity_action.tooltip_text = "请先加入社团。" if membership.is_empty() else ("请先前往社团活动室。" if not at_club else ("当前不在该社团的活动时间。" if not bool(club.get("activity_open_now", false)) else ("本时段主要行动已用完。" if major_remaining <= 0 else "参加活动消耗 1 次主要行动。")))
	_lock_social_controls("club", [_club_membership_action, _club_activity_action, _club_picker])


func _perform_club_membership_action() -> void:
	if _club_membership_action.disabled or not String(_social_pending.club).is_empty():
		return
	_social_pending.club = _selected_club_id
	_refresh_club_detail()
	var club: Dictionary = (SimulationBridge.campus_snapshot.get("clubs", {}) as Dictionary).get(_selected_club_id, {})
	var action_id := "LEAVE_CAMPUS_CLUB" if club.get("viewer_membership") is Dictionary else "JOIN_CAMPUS_CLUB"
	_club_feedback.text = "正在提交社团申请……"
	SimulationBridge.operate_campus_club(action_id, _selected_club_id)


func _perform_club_activity() -> void:
	if _club_activity_action.disabled or not String(_social_pending.club).is_empty():
		return
	_social_pending.club = _selected_club_id
	_refresh_club_detail()
	_club_feedback.text = "正在结算社团活动……"
	SimulationBridge.operate_campus_club("CLUB_ACTIVITY", _selected_club_id)


func _on_club_operation_completed(success: bool, result: Dictionary, _action_id: String, club_id: String) -> void:
	if String(_social_pending.club) == club_id:
		_social_pending.club = ""
	if club_id != _selected_club_id:
		_refresh_club_page()
		return
	_club_feedback.text = UI_TEXT.operation_feedback(success, result)
	_club_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	_refresh_club_page()


func _refresh_party_page() -> void:
	var party: Dictionary = SimulationBridge.campus_snapshot.get("party", {})
	if party.is_empty():
		_departure_picker.clear()
		_departure_reserve.disabled = true
		_departure_cancel.disabled = true
		_party_candidate_picker.clear()
		_party_member_picker.clear()
		_selected_party_candidate_id = ""
		_selected_party_member_id = ""
		_party_detail.text = "队伍数据尚未同步。"
		_party_invite_action.disabled = true
		_party_dismiss_action.disabled = true
		_party_invite_action.tooltip_text = "暂无可用队伍数据。"
		_party_dismiss_action.tooltip_text = "暂无可用队伍数据。"
		return
	var band_names := {"fragile": "脆弱", "uncertain": "磨合中", "steady": "稳定", "cohesive": "默契"}
	var response_names := {"likely_accept": "较愿意", "uncertain": "态度不明", "likely_decline": "较可能拒绝"}
	var member_lines: Array[String] = []
	for member in party.get("members", []):
		if member is Dictionary:
			var status := "队长" if String(member.get("status", "")) == "leader" else "已承诺至第%d天" % int(member.get("commitment_until_day", 1))
			member_lines.append("• %s · %s" % [member.get("display_name", member.get("actor_id", "")), status])
			var departure: Dictionary = member.get("departure", {})
			if not departure.is_empty():
				member_lines.append("  出击预约：第 %d 天 · %s" % [int(departure.day), SimulationBridge.phase_display_name(String(departure.phase))])
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
	_party_candidate_picker.disabled = false
	_party_member_picker.disabled = false
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
	_party_invite_action.tooltip_text = "队伍已满。" if bool(party.get("is_full", false)) else ("暂无可邀请的人物。" if _selected_party_candidate_id.is_empty() else ("请先当面交换联系方式。" if not _selected_party_candidate_is_contact else "对方自主决定是否接受，不保证加入。"))
	_party_dismiss_action.tooltip_text = "没有可解除同行的队友。" if _selected_party_member_id.is_empty() else "解除所选队友的同行承诺。"
	if _party_candidate_picker.item_count == 0:
		_party_detail.text += "\n\n暂无可邀请人物，可先在校园探索并结识他人。"
	var clock: Dictionary = SimulationBridge.campus_snapshot.get("clock", {})
	var previous_slot: Dictionary = {}
	if _departure_picker.selected >= 0:
		previous_slot = _departure_picker.get_item_metadata(_departure_picker.selected)
	_departure_picker.clear()
	for offset in range(3):
		for phase in ["evening", "late_night"]:
			if offset == 0 and String(clock.get("phase", "")) == "late_night" and phase == "evening":
				continue
			var slot := {"day": int(clock.get("day", 1)) + offset, "phase": phase}
			var index := _departure_picker.item_count
			_departure_picker.add_item("第 %d 天 · %s" % [slot.day, SimulationBridge.phase_display_name(phase)])
			_departure_picker.set_item_metadata(index, slot)
			if slot == previous_slot:
				_departure_picker.select(index)
	_departure_reserve.disabled = String(party.get("leader_id", "")) != "player"
	_departure_cancel.disabled = _departure_reserve.disabled
	_departure_reserve.tooltip_text = "全队同意后才预约；课程、工作和已接任务可能冲突。首次开战扣行动，取消不返还已用行动。"
	_lock_social_controls("party", [_party_invite_action, _party_dismiss_action, _party_candidate_picker, _party_member_picker, _departure_picker, _departure_reserve, _departure_cancel])


func _operate_departure(cancel: bool) -> void:
	if not String(_social_pending.party).is_empty() or _departure_reserve.disabled:
		return
	var slot: Dictionary = _departure_picker.get_item_metadata(_departure_picker.selected)
	_social_pending.party = "departure"
	_refresh_party_page()
	_party_feedback.text = "正在协调出击日程……"
	SimulationBridge.operate_campus_party("CANCEL_PARTY_DEPARTURE" if cancel else "RESERVE_PARTY_DEPARTURE", "departure", slot)


func _select_party_candidate(index: int) -> void:
	_selected_party_candidate_id = String(_party_candidate_picker.get_item_metadata(index))
	_selected_party_candidate_is_contact = _party_candidate_picker.get_item_tooltip(index) == "phone_contact"
	_refresh_party_page()


func _select_party_member(index: int) -> void:
	_selected_party_member_id = String(_party_member_picker.get_item_metadata(index))


func _invite_party_candidate() -> void:
	if _party_invite_action.disabled or not String(_social_pending.party).is_empty():
		return
	_social_pending.party = _selected_party_candidate_id
	_refresh_party_page()
	_party_feedback.text = "正在等待对方决定……"
	SimulationBridge.operate_campus_social_proposal(
		_selected_party_candidate_id, "party_invite", "phone"
	)


func _dismiss_party_member() -> void:
	if _party_dismiss_action.disabled or not String(_social_pending.party).is_empty():
		return
	_social_pending.party = _selected_party_member_id
	_refresh_party_page()
	_party_feedback.text = "正在解除同行承诺……"
	SimulationBridge.operate_campus_party("DISMISS_PARTY_MEMBER", _selected_party_member_id)


func _on_party_operation_completed(success: bool, result: Dictionary, _action_id: String, _target_id: String) -> void:
	_social_pending.party = ""
	_party_feedback.text = UI_TEXT.operation_feedback(success, result)
	_party_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	_refresh_party_page()


func _lock_social_controls(page: String, controls: Array) -> void:
	if String(_social_pending.get(page, "")).is_empty():
		return
	for control in controls:
		control.disabled = true
		control.tooltip_text = UI_TEXT.PENDING_MESSAGE


func _lock_waiting_controls(node: Node) -> void:
	for child in node.get_children():
		if child is BaseButton:
			child.disabled = true
			child.tooltip_text = UI_TEXT.PENDING_MESSAGE
		_lock_waiting_controls(child)


func _refresh_message_controls() -> void:
	if _message_send_action == null:
		return
	var no_contact := _selected_message_contact_id.is_empty()
	_message_contact_picker.disabled = no_contact
	_message_proposal_picker.disabled = no_contact
	_message_send_action.disabled = no_contact or _message_input.text.strip_edges().is_empty()
	_message_proposal_action.disabled = no_contact
	_message_send_action.tooltip_text = "请先添加联系人。" if no_contact else ("请输入消息内容。" if _message_input.text.strip_edges().is_empty() else "发送消息不消耗主要行动，不设每日聊天次数上限。")
	_message_proposal_action.tooltip_text = "请先添加联系人。" if no_contact else "对方会自主决定是否接受。"
	if not _message_pending.is_empty():
		_lock_waiting_controls(_message_root)


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
	_combat_items.refresh(active)
	_combat_insights.refresh(active)
	_refresh_combat_presentation(active)
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
		if _combat_feedback.text.contains("小队败北") or _combat_feedback.text.contains("撤回表世界"):
			_combat_formation_detail.text = "[b]上次战斗结果[/b]\n%s\n\n%s" % [_combat_feedback.text, _combat_formation_detail.text]
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
		_combat_retreat_action.disabled = true
		_reset_combat_action_controls()
		_combat_hand_detail.text = "[color=#91a4bc]锁定阵型后可生成个人八张牌组与共享战术手牌。[/color]"
		_refresh_combat_hints()
		return

	var row_names := {"front": "前排", "middle": "中排", "back": "后排"}
	var cards: Dictionary = active.get("character_cards", {})
	var formation: Dictionary = (active.get("formations", {}) as Dictionary).get("party:player", {})
	var lines: Array[String] = []
	for row_id in ["front", "middle", "back"]:
		var names: Array[String] = []
		for card_id_value in formation.get(row_id, []):
			var deployed_card: Dictionary = cards.get(String(card_id_value), {})
			var actor_id := String(deployed_card.get("actor_id", ""))
			var pollution := int(active.get("pollution", {}).get(actor_id, 0))
			var status_names := {"pollution_noticeable": "月蚀显现", "pollution_severe": "认知动摇", "pollution_critical": "自我濒危"}
			var visible_statuses: Array[String] = []
			for status_id_value in active.get("statuses", {}).get(actor_id, []):
				var status_id := String(status_id_value)
				visible_statuses.append(String(status_names.get(status_id, "倒下" if status_id == "incapacitated" else status_id)))
			var status_text := " · %s" % " / ".join(visible_statuses) if not visible_statuses.is_empty() else ""
			names.append("%s · 生命 %d/%d · 护盾 %d · 污染 %d%%%s" % [deployed_card.get("display_name", "未知人物"), int(active.get("health", {}).get(actor_id, 0)), int(deployed_card.get("max_health", 0)), int(active.get("barriers", {}).get(actor_id, 0)), pollution, status_text])
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
			var intent: Dictionary = active.get("enemy_intents", {}).get(enemy_id, {})
			if not intent.is_empty() and int(enemy_health.get(enemy_id, 0)) > 0:
				enemy_names.append("意图：攻击%s · 威力 %d · 污染 %d（防御/护盾前）" % [row_names.get(String(intent.get("target_row", "")), "未知排位"), int(intent.get("power", 0)), int(intent.get("pollution_power", 0))])
				if "disrupted" in enemy.get("statuses", []):
					enemy_names.append("受到干扰：下次攻击威力减半")
		enemy_lines.append("[b]%s[/b]  %s" % [row_names[row_id], " / ".join(enemy_names) if not enemy_names.is_empty() else "—"])
	var phase_names := {
		"setup": "准备中", "ready": "阵型已锁定", "player_turn": "玩家行动",
		"enemy_turn": "敌方行动", "round_end": "轮次结算", "resolved": "战斗结束",
	}
	var phase_name := String(phase_names.get(String(active.get("phase", "")), "战斗中"))
	_combat_formation_detail.text = "[font_size=21][b]%s[/b][/font_size]\n[b]我方阵型[/b]\n%s\n\n[b]敌方阵型[/b]\n%s\n\n[color=#91a4bc]每排最多两人；玩家必须上场；锁定后本场不能替补。[/color]" % [
		phase_name, "\n".join(lines), "\n".join(enemy_lines)
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
	_refresh_combat_hints()


func _refresh_combat_presentation(active: Dictionary) -> void:
	var phase := String(active.get("phase", ""))
	var setup := phase == "setup"
	var fighting := phase in ["player_turn", "enemy_turn", "round_end"]
	_combat_task_picker.get_parent().visible = active.is_empty()
	_combat_character_picker.get_parent().visible = setup
	_combat_deploy_action.get_parent().visible = setup
	_combat_confirm_action.get_parent().visible = setup
	_combat_start_action.visible = phase == "ready"
	_combat_end_round_action.visible = fighting
	_combat_retreat_action.visible = fighting
	_combat_card_picker.get_parent().visible = fighting
	_combat_base_picker.get_parent().visible = fighting
	_combat_items.visible = fighting
	_combat_insights.visible = fighting


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
			{"attack": "攻击", "defense": "防御", "control": "控制", "knowledge": "知识", "signature": "特质", "support": "支援", "technique": "技巧"}.get(String(instance.get("card_type", "")), "指令"),
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
	_refresh_combat_hints()


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
	_refresh_combat_hints()


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
	var entry: Dictionary = SimulationBridge.campus_snapshot.get("combat", {}).get("entry_action", {})
	_combat_start_action.disabled = _combat_start_action.disabled or not bool(entry.get("allowed", false))
	_combat_end_round_action.disabled = String(active.get("phase", "")) != "player_turn"
	_combat_retreat_action.disabled = String(active.get("phase", "")) != "player_turn"
	_refresh_combat_hints()


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
	if _combat_prepare_action.disabled or _combat_pending:
		return
	_combat_feedback.text = "正在建立战斗准备……"
	_send_combat_operation(
		"START_BATTLE_PREPARATION", {"task_id": _selected_combat_task_id}
	)


func _active_combat_parameters() -> Dictionary:
	if _combat_pending:
		return {}
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
	_send_combat_operation(action_id, parameters)


func _withdraw_combat_character() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty():
		return
	parameters["character_card_instance_id"] = _selected_character_card_id
	_combat_feedback.text = "正在撤回人物牌……"
	_send_combat_operation("WITHDRAW_COMBAT_CHARACTER", parameters)


func _confirm_combat_deployment() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty():
		return
	_combat_feedback.text = "正在锁定阵型……"
	_send_combat_operation("CONFIRM_BATTLE_DEPLOYMENT", parameters)


func _start_card_combat() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty():
		return
	_combat_feedback.text = "正在洗入个人牌组并抽取首轮手牌……"
	_send_combat_operation("START_CARD_COMBAT", parameters)


func _end_combat_round() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty():
		return
	_combat_feedback.text = "正在结算敌方攻击、护盾与倒下状态……"
	_send_combat_operation("END_COMBAT_ROUND", parameters)


func _retreat_from_combat() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty() or _combat_retreat_action.disabled:
		return
	_combat_feedback.text = "正在承受敌方追击并尝试撤回表世界……"
	_send_combat_operation("RETREAT_CARD_COMBAT", parameters)


func _play_combat_card() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty() or _combat_card_target_picker.selected < 0:
		return
	parameters["card_instance_id"] = _selected_combat_card_id
	parameters["target_ids"] = [String(
		_combat_card_target_picker.get_item_metadata(_combat_card_target_picker.selected)
	)]
	_combat_feedback.text = "正在结算指令牌……"
	_send_combat_operation("PLAY_COMBAT_CARD", parameters)


func _use_combat_base_command() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty() or _combat_base_target_picker.selected < 0:
		return
	parameters["source_actor_id"] = _selected_combat_base_actor_id
	parameters["target_ids"] = [String(
		_combat_base_target_picker.get_item_metadata(_combat_base_target_picker.selected)
	)]
	_combat_feedback.text = "正在执行基础指令……"
	_send_combat_operation("USE_COMBAT_BASE_COMMAND", parameters)


func _use_combat_item(selection: Dictionary) -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty():
		return
	parameters.merge(selection)
	_combat_feedback.text = "正在从使用者库存取药并结算治疗与指令费用……"
	_send_combat_operation("USE_COMBAT_ITEM", parameters)


func _cancel_combat_preparation() -> void:
	var parameters := _active_combat_parameters()
	if parameters.is_empty():
		return
	_combat_feedback.text = "正在取消战斗准备……"
	_send_combat_operation("CANCEL_BATTLE_PREPARATION", parameters)


func _on_combat_operation_completed(
	success: bool, result: Dictionary, _action_id: String, _battle_id: String
) -> void:
	_combat_pending = false
	_combat_feedback.text = UI_TEXT.operation_feedback(success, result)
	_combat_feedback.add_theme_color_override("font_color", Color("9bcf9b") if success else Color("ee8174"))
	_refresh_combat_page()


func _send_combat_operation(action: String, parameters: Dictionary) -> void:
	if _combat_pending:
		return
	_combat_pending = true
	_refresh_combat_hints()
	SimulationBridge.operate_campus_combat(action, parameters)


func _refresh_combat_hints() -> void:
	if _combat_prepare_action == null:
		return
	for pair in [
		[_combat_prepare_action, "需处于夜相、持有自己的夜相任务并到达任务区域，且没有其他战斗。"],
		[_combat_deploy_action, "仅准备阶段可部署；已部署角色可在己方回合花费指令点换位。"],
		[_combat_withdraw_action, "只能在准备阶段撤回已经部署的人物。"],
		[_combat_confirm_action, "准备阶段需先部署玩家人物牌。"],
		[_combat_cancel_action, "只可取消尚未开战的准备，不等于战中撤退。"],
		[_combat_start_action, "请先确认阵型，再开始战斗。"],
		[_combat_end_round_action, "只有己方行动阶段可以结束本轮。"],
		[_combat_retreat_action, "撤退会先承受当前已预告的敌方攻击；幸存后保留伤势和消耗并释放任务。"],
		[_combat_play_card_action, "需有可用手牌、合法目标和足够共享指令点。"],
		[_combat_use_base_action, "需有合法目标、足够共享指令点，且该人物本轮尚未使用基础指令。"],
	]:
		pair[0].tooltip_text = pair[1]
	var entry: Dictionary = SimulationBridge.campus_snapshot.get("combat", {}).get("entry_action", {})
	var blocked: Array = entry.get("blocked_actor_ids", [])
	var names := PackedStringArray()
	for actor_id in blocked:
		names.append(String(SimulationBridge.campus_snapshot.get("population", {}).get(actor_id, {}).get("display_name", "角色")))
	_combat_start_action.text = "开始战斗（本时段已付费）" if entry.get("due_actor_ids", []).is_empty() else "开始战斗（首次各扣 1 行动）"
	_combat_start_action.tooltip_text = "这些参战角色的主要行动已用完：%s" % "、".join(names) if not names.is_empty() else "阵型确认后开战；每名上场者本时段首次扣 1 次主要行动，连续多场不重复扣。"
	if _combat_pending:
		_lock_waiting_controls(_combat_root)


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
	_refresh_home_brief()
	_home.visible = true
	_app_page.visible = false
	_forum_root.visible = false
	_club_root.visible = false
	_party_root.visible = false
	_combat_root.visible = false
	_content.visible = true
	_feed_root.visible = false


func _refresh_home_brief() -> void:
	var snapshot := SimulationBridge.campus_snapshot
	var unread := int(snapshot.get("messaging", {}).get("unread_total", 0))
	var notices: Array = FEED.project(snapshot, true)
	_home_brief.text = "%d 条未读 · %d 项通知与约定 · 校园动态 ›" % [unread, notices.size()]


func _navigate_feed(app_id: String, target_id: String) -> void:
	if app_id == "messages" and not target_id.is_empty():
		if not _selected_message_contact_id.is_empty(): _message_drafts[_selected_message_contact_id] = _message_input.text
		_contact_search.text = ""
		_selected_message_contact_id = target_id
		_message_input.text = String(_message_drafts.get(target_id, ""))
	_open_app(app_id, {"messages": "校园通讯", "forums": "双层论坛", "party": "行动小队", "agenda": "日程与约定"}.get(app_id, "校园事项"))
	if app_id == "forums" and not target_id.is_empty():
		var task: Dictionary = SimulationBridge.campus_snapshot.get("tasks", {}).get(target_id, {})
		if not task.is_empty():
			_set_forum_channel(String(task.get("forum", "surface")))
			_open_task_detail(target_id)


func _prepare_readable_forms(node: Node) -> void:
	# Keep narrative/formation information readable instead of shrinking it to zero.
	if node is RichTextLabel and not node.fit_content and node.custom_minimum_size.y == 0:
		node.custom_minimum_size.y = 160
	if node is OptionButton:
		node.fit_to_longest_item = false
		node.clip_text = true
	for child in node.get_children():
		_prepare_readable_forms(child)


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
	_time_label.text = "第 %d 天 · %s" % [int(clock.get("day", 1)), SimulationBridge.phase_display_name(String(clock.get("phase", "morning")))]


func _refresh_connection(connected: bool, _message: String) -> void:
	_connection_label.text = "模拟已连接" if connected else "模拟未连接"
	_connection_label.tooltip_text = "本地模拟服务连接状态；不表示 LLM 接口已配置或可用。"


func open_hud_page(id: String) -> void:
	_set_open(true)
	if not _opened or id == "phone": return
	var titles := {"party": "队友", "character": "人物与物品", "cards": "卡牌库", "relationships": "关系 · 交友与恋爱", "agenda": "日程与约定", "forums": "双层论坛"}
	_open_app(id, String(titles.get(id, id)))


func _refresh_character_summary() -> void:
	var names := {"physique": "体魄", "dexterity": "灵巧", "focus": "专注", "insight": "洞察", "empathy": "共情", "expression": "表达"}
	var parts := PackedStringArray()
	for key in SimulationBridge.campus_snapshot.get("growth", {}).get("attributes", {}):
		parts.append("%s %d" % [names.get(key, key), int(SimulationBridge.campus_snapshot.growth.attributes[key])])
	_character_summary.text = "基础属性\n" + " · ".join(parts)
