extends VBoxContainer
## Only the player's real material needs and participated commitments are shown.

var item: OptionButton
var helper: OptionButton
var request_picker: OptionButton
var detail: RichTextLabel
var feedback: Label
var ask: Button
var accept: Button
var decline: Button
var deliver: Button
var cancel: Button
var _pending := false
var _data: Dictionary = {}
const TEXT = preload("res://scripts/ui/campus_ui_text.gd")


func _ready() -> void:
	var heading := Label.new()
	heading.text = "物资互助 · 答应不等于已交付"
	add_child(heading)
	item = _picker()
	helper = _picker()
	ask = _button(self, "请求带来一份 · 免费", func(): _send("REQUEST_MATERIAL_HELP", {"item_id": _selected(item), "helper_id": _selected(helper)}))
	request_picker = _picker()
	request_picker.item_selected.connect(func(_index): _details())
	detail = RichTextLabel.new()
	detail.custom_minimum_size.y = 210
	detail.bbcode_enabled = false
	add_child(detail)
	var row := HBoxContainer.new()
	add_child(row)
	accept = _button(row, "答应帮忙", func(): _respond(true))
	decline = _button(row, "暂不答应", func(): _respond(false))
	deliver = _button(self, "当面交付约定物资 · 免费", func(): _send("DELIVER_MATERIAL_HELP", {"request_id": _selected(request_picker)}))
	cancel = _button(self, "撤回约定", func(): _send("CANCEL_MATERIAL_HELP", {"request_id": _selected(request_picker)}))
	feedback = Label.new()
	feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(feedback)
	SimulationBridge.campus_assistance_operation_completed.connect(_completed)
	SimulationBridge.campus_snapshot_updated.connect(func(_snapshot):
		if visible: refresh()
	)
	refresh()


func _picker() -> OptionButton:
	var picker := OptionButton.new()
	picker.fit_to_longest_item = false
	add_child(picker)
	return picker


func _button(parent: Node, title: String, callback: Callable) -> Button:
	var button := Button.new()
	button.text = title
	button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	button.pressed.connect(callback)
	parent.add_child(button)
	return button


func _selected(picker: OptionButton) -> String:
	return String(picker.get_item_metadata(picker.selected)) if picker.item_count > 0 and picker.selected >= 0 else ""


func _fill(picker: OptionButton, entries: Array, id_key: String, text_key: String, empty: String) -> void:
	var selected := _selected(picker)
	picker.clear()
	for entry in entries:
		picker.add_item(String(entry.get(text_key, "")))
		picker.set_item_metadata(picker.item_count - 1, String(entry.get(id_key, "")))
		if String(entry.get(id_key, "")) == selected:
			picker.select(picker.item_count - 1)
	if entries.is_empty():
		picker.add_item(empty)
		picker.set_item_metadata(0, "")
	picker.disabled = _pending or entries.is_empty()


func refresh() -> void:
	_data = SimulationBridge.campus_snapshot.get("assistance", {})
	_fill(item, _data.get("needs", []), "item_id", "name", "当前没有这类物资缺口")
	_fill(helper, _data.get("contacts", []), "actor_id", "name", "需要先见面或交换联系方式")
	var requests: Array = _data.get("requests", []).duplicate(true)
	for request in requests:
		request["label"] = "%s · %s → %s · %s" % [request.item_name, request.helper_name, request.requester_name, request.status_text]
	_fill(request_picker, requests, "request_id", "label", "暂无与你有关的互助约定")
	ask.disabled = _pending or _selected(item).is_empty() or _selected(helper).is_empty()
	ask.tooltip_text = "只提出真实缺物需求，不会自动获得物品。"
	_details()


func _details() -> void:
	var selected: Dictionary = {}
	for request in _data.get("requests", []):
		if request.request_id == _selected(request_picker): selected = request
	accept.disabled = _pending or not selected.get("can_respond", false)
	decline.disabled = accept.disabled
	deliver.disabled = _pending or not selected.get("can_deliver", false)
	cancel.disabled = _pending or not selected.get("can_cancel", false)
	deliver.tooltip_text = "须已答应、携带可转交的一份物资、双方同地同世界；职业保留量、负重和战斗锁仍生效。"
	if selected.is_empty():
		detail.text = "只显示你参与的约定。\n\n对方可以拒绝；答应后需要实际备货和交付。手机可以沟通，不能隔空传送物品。"
		return
	var deadline: int = int(selected.expires_tick)
	detail.text = "%s\n%s → %s\n状态：%s\n碰面地点：%s（碰巧遇见也可直接交付）\n到期：第 %d 天 · %s\n\n%s\n\n承诺不会创建物品。对方通过其他方式补齐需求后，约定会结束；未履约的已接受约定到期会影响信任。" % [
		selected.item_name, selected.helper_name, selected.requester_name, selected.status_text,
		selected.meeting_name,
		deadline / 4 + 1, ["上午", "下午", "晚上", "深夜"][deadline % 4], selected.last_reason]


func _respond(accepted: bool) -> void:
	_send("RESPOND_MATERIAL_HELP", {"request_id": _selected(request_picker), "accepted": accepted})


func _send(action: String, params: Dictionary) -> void:
	if _pending: return
	_pending = true
	feedback.text = TEXT.PENDING_MESSAGE
	refresh()
	SimulationBridge.operate_campus_assistance(action, params)


func _completed(success: bool, response: Dictionary) -> void:
	if not _pending: return
	_pending = false
	feedback.text = TEXT.operation_feedback(success, response)
	refresh()
