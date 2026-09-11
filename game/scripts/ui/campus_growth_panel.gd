extends VBoxContainer
## Courses, source-tracked understanding and actor-bound deck configuration.

var topic: OptionButton
var detail: RichTextLabel
var reason: Label
var feedback: Label
var read: Button
var reflect: Button
var focus: Button
var actor: OptionButton
var slots: Array[OptionButton] = []
var save_deck: Button
var _data: Dictionary = {}
var _pending := false
var _dirty := false
var _loaded_actor := ""
var _cards_only := false
var _catalog_detail: RichTextLabel
var catalog_grid: GridContainer


func _ready() -> void:
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	topic = _picker(self)
	topic.item_selected.connect(func(_index): _details())
	detail = RichTextLabel.new()
	detail.custom_minimum_size.y = 235
	detail.bbcode_enabled = false
	add_child(detail)
	reason = Label.new()
	reason.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(reason)
	var row := HBoxContainer.new()
	add_child(row)
	read = _button(row, "阅读 · 1 行动", func(): _send("READ_KNOWLEDGE", {"topic_id": _selected(topic)}))
	reflect = _button(row, "反思 · 1 行动", func(): _send("REFLECT_ON_CASE", {"topic_id": _selected(topic)}))
	focus = _button(self, "设为当前研习主题 · 免费", func(): _send("SET_STUDY_FOCUS", {"topic_id": _selected(topic)}))
	var heading := Label.new()
	heading.text = "个人八张牌组 · 开战前配置"
	add_child(heading)
	actor = _picker(self)
	actor.item_selected.connect(func(_index):
		_dirty = false
		_loaded_actor = ""
		_load_deck()
		_details()
	)
	for index in range(8):
		var picker := _picker(self)
		picker.item_selected.connect(func(_value): _dirty = true)
		slots.append(picker)
	save_deck = _button(self, "保存该角色牌组 · 免费", _save_deck)
	feedback = Label.new()
	feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(feedback)
	_catalog_detail = RichTextLabel.new()
	_catalog_detail.fit_content = true
	_catalog_detail.scroll_active = false
	_catalog_detail.visible = false
	add_child(_catalog_detail)
	catalog_grid = GridContainer.new()
	catalog_grid.columns = 2
	catalog_grid.visible = false
	add_child(catalog_grid)
	SimulationBridge.campus_snapshot_updated.connect(func(_snapshot):
		if visible:
			refresh()
	)
	SimulationBridge.campus_growth_operation_completed.connect(_completed)
	refresh()


func _picker(parent: Node) -> OptionButton:
	var picker := OptionButton.new()
	picker.fit_to_longest_item = false
	parent.add_child(picker)
	return picker


