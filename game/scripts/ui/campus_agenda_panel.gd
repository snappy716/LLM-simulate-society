extends VBoxContainer
## Existing commitments plus shared public opportunity commands; no local rewards.

signal open_management(app_id: String, app_name: String)

const PHASES := {"morning": "上午", "afternoon": "下午", "evening": "晚上", "late_night": "凌晨"}
var detail: RichTextLabel
var note: Label
var opportunity: OptionButton
var opportunity_detail: RichTextLabel
var enroll: Button
var cancel: Button
var attend: Button
var feedback: Label
var participation: RichTextLabel
var event_club: OptionButton
var event_support: CheckButton
var event_results: RichTextLabel
var event_board_picker: OptionButton
var _event_boards: Array = []
var _event_session := ""
var _offers: Array = []
var _pending := false


func _ready() -> void:
	detail = RichTextLabel.new()
	detail.bbcode_enabled = false
	detail.fit_content = true
	detail.scroll_active = false
	detail.custom_minimum_size.y = 140
	add_child(detail)
	note = Label.new()
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(note)
	for entry in [["party", "行动小队"], ["messages", "校园通讯"]]:
		var button := Button.new()
		button.text = "前往%s管理约定" % entry[1]
		button.pressed.connect(func(): open_management.emit(entry[0], entry[1]))
		add_child(button)
	var heading := Label.new()
	heading.text = "公开校园活动 · 报名不是完成"
	add_child(heading)
	opportunity = OptionButton.new()
	opportunity.fit_to_longest_item = false
	opportunity.item_selected.connect(func(_index): _show_opportunity())
	add_child(opportunity)
	opportunity_detail = RichTextLabel.new()
	opportunity_detail.bbcode_enabled = false
	opportunity_detail.fit_content = true
	opportunity_detail.scroll_active = false
	add_child(opportunity_detail)
	event_club = OptionButton.new()
	event_club.fit_to_longest_item = false
	event_club.item_selected.connect(func(_index):
		event_support.button_pressed = false
		_update_support_permission()
	)
	add_child(event_club)
	event_support = CheckButton.new()
	event_support.text = "明确使用社团公共资源 · 到场时扣除"
	add_child(event_support)
	enroll = _button("报名 · 免费", "ENROLL_CAMPUS_OPPORTUNITY")
	cancel = _button("退出报名 · 不返还已用行动", "CANCEL_CAMPUS_OPPORTUNITY")
	attend = _button("到场参加 · 1 主要行动", "ATTEND_CAMPUS_OPPORTUNITY")
	feedback = Label.new()
	feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(feedback)
	participation = RichTextLabel.new()
	participation.bbcode_enabled = false
	participation.fit_content = true
	participation.scroll_active = false
	add_child(participation)
	event_board_picker = OptionButton.new()
	event_board_picker.fit_to_longest_item = false
	event_board_picker.item_selected.connect(func(_index): _show_event_result())
	add_child(event_board_picker)
	event_results = RichTextLabel.new()
	event_results.bbcode_enabled = false
	event_results.fit_content = false
	event_results.scroll_active = true
	event_results.custom_minimum_size.y = 240
	add_child(event_results)
	var outings := preload("res://scripts/ui/campus_outing_panel.gd").new()
	outings.name = "Outings"
	var bonds := preload("res://scripts/ui/campus_bond_panel.gd").new()
	bonds.name = "Bonds"
	add_child(bonds)
	add_child(outings)
	SimulationBridge.campus_life_operation_completed.connect(func(success, result):
		if not _pending: return
		_pending = false
		feedback.text = String(result.get("result", {}).get("message", result.get("error", "操作已完成" if success else "操作失败，请检查状态后重试")))
		refresh()
	)
	SimulationBridge.campus_snapshot_updated.connect(func(_snapshot):
		if visible:
			refresh()
	)
	refresh()


