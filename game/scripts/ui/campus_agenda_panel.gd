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
	var outings := preload("res://scripts/ui/campus_outing_panel.gd").new()
	outings.name = "Outings"
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
	history_lines.append("\n我的课程进度（真实到课，不是考试成绩或异常掌握度）")
	for course in data.get("life", {}).get("courses", []):
		history_lines.append("%s · %d/%d · %s" % [course.name, int(course.completed_units), int(course.total_units), course.next_unit])
	participation.text = "\n".join(history_lines)
	_show_opportunity()


func _selected() -> String:
	return String(opportunity.get_item_metadata(opportunity.selected)) if opportunity.selected >= 0 else ""


func _button(title: String, action: String) -> Button:
	var button := Button.new()
	button.text = title
	button.pressed.connect(func():
		if _pending or _selected().is_empty(): return
		_pending = true
		feedback.text = "正在核验活动条件…"
		_show_opportunity()
		SimulationBridge.operate_campus_life(action, {"session_id": _selected()})
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
	if row.is_empty():
		opportunity_detail.text = "暂无可查看的公开活动。"
		return
	opportunity_detail.text = "%s\n%s\n%s · %s\n待到场 %d 人 · 已实际参加 %d 人\n%s\n参加条件：%s\n普通移动、聊天和购物仍不扣主要行动。" % [row.name, row.description, row.location_name, row.status_text, int(row.enrolled_count), int(row.completed_count), row.reason, row.attend_reason]
	opportunity_detail.text += "\n" + String(row.get("summary", ""))
