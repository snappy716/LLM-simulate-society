extends VBoxContainer
## Only participant-owned relationships returned by the server.

const STATUS := {"pending": "待回应", "active": "已确认", "declined": "已婉拒", "cancelled": "已撤回", "ended": "已结束", "expired": "已过期"}
var contacts: OptionButton
var kind: OptionButton
var history: OptionButton
var propose: Button
var accept: Button
var decline: Button
var cancel: Button
var end_bond: Button
var detail: Label
var feedback: Label
var _rows: Array = []
var _pending := false


func _ready() -> void:
	var heading := Label.new()
	heading.text = "交友与恋爱 · 每段关系分别确认"
	add_child(heading)
	contacts = _picker()
	kind = _picker()
	kind.add_item("确认好友关系")
	kind.set_item_metadata(0, "friendship")
	kind.add_item("表达恋爱心意（不约定排他关系）")
	kind.set_item_metadata(1, "romance")
	propose = _button("发送关系请求 · 免费", "PROPOSE_CAMPUS_BOND")
	history = _picker()
	history.item_selected.connect(func(_i): _show_record())
	detail = Label.new()
	detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(detail)
	accept = _button("同意确认这段关系", "ACCEPT_CAMPUS_BOND")
	decline = _button("婉拒 · 不惩罚拒绝", "DECLINE_CAMPUS_BOND")
	cancel = _button("撤回待回应请求", "CANCEL_CAMPUS_BOND")
	end_bond = _button("结束所选关系 · 不影响其他关系", "END_CAMPUS_BOND")
	feedback = Label.new()
	feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(feedback)
	SimulationBridge.campus_bond_operation_completed.connect(func(success, result):
		if not _pending: return
		_pending = false
		feedback.text = String(result.get("result", {}).get("message", result.get("error", "已处理" if success else "未完成")))
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
	var agenda: Dictionary = SimulationBridge.campus_snapshot.get("agenda", {})
	var old_contact = _selected(contacts)
	contacts.clear()
	for row in agenda.get("outings", {}).get("contacts", []):
		contacts.add_item(row.name)
		contacts.set_item_metadata(contacts.item_count - 1, row.actor_id)
		if old_contact == row.actor_id: contacts.select(contacts.item_count - 1)
	var old_id = _selected(history)
	_rows = agenda.get("bonds", {}).get("records", [])
	history.clear()
	for row in _rows:
		history.add_item("%s · %s · %s" % [row.partner_name, "好友" if row.kind == "friendship" else "恋人", STATUS.get(row.status, row.status)])
		history.set_item_metadata(history.item_count - 1, row.bond_id)
		if old_id == null or row.bond_id == old_id: history.select(history.item_count - 1)
	propose.disabled = _pending or contacts.item_count == 0
	for picker in [contacts, kind, history]: picker.disabled = _pending
	_show_record()


func _show_record() -> void:
	var row: Dictionary = {}
	for item in _rows:
		if item.bond_id == _selected(history): row = item
	accept.disabled = _pending or not row.get("can_reply", false)
	decline.disabled = accept.disabled
	cancel.disabled = _pending or not row.get("can_cancel", false)
	end_bond.disabled = _pending or not row.get("can_end", false)
	detail.text = "不限制正式伴侣数量；每段关系分别同意。约会不等于恋爱，也不保证告白成功。只显示本人参与的关系。"
	if not row.is_empty():
		detail.text += "\n%s · %s\n%s" % [row.partner_name, STATUS.get(row.status, row.status), row.reason]
		for event in row.get("history", []):
			detail.text += "\n第 %d 天：%s" % [int(event.day), event.reason]


func _button(title: String, action: String) -> Button:
	var button := Button.new()
	button.text = title
	button.pressed.connect(func():
		if _pending or SimulationBridge.is_campus_busy(): return
		var parameters: Dictionary = {}
		if action == "PROPOSE_CAMPUS_BOND":
			if _selected(contacts) == null: return
			parameters = {"target_id": _selected(contacts), "kind": _selected(kind)}
		else:
			for row in _rows:
				if row.bond_id == _selected(history):
					parameters = {"bond_id": row.bond_id, "expected_revision": row.revision}
			if parameters.is_empty(): return
		_pending = true
		feedback.text = "正在核验关系请求…"
		refresh()
		SimulationBridge.operate_campus_bond(action, parameters)
	)
	add_child(button)
	return button