func _button(parent: Node, title: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = title
	button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	button.pressed.connect(action)
	parent.add_child(button)
	return button


func _selected(picker: OptionButton) -> String:
	return String(picker.get_item_metadata(picker.selected)) if picker.selected >= 0 else ""


func _deck_actor() -> Dictionary:
	for item in _data.get("deck_actors", []):
		if item.actor_id == _selected(actor):
			return item
	return {}


func refresh() -> void:
	_data = SimulationBridge.campus_snapshot.get("growth", {})
	var previous := _selected(topic)
	topic.clear()
	for item in _data.get("topics", []):
		var index := topic.item_count
		topic.add_item("%s · %d / 100" % [item.name, int(item.mastery)])
		topic.set_item_metadata(index, item.topic_id)
		if item.topic_id == previous:
			topic.select(index)
	previous = _selected(actor)
	actor.clear()
	for item in _data.get("deck_actors", []):
		var index := actor.item_count
		actor.add_item(String(item.name))
		actor.set_item_metadata(index, item.actor_id)
		if item.actor_id == previous:
			actor.select(index)
	_load_deck()
	_details()


func _load_deck() -> void:
	var entry := _deck_actor()
	if _dirty and _loaded_actor == _selected(actor):
		return
	_loaded_actor = _selected(actor)
	var catalog: Array = entry.get("catalog", [])
	var chosen: Array = entry.get("deck_ids", []).duplicate()
	if chosen.is_empty() and not catalog.is_empty():
		chosen = ["general:brace", "general:center"]
		for card in catalog:
			if String(card.card_id).begins_with("college:") and chosen.size() < 8:
				chosen.append(card.card_id)
		while chosen.size() < 8:
			chosen.append("general:steady_action")
	for index in range(slots.size()):
		var picker := slots[index]
		picker.clear()
		for card in catalog:
			var option := picker.item_count
			picker.add_item("%d · %s · %d 费" % [index + 1, card.name, int(card.command_cost)])
			picker.set_item_metadata(option, card.card_id)
			if index < chosen.size() and card.card_id == chosen[index]:
				picker.select(option)


func _details() -> void:
	if save_deck == null:
		return
	var selected: Dictionary = {}
	for item in _data.get("topics", []):
		if item.topic_id == _selected(topic):
			selected = item
	var lines := PackedStringArray([String(_data.get("rule_note", "正在连接……")), ""])
	if not selected.is_empty():
		var parts: Dictionary = selected.components
		lines.append("%s · %s\n理论 %d/40 · 案例 %d/30\n应用 %d/20 · 反思 %d/10\n对应异常增伤：%s%%" % [selected.book_title, selected.name, parts.theory, parts.cases, parts.application, parts.reflection, selected.damage_bonus_percent])
		lines.append("25：辨析规律 · 50：标记弱点\n75：打断异常 · 100：特殊解法知识条件（具体对象后续接入）")
		lines.append("当前研习主题" if selected.is_focus else "可设为研习主题，结合课程和研究积累理论")
	lines.append("\n基础属性与练习积累：")
	var names := {"physique": "体魄", "dexterity": "灵巧", "focus": "专注", "insight": "洞察", "empathy": "共情", "expression": "表达"}
	for key in _data.get("attributes", {}):
		var value := int(_data.attributes[key])
		lines.append("%s %d · 练习 %d/%d" % [names.get(key, key), value, int(_data.get("attribute_practice", {}).get(key, 0)), 8 + value * 2])
	lines.append("\n最近理解收益（有来源记录）：")
	var history: Array = _data.get("history", [])
	for index in range(maxi(0, history.size() - 4), history.size()):
		var item: Dictionary = history[index]
		var components := {"theory": "理论", "cases": "案例", "application": "应用", "reflection": "反思"}
		lines.append("第 %d 天：%s +%d" % [int(item.day), components.get(item.component, item.component), int(item.gain)])
	detail.text = "\n".join(lines)
	reason.text = String(_data.get("study_reason", "当前无法学习"))
	var busy := _pending or bool(_data.get("battle_locked", false))
	read.disabled = busy or not selected.get("can_read", false)
	reflect.disabled = busy or not selected.get("can_reflect", false)
	reflect.tooltip_text = "需理论至少20、亲历案例至少10、携带笔记本，且反思部分未完成。"
	focus.disabled = busy or selected.is_empty()
	topic.disabled = busy or topic.item_count == 0
	actor.disabled = busy or actor.item_count == 0
	save_deck.disabled = busy or not _deck_actor().get("can_configure", false)
	for picker in slots:
		picker.disabled = save_deck.disabled
	if _catalog_detail != null:
		for child in catalog_grid.get_children():
			catalog_grid.remove_child(child)
			child.queue_free()
		var card_lines := PackedStringArray(["该角色可用卡牌"])
		var effects := {"grant_guard": "获得护盾", "restore_focus": "恢复专注", "reveal_pattern": "辨析规律", "apply_disruption": "施加干扰", "deal_physical": "物理攻击", "deal_technique": "技巧攻击", "restore_health": "恢复生命", "specialization_effect": "专业特效", "knowledge_insight": "知识洞察"}
		var ranges := {"any_ally": "任意友方", "same_or_adjacent_ally": "同排或相邻排友方", "any_enemy": "任意敌方", "frontmost_enemy": "最前排敌方", "front_two_enemy_rows": "前两排敌方", "card_defined": "依卡牌情境"}
		for card in _deck_actor().get("catalog", []):
			var descriptions := PackedStringArray()
			for effect in card.get("effect_ids", []): descriptions.append(String(effects.get(effect, "特殊效果")))
			card_lines.append("%s · %d 费\n%s · 基础效力 %d · %s" % [card.name, int(card.command_cost), " / ".join(descriptions), int(card.get("base_power", 0)), ranges.get(card.get("range_pattern", ""), "依卡牌规则")])
			var tile := PanelContainer.new()
			tile.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			catalog_grid.add_child(tile)
			var margin := MarginContainer.new()
			for side in ["left", "top", "right", "bottom"]: margin.add_theme_constant_override("margin_" + side, 12)
			tile.add_child(margin)
			margin.add_child(preload("res://scripts/ui/campus_ui_kit.gd").label(card_lines[-1]))
		card_lines.append("基础效力不等于最终伤害；实际数值由战斗状态、知识与目标共同结算。")
		_catalog_detail.text = "\n\n".join(card_lines)


func set_cards_only(value: bool) -> void:
	_cards_only = value
	for control in [topic, detail, reason, read.get_parent(), focus]:
		control.visible = not value
	_catalog_detail.visible = false
	catalog_grid.visible = value
	var courses := get_node_or_null("PublicCourses")
	if courses != null: courses.visible = not value


func _save_deck() -> void:
	var cards: Array[String] = []
	for picker in slots:
		cards.append(_selected(picker))
	_send("CONFIGURE_ACTOR_DECK", {"card_actor_id": _selected(actor), "card_ids": cards})


func _send(action: String, parameters: Dictionary) -> void:
	if _pending:
		return
	_pending = true
	feedback.text = "正在提交……"
	_details()
	SimulationBridge.operate_campus_growth(action, parameters)


func _completed(success: bool, result: Dictionary) -> void:
	if not _pending:
		return
	_pending = false
	var outcome: Dictionary = result.get("result", {})
	feedback.text = ("完成：" if success else ("结果尚未确认：" if outcome.is_empty() else "未执行：")) + String(outcome.get("message", result.get("error", "请刷新核对最新状态。")))
	if success and outcome.get("payload", {}).has("card_ids"):
		_dirty = false
	refresh()
