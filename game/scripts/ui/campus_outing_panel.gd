extends VBoxContainer
## Actor-local server projection. No UI-generated consent, rewards or travel.

const PHASES := {"afternoon": "下午", "evening": "晚上"}
const STATUS := {"pending": "等待回应", "confirmed": "已确认", "declined": "已婉拒", "cancelled": "已取消", "missed": "未完成", "completed": "已共同完成"}
var contacts: OptionButton
var slots: OptionButton
var intent: OptionButton
var invitation: Button
var history: OptionButton
var detail: RichTextLabel
var feedback: Label
var accept: Button
var decline: Button
var cancel: Button
var attend: Button
var _rows: Array = []
var _pending := false


func _ready() -> void:
	var heading := Label.new()
	heading.text = "相处与约会 · 双方自愿"
	add_child(heading)
	contacts = _picker()
	slots = _picker()
	intent = _picker()
	intent.add_item("普通共同活动")
	intent.set_item_metadata(0, "companionship")
	intent.add_item("明确邀请约会（不自动确立关系）")
	intent.set_item_metadata(1, "date")
	invitation = _button("发出邀请 · 免费", "INVITE_CAMPUS_OUTING")
	history = _picker()
	history.item_selected.connect(func(_i): _show_record())
	detail = RichTextLabel.new()
	detail.bbcode_enabled = false
	detail.fit_content = true
	detail.scroll_active = false
	add_child(detail)
	accept = _button("接受本次邀请", "ACCEPT_CAMPUS_OUTING")
	decline = _button("婉拒本次邀请", "DECLINE_CAMPUS_OUTING")
	cancel = _button("取消约定 · 不惩罚拒绝", "CANCEL_CAMPUS_OUTING")
	attend = _button("已到场，确认一起活动 · 各 1 主要行动", "ATTEND_CAMPUS_OUTING")
	feedback = Label.new()
	feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(feedback)
	SimulationBridge.campus_outing_operation_completed.connect(func(success, result):
		if not _pending: return
		_pending = false
		feedback.text = String(result.get("result", {}).get("message", result.get("error", "已处理" if success else "未完成，请刷新")))
		refresh()
	)
	SimulationBridge.campus_snapshot_updated.connect(func(_snapshot): refresh())
	refresh()


func _picker() -> OptionButton:
	var picker := OptionButton.new()
	picker.fit_to_longest_item = false
	add_child(picker)
	return picker


func _selected(picker: OptionButton):
	return picker.get_item_metadata(picker.selected) if picker.selected >= 0 else null


func refresh() -> void:
	var data: Dictionary = SimulationBridge.campus_snapshot.get("agenda", {}).get("outings", {})
	var old_contact = _selected(contacts)
	contacts.clear()
	for row in data.get("contacts", []):
		contacts.add_item(row.name)
		contacts.set_item_metadata(contacts.item_count - 1, row.actor_id)
		if row.actor_id == old_contact: contacts.select(contacts.item_count - 1)
	var old_slot = _selected(slots)
	slots.clear()
	for row in data.get("slots", []):
		slots.add_item("第 %d 天 %s · %s" % [int(row.day), PHASES.get(row.phase, row.phase), row.location_name])
		slots.set_item_metadata(slots.item_count - 1, row)
		if row == old_slot: slots.select(slots.item_count - 1)
	var old_id = _selected(history)
	_rows = data.get("records", [])
	history.clear()
	for row in _rows:
		history.add_item("第 %d 天 %s · %s · %s" % [int(row.day), PHASES.get(row.phase, row.phase), row.partner_name, STATUS.get(row.status, row.status)])
		history.set_item_metadata(history.item_count - 1, row.outing_id)
		if row.outing_id == old_id or old_id == null: history.select(history.item_count - 1)
	invitation.disabled = _pending or contacts.item_count == 0 or slots.item_count == 0
	for picker in [contacts, slots, intent, history]: picker.disabled = _pending
	_show_record()


func _show_record() -> void:
	var row: Dictionary = {}
	for item in _rows:
		if item.outing_id == _selected(history): row = item
	accept.disabled = _pending or not row.get("can_reply", false)
	decline.disabled = accept.disabled
	cancel.disabled = _pending or not row.get("can_cancel", false)
	attend.disabled = _pending or not row.get("can_attend", false)
	if row.is_empty():
		detail.text = "暂无相处约定。只显示已有联系人；普通聊天免费，长时间共同活动需各留一次主要行动。"
		return
	detail.text = "%s · %s\n%s · %s\n%s\n实际到场确认 %d/2 人；未完成前不获得相处收益。" % [row.partner_name, "约会" if row.kind == "date" else "普通共同活动", row.location_name, STATUS.get(row.status, row.status), row.reason, row.attended.size()]
	if row.get("receipt") is Dictionary:
		detail.text += "\n共同经历：" + String(row.receipt.summary)


func _button(title: String, action: String) -> Button:
	var button := Button.new()
	button.text = title
	button.pressed.connect(func():
		if _pending: return
		var parameters: Dictionary = {}
		if action == "INVITE_CAMPUS_OUTING":
			if _selected(contacts) == null or _selected(slots) == null: return
			parameters = _selected(slots).duplicate(true)
			parameters.target_id = _selected(contacts)
			parameters.kind = _selected(intent)
		else:
			for row in _rows:
				if row.outing_id == _selected(history):
					parameters = {"outing_id": row.outing_id, "expected_revision": row.revision}
			if parameters.is_empty(): return
		_pending = true
		feedback.text = "正在核验本人意愿、日程与实际地点…"
		refresh()
		SimulationBridge.operate_campus_outing(action, parameters)
	)
	add_child(button)
	return button