func refresh() -> void:
	var data: Dictionary = SimulationBridge.campus_snapshot.get("agenda", {})
	var lines := PackedStringArray(["我已确认的约定"])
	var rows: Array = data.get("commitments", [])
	if rows.is_empty():
		lines.append("目前没有待履行的已确认约定。\n这不代表没有课程、委托或其他可选活动。")
	for row in rows:
		var cost := "短暂见面 · 不扣主要行动" if int(row.major_action_cost) == 0 else "实际执行时核验主要行动"
		lines.append("第 %d 天 · %s\n%s\n%s\n%s" % [int(row.day), PHASES.get(row.phase, row.phase), row.label, row.location_name, cost])
	detail.text = "\n\n".join(lines)
	note.text = String(data.get("note", "正在读取本人约定…"))
	var previous := _selected()
	_offers = data.get("life", {}).get("offers", [])
	opportunity.clear()
	for row in _offers:
		var index := opportunity.item_count
		opportunity.add_item("第 %d 天 %s · %s" % [int(row.day), PHASES.get(row.phase, row.phase), row.name])
		opportunity.set_item_metadata(index, row.session_id)
		if row.session_id == previous: opportunity.select(index)
	var history_lines := PackedStringArray(["我的参与记录（仅本人）"])
	for row in data.get("life", {}).get("history", []):
		history_lines.append("第 %d 天 %s · %s · %s" % [int(row.day), PHASES.get(row.phase, row.phase), row.name, row.status_text])
		var result: Dictionary = row.get("result", {})
		if result.has("course"):
			history_lines.append("  已学习：%s · 知识进度 +%d" % [result.course.unit_name, int(result.course.knowledge_gain)])
		if result.has("job"):
			history_lines.append("  实收 %d · 付款方：%s" % [int(result.job.wage), result.job.payer_name])
		if result.has("event"):
			var entry: Dictionary = result.event
			history_lines.append("  表现 %d · %s" % [int(entry.score), entry.summary])
			var parts: Dictionary = entry.get("components", {})
			history_lines.append("  本人成绩依据：属性 %d / 学院技能 %d / 练习 %d / 课程准备 %d / 工具 %d / 社团支持 %d / 疲劳 %d" % [int(parts.get("attributes", 0)), int(parts.get("ability", 0)), int(parts.get("practice", 0)), int(parts.get("preparation", 0)), int(parts.get("tool", 0)), int(parts.get("organization", 0)), int(parts.get("fatigue", 0))])
			history_lines.append("  实用社团资源 %d · 结算贡献 %d" % [int(entry.get("resource_cost", 0)), int(entry.get("contribution", 0))])
	history_lines.append("\n我的课程进度（真实到课，不是考试成绩或异常掌握度）")
	for course in data.get("life", {}).get("courses", []):
		history_lines.append("%s · %d/%d · %s" % [course.name, int(course.completed_units), int(course.total_units), course.next_unit])
	participation.text = "\n".join(history_lines)
	var previous_event := String(event_board_picker.get_item_metadata(event_board_picker.selected)) if event_board_picker.selected >= 0 else ""
	_event_boards = data.get("life", {}).get("event_board", [])
	event_board_picker.clear()
	for event in _event_boards:
		event_board_picker.add_item("第 %d 天 · %s" % [int(event.day), event.name])
		event_board_picker.set_item_metadata(event_board_picker.item_count - 1, event.session_id)
		if event.session_id == previous_event: event_board_picker.select(event_board_picker.item_count - 1)
	event_board_picker.disabled = _event_boards.is_empty()
	_show_event_result()
	_show_opportunity()


func _selected() -> String:
	return String(opportunity.get_item_metadata(opportunity.selected)) if opportunity.selected >= 0 else ""


func _button(title: String, action: String) -> Button:
	var button := Button.new()
	button.text = title
	button.pressed.connect(func():
		if _pending or _selected().is_empty(): return
		var parameters := {"session_id": _selected()}
		if action == "ENROLL_CAMPUS_OPPORTUNITY" and event_club.visible and event_club.selected >= 0:
			parameters.event_options = {"club_id": String(event_club.get_item_metadata(event_club.selected).club_id), "use_club_resources": event_support.button_pressed}
		_pending = true
		feedback.text = "正在核验活动条件…"
		_show_opportunity()
		SimulationBridge.operate_campus_life(action, parameters)
	)
	add_child(button)
	return button


func _show_opportunity() -> void:
	var row: Dictionary = {}
	for entry in _offers:
		if entry.session_id == _selected(): row = entry
	enroll.disabled = _pending or not row.get("can_enroll", false)
	cancel.disabled = _pending or not row.get("can_cancel", false)
	attend.disabled = _pending or not row.get("can_attend", false)
	opportunity.disabled = _pending
	var is_event := row.has("event")
	event_club.visible = is_event
	event_support.visible = is_event
	if is_event:
		var previous_club := ""
		var previous_support := false
		if _event_session == _selected() and event_club.selected >= 0:
			previous_club = String(event_club.get_item_metadata(event_club.selected).club_id)
			previous_support = event_support.button_pressed
		if row.get("status") == "enrolled":
			previous_club = String(row.get("event_options", {}).get("club_id", ""))
			previous_support = bool(row.get("event_options", {}).get("use_club_resources", false))
		event_club.clear()
		for choice in row.get("club_choices", []):
			event_club.add_item(String(choice.name))
			event_club.set_item_metadata(event_club.item_count - 1, choice)
			if choice.club_id == previous_club: event_club.select(event_club.item_count - 1)
		event_support.button_pressed = previous_support
		event_club.disabled = _pending or not row.get("can_enroll", false)
		_update_support_permission()
	_event_session = _selected()
	if row.is_empty():
		opportunity_detail.text = "暂无可查看的公开活动。"
		return
	opportunity_detail.text = "%s\n%s\n%s · %s\n待到场 %d 人 · 已实际参加 %d 人\n%s\n参加条件：%s\n普通移动、聊天和购物仍不扣主要行动。" % [row.name, row.description, row.location_name, row.status_text, int(row.enrolled_count), int(row.completed_count), row.reason, row.attend_reason]
	opportunity_detail.text += "\n" + String(row.get("summary", ""))


func _update_support_permission() -> void:
	var allowed := event_club.selected >= 0 and bool(event_club.get_item_metadata(event_club.selected).get("can_use_resources", false))
	event_support.disabled = event_club.disabled or not allowed
	if not allowed and not event_club.disabled: event_support.button_pressed = false


func _show_event_result() -> void:
	var lines := PackedStringArray(["校园比赛与节庆 · 公开结果", "仅公开展示姓名和成果；不会自动添加联系人。"])
	if event_board_picker.selected < 0:
		lines.append("目前没有已开始的比赛或节庆；可在上方查看近期安排。")
	else:
		var event: Dictionary = _event_boards[event_board_picker.selected]
		lines.append("\n第 %d 天 %s · %s\n%s" % [int(event.day), PHASES.get(event.phase, event.phase), event.name, event.summary])
		for entry in event.get("results", []):
			lines.append("%s%s · %s" % [entry.name, "（%s）" % entry.club_name if not String(entry.club_name).is_empty() else "", entry.summary])
	var text := "\n".join(lines)
	if event_results.text != text:
		event_results.text = text
		event_results.scroll_to_line(0)
