extends VBoxContainer
## Text-first campus inventory. No legacy inventory or wallet endpoints.

const ACTIONS := [
	["BUY_ITEM", "购买"], ["SELL_ITEM", "出售"], ["USE_ITEM", "使用"],
	["GIVE_ITEM", "转交"], ["DROP_ITEM", "放下"], ["PICK_UP_ITEM", "拾取"],
	["EQUIP_ITEM", "装备"], ["UNEQUIP_ITEM", "卸下"],
]
var shop_picker: OptionButton
var item_picker: OptionButton
var action_picker: OptionButton
var target_picker: OptionButton
var quantity: SpinBox
var detail: RichTextLabel
var feedback: Label
var submit: Button
var travel: Button
var _next_passage := ""
var _pending := false


func _ready() -> void:
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	shop_picker = OptionButton.new()
	shop_picker.item_selected.connect(func(_index): refresh())
	add_child(shop_picker)
	travel = Button.new()
	travel.pressed.connect(func(): SimulationBridge.traverse_campus_passage(_next_passage))
	add_child(travel)
	var row := HBoxContainer.new()
	action_picker = OptionButton.new()
	for action in ACTIONS:
		action_picker.add_item(action[1])
	action_picker.item_selected.connect(func(_index): refresh())
	row.add_child(action_picker)
	quantity = SpinBox.new()
	quantity.min_value = 1
	quantity.max_value = 99
	quantity.value = 1
	quantity.value_changed.connect(func(_value): _refresh_detail())
	row.add_child(quantity)
	add_child(row)
	item_picker = OptionButton.new()
	item_picker.item_selected.connect(func(_index): _refresh_detail())
	add_child(item_picker)
	target_picker = OptionButton.new()
	add_child(target_picker)
	detail = RichTextLabel.new()
	detail.size_flags_vertical = Control.SIZE_EXPAND_FILL
	detail.fit_content = false
	add_child(detail)
	feedback = Label.new()
	feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(feedback)
	submit = Button.new()
	submit.text = "确认"
	submit.pressed.connect(_execute)
	add_child(submit)
	SimulationBridge.campus_snapshot_updated.connect(func(_snapshot): refresh())
	SimulationBridge.campus_inventory_operation_completed.connect(_completed)
	SimulationBridge.campus_traversal_completed.connect(func(success, result, _passage):
		if visible and not success:
			feedback.text = String((result.get("result", {}) as Dictionary).get("message", result.get("error", "通行失败")))
	)
	refresh()


func _selected(picker: OptionButton) -> String:
	return String(picker.get_item_metadata(picker.selected)) if picker.selected >= 0 else ""


func _action() -> String:
	return ACTIONS[action_picker.selected][0]


func refresh() -> void:
	var economy: Dictionary = SimulationBridge.campus_snapshot.get("economy", {})
	var old_shop := _selected(shop_picker)
	shop_picker.clear()
	for shop in economy.get("shops", []):
		var index := shop_picker.item_count
		shop_picker.add_item("%s · %s · %s" % [shop.name, "在场" if shop.nearby else "须到店", "营业" if shop.open else "休息"])
		shop_picker.set_item_metadata(index, shop.id)
		if shop.id == old_shop:
			shop_picker.select(index)
	var trading := _action() in ["BUY_ITEM", "SELL_ITEM"]
	shop_picker.visible = trading
	travel.visible = trading
	target_picker.visible = _action() in ["GIVE_ITEM", "USE_ITEM"]
	var old_item := _selected(item_picker)
	item_picker.clear()
	var ids: Array = []
	if trading:
		for shop in economy.get("shops", []):
			if shop.id == _selected(shop_picker):
				for good in shop.goods:
					ids.append(good.item_id)
	else:
		var source: Dictionary = economy.get("ground", {}) if _action() == "PICK_UP_ITEM" else economy.get("inventory", {})
		ids = (source.get("quantities", {}) as Dictionary).keys()
	for item_id in ids:
		var item: Dictionary = (economy.get("items", {}) as Dictionary).get(item_id, {})
		var index := item_picker.item_count
		item_picker.add_item(String(item.get("name", item_id)))
		item_picker.set_item_metadata(index, item_id)
		if item_id == old_item:
			item_picker.select(index)
	var old_target := _selected(target_picker)
	target_picker.clear()
	if _action() == "USE_ITEM":
		target_picker.add_item("对自己使用（食物仅供自己食用）")
		target_picker.set_item_metadata(0, "player")
	for actor_id in economy.get("nearby_actor_ids", []):
		var actor: Dictionary = (SimulationBridge.campus_snapshot.get("population", {}) as Dictionary).get(actor_id, {})
		var index := target_picker.item_count
		target_picker.add_item(String(actor.get("display_name", actor_id)))
		target_picker.set_item_metadata(index, actor_id)
		if actor_id == old_target:
			target_picker.select(index)
	_refresh_detail()


