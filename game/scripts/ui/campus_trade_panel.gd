extends VBoxContainer
## Local handover, not a global contact list or an online delivery service.

var target_picker: OptionButton
var item_picker: OptionButton
var side_picker: OptionButton
var price: SpinBox
var quantity: SpinBox
var propose: Button
var offer_picker: OptionButton
var respond: Button
var decline: Button
var detail: RichTextLabel
var feedback: Label
var _pending := false


func _ready() -> void:
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	target_picker = OptionButton.new()
	add_child(target_picker)
	var row := HBoxContainer.new()
	side_picker = OptionButton.new()
	side_picker.add_item("向对方购买")
	side_picker.add_item("出售给对方")
	row.add_child(side_picker)
	item_picker = OptionButton.new()
	item_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	item_picker.item_selected.connect(func(_index):
		var economy: Dictionary = SimulationBridge.campus_snapshot.get("economy", {})
		price.value = float(economy.get("items", {}).get(_selected(item_picker), {}).get("base_price", 1))
	)
	row.add_child(item_picker)
	add_child(row)
	row = HBoxContainer.new()
	var label := Label.new()
	label.text = "单价 / 数量"
	row.add_child(label)
	price = SpinBox.new()
	price.min_value = 1
	price.max_value = 100000
	price.value = 4
	row.add_child(price)
	quantity = SpinBox.new()
	quantity.min_value = 1
	quantity.max_value = 99
	row.add_child(quantity)
	add_child(row)
	propose = Button.new()
	propose.text = "提出报价（不立即扣款）"
	propose.pressed.connect(func(): _send("OFFER_TRADE", {"target_id": _selected(target_picker), "item_id": _selected(item_picker), "side": "buy" if side_picker.selected == 0 else "sell", "unit_price": int(price.value), "quantity": int(quantity.value)}))
	add_child(propose)
	offer_picker = OptionButton.new()
	offer_picker.item_selected.connect(func(_index):
		feedback.text = ""
		_refresh_offer()
	)
	add_child(offer_picker)
	detail = RichTextLabel.new()
	detail.size_flags_vertical = Control.SIZE_EXPAND_FILL
	add_child(detail)
	row = HBoxContainer.new()
	respond = Button.new()
	respond.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	respond.pressed.connect(func():
		var offer := _offer()
		_send("ACCEPT_TRADE" if offer.get("recipient_id") == "player" else "REQUEST_TRADE_RESPONSE", {"offer_id": _selected(offer_picker)})
	)
	row.add_child(respond)
	decline = Button.new()
	decline.pressed.connect(func():
		_send("REJECT_TRADE" if _offer().get("recipient_id") == "player" else "CANCEL_TRADE", {"offer_id": _selected(offer_picker)})
	)
	row.add_child(decline)
	add_child(row)
	feedback = Label.new()
	feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(feedback)
	SimulationBridge.campus_snapshot_updated.connect(func(_snapshot): refresh())
	SimulationBridge.campus_inventory_operation_completed.connect(func(_success, result):
		if _pending:
			_pending = false
			feedback.text = String(result.get("result", {}).get("message", result.get("error", "操作失败")))
			refresh()
			var changed_id := String(result.get("result", {}).get("payload", {}).get("offer", {}).get("offer_id", ""))
			for index in range(offer_picker.item_count):
				if String(offer_picker.get_item_metadata(index)) == changed_id:
					offer_picker.select(index)
			_refresh_offer()
	)
	refresh()


func _selected(picker: OptionButton) -> String:
	return String(picker.get_item_metadata(picker.selected)) if picker.selected >= 0 else ""


func _offer() -> Dictionary:
	for offer in SimulationBridge.campus_snapshot.get("economy", {}).get("private_trade", {}).get("offers", []):
		if offer.offer_id == _selected(offer_picker):
			return offer
	return {}


func refresh() -> void:
	var economy: Dictionary = SimulationBridge.campus_snapshot.get("economy", {})
	var old_target := _selected(target_picker)
	target_picker.clear()
	for actor_id in economy.get("nearby_actor_ids", []):
		var index := target_picker.item_count
		target_picker.add_item(String(SimulationBridge.campus_snapshot.get("population", {}).get(actor_id, {}).get("display_name", actor_id)))
		target_picker.set_item_metadata(index, actor_id)
		if actor_id == old_target:
			target_picker.select(index)
	if item_picker.item_count == 0:
		for item_id in economy.get("items", {}):
			var index := item_picker.item_count
			item_picker.add_item(String(economy.items[item_id].name))
			item_picker.set_item_metadata(index, item_id)
	var old_offer := _selected(offer_picker)
	offer_picker.clear()
	var offers: Array = economy.get("private_trade", {}).get("offers", []).duplicate()
	offers.reverse()
	var names := {"pending": "待回应", "settled": "已成交", "rejected": "已拒绝", "cancelled": "已撤销", "expired": "已过期"}
	for offer in offers:
		var index := offer_picker.item_count
		offer_picker.add_item("%s · %s" % [offer.offer_id, names.get(offer.status, offer.status)])
		offer_picker.set_item_metadata(index, offer.offer_id)
		if offer.offer_id == old_offer:
			offer_picker.select(index)
	propose.disabled = _pending or target_picker.item_count == 0 or bool(economy.get("battle_locked", false))
	_refresh_offer()


func _refresh_offer() -> void:
	var offer := _offer()
	var incoming: bool = offer.get("recipient_id") == "player"
	respond.text = "接受并结算" if incoming else "请对方回应"
	decline.text = "拒绝" if incoming else "撤销"
	respond.disabled = _pending or offer.get("status") != "pending" or (incoming and not bool(offer.get("can_accept", false)))
	decline.disabled = _pending or offer.get("status") != "pending"
	var economy: Dictionary = SimulationBridge.campus_snapshot.get("economy", {})
	var lines := PackedStringArray(["余额：%d 元" % int(economy.get("balance", 0))])
	if not offer.is_empty():
		lines.append("%s × %d · 单价 %d 元\n%s" % [economy.get("items", {}).get(offer.item_id, {}).get("name", offer.item_id), int(offer.quantity), int(offer.unit_price), offer.reason])
		lines.append(String(offer.get("unavailable_reason", "")))
	if target_picker.item_count == 0:
		lines.append("此处暂无可当面交易的人，请先在校园探索。")
	lines.append("\n须同地同层交货，不扣主要行动。NPC 根据需求、价格、关系与保留数量判断，不保证接受。")
	var memories: Array = economy.get("private_trade", {}).get("memories", [])
	lines.append("\n最近交易/报价记忆：%d 条（只显示自己的记录）" % memories.size())
	detail.text = "\n".join(lines)


func _send(action: String, parameters: Dictionary) -> void:
	_pending = true
	refresh()
	SimulationBridge.operate_campus_inventory(action, parameters)
