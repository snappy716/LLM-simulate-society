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


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("campus_phone_ui")
	_build_ui()
	SimulationBridge.campus_snapshot_updated.connect(_on_campus_snapshot_updated)
	SimulationBridge.campus_task_operation_completed.connect(_on_task_operation_completed)


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
	return page


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
	_content.visible = not is_forum
	_forum_root.visible = is_forum
	if is_forum:
		_forum_feedback.text = ""
		_show_forum_list()
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
	return "[b]校园通讯[/b]\n\n联系人、聊天和关系系统入口已经保留。\nNPC 对话与消息内容将在认知层接入后显示。"


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
	_forum_detail.text = "[font_size=22][b]%s[/b][/font_size]\n%s\n\n[b]发起人[/b]  %s\n[b]所属组织[/b]  %s\n[b]地点[/b]  %s\n[b]截止[/b]  第 %d 天\n[b]报酬[/b]  %d 校园币\n[b]社会影响[/b]  %s\n\n[b]当前目标[/b]\n%s\n\n[b]竞争情况[/b]\n%d 人查看，%d 人正在考虑\n\n[b]动态记录[/b]\n%s" % [
		task.get("title", "未命名任务"), task.get("description", ""),
		task.get("issuer_name", "校园用户"), organization_name if not organization_name.is_empty() else "个人委托",
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
	if not _opened or not _forum_root.visible:
		return
	if _selected_task_id.is_empty():
		_refresh_forum_list()
	else:
		_refresh_forum_detail()


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
	_forum_root.visible = false
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