func _refresh_detail() -> void:
	var economy: Dictionary = SimulationBridge.campus_snapshot.get("economy", {})
	var inventory: Dictionary = economy.get("inventory", {})
	var items: Dictionary = economy.get("items", {})
	var item_id := _selected(item_picker)
	var item: Dictionary = items.get(item_id, {})
	var lines := PackedStringArray(["余额：%d %s  负重：%.1f / %.1f" % [int(economy.get("balance", 0)), economy.get("currency", "元"), float(economy.get("weight", 0)), float(inventory.get("max_weight", 0))]])
	lines.append("\n%s\n%s" % [item.get("name", "没有物品"), item.get("description", "")])
	var owned := int((inventory.get("quantities", {}) as Dictionary).get(item_id, 0))
	lines.append("持有：%d" % owned)
	if item_id == "bandage_roll":
		var vitals: Dictionary = (SimulationBridge.campus_snapshot.get("player", {}) as Dictionary).get("vitals", {})
		lines.insert(1, "自身生命：%d / %d" % [int(vitals.get("health", 0)), int(vitals.get("max_health", 0))])
	var equipped: Dictionary = inventory.get("equipped", {})
	lines.append("装备状态：%s" % ("已装备" if item_id in equipped.values() else "未装备"))
	var unavailable := ""
	_next_passage = ""
	travel.text = "已到柜台"
	if _action() in ["BUY_ITEM", "SELL_ITEM"]:
		for shop in economy.get("shops", []):
			if shop.id != _selected(shop_picker):
				continue
			lines.append("柜台：%s" % shop.location_name)
			if not shop.nearby:
				unavailable = "请先到柜台所在地点。"
				_next_passage = _route_first_passage(String(shop.location_id))
				travel.text = "沿道路 / 入口前往柜台（下一段）"
			elif not shop.open:
				unavailable = "商店尚未营业。"
			for good in shop.goods:
				if good.item_id == item_id:
					var price := int(good.buy_price if _action() == "BUY_ITEM" else good.sell_price)
					lines.insert(1, "库存：%d  单价：%d  合计：%d" % [int(good.stock), price, price * int(quantity.value)])
					if _action() == "SELL_ITEM" and price <= 0:
						unavailable = "本窗口不回收物品。"
	if bool(economy.get("battle_locked", false)):
		unavailable = "战斗中暂不可使用生活物品操作。"
	if _action() == "GIVE_ITEM" and target_picker.item_count == 0:
		unavailable = "同一地点没有可转交的角色。"
	lines.append("\n购物、吃饭不消耗时段或主要行动。")
	lines.append(unavailable)
	detail.text = "\n".join(lines)
	submit.disabled = _pending or item_id.is_empty() or not unavailable.is_empty()
	travel.disabled = _next_passage.is_empty() or bool(economy.get("battle_locked", false))
	submit.text = "处理中…" if _pending else "确认%s" % ACTIONS[action_picker.selected][1]


static func _route_first_passage(destination: String) -> String:
	# UI suggests one edge; the server independently checks doors, access and clock.
	var campus: Dictionary = SimulationBridge.campus_snapshot
	var player: Dictionary = campus.get("player", {})
	var start := String(player.get("current_location_id", ""))
	var frontier: Array = [start]
	var first := {start: ""}
	var phase := String((campus.get("clock", {}) as Dictionary).get("phase", ""))
	var access: Array = player.get("access_tags", [])
	var places: Dictionary = campus.get("places", {})
	while not frontier.is_empty():
		var current := String(frontier.pop_front())
		for passage in (campus.get("passages", {}) as Dictionary).values():
			var next := ""
			if passage.from_id == current:
				next = passage.to_id
			elif passage.to_id == current and bool(passage.get("bidirectional", false)):
				next = passage.from_id
			if next.is_empty() or first.has(next):
				continue
			var place: Dictionary = places.get(next, {})
			var allowed: bool = phase in passage.get("open_phases", []) and (place.get("node_type") == "region" or phase in place.get("open_phases", []))
			for tag in passage.get("required_access_tags", []):
				allowed = allowed and tag in access
			for tag in place.get("access_tags", []):
				allowed = allowed and tag in access
			if not allowed and not (current == passage.to_id and bool(passage.get("exit_always_allowed", false))):
				continue
			first[next] = String(passage.passage_id) if current == start else first[current]
			if next == destination:
				return String(first[next])
			frontier.append(next)
	return ""


func _execute() -> void:
	_pending = true
	_refresh_detail()
	SimulationBridge.operate_campus_inventory(_action(), {
		"shop_id": _selected(shop_picker), "item_id": _selected(item_picker),
		"quantity": int(quantity.value), "target_id": _selected(target_picker),
	})


func _completed(_success: bool, result: Dictionary) -> void:
	_pending = false
	feedback.text = String((result.get("result", {}) as Dictionary).get("message", result.get("error", "操作失败")))
	refresh()
