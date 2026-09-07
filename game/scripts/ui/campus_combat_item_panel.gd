extends VBoxContainer
## Projection-only controls; all eligibility, cost and healing are server-owned.

signal use_requested(parameters: Dictionary)

var item_picker: OptionButton
var target_picker: OptionButton
var use_button: Button
var hint: Label
var _options: Array = []


func _init() -> void:
	var title := Label.new()
	title.text = "战斗物品 · 使用者自己的库存"
	add_child(title)
	item_picker = OptionButton.new()
	item_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	item_picker.clip_text = true
	item_picker.item_selected.connect(func(_index: int): _refresh_targets())
	add_child(item_picker)
	var row := HBoxContainer.new()
	target_picker = OptionButton.new()
	target_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	target_picker.clip_text = true
	row.add_child(target_picker)
	use_button = Button.new()
	use_button.text = "用药 · 1 指令"
	use_button.pressed.connect(_use_item)
	row.add_child(use_button)
	add_child(row)
	hint = Label.new()
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hint.add_theme_font_size_override("font_size", 13)
	add_child(hint)
	refresh({})


func refresh(battle: Dictionary) -> void:
	var previous := _selected_option()
	_options = battle.get("action_options", {}).get("items", [])
	item_picker.clear()
	for index in range(_options.size()):
		var option: Dictionary = _options[index]
		item_picker.add_item("%s · %s × %d" % [option.source_name, option.name, int(option.quantity)])
		if option.get("source_actor_id") == previous.get("source_actor_id") and option.get("item_id") == previous.get("item_id"):
			item_picker.select(index)
	item_picker.disabled = _options.is_empty()
	_refresh_targets()


func _selected_option() -> Dictionary:
	if item_picker != null and item_picker.selected >= 0 and item_picker.selected < _options.size():
		return _options[item_picker.selected]
	return {}


func _refresh_targets() -> void:
	var previous: String = ""
	if target_picker.selected >= 0:
		previous = String(target_picker.get_item_metadata(target_picker.selected))
	target_picker.clear()
	var option := _selected_option()
	for target in option.get("targets", []):
		var index := target_picker.item_count
		target_picker.add_item("%s · 恢复 %d 生命" % [target.name, int(target.heal_amount)])
		target_picker.set_item_metadata(index, target.actor_id)
		if String(target.actor_id) == previous:
			target_picker.select(index)
	target_picker.disabled = target_picker.item_count == 0
	use_button.disabled = not bool(option.get("playable", false)) or target_picker.item_count == 0
	use_button.tooltip_text = "消耗使用者的一份药品与小队 1 点指令；仅同排或相邻排的受伤队友，不复活、不消除月光污染。"
	if option.is_empty():
		hint.text = "己方回合可用药；当前没有可行动队员携带治疗药品。出发前可到校园药房购买。"
	elif target_picker.item_count == 0:
		hint.text = "没有同排或相邻排、仍可行动的受伤队友，不会浪费药品。"
	elif not bool(option.get("playable", false)):
		hint.text = "小队指令点不足；药品未消耗。"
	else:
		hint.text = "按目标最大生命值恢复 %d%%，不超过上限。治疗不复活、不清除污染；库存消耗与伤势会带到下一场。" % int(option.get("heal_percent", 0))


func _use_item() -> void:
	if use_button.disabled or target_picker.selected < 0:
		return
	var option := _selected_option()
	use_requested.emit({"source_actor_id": option.source_actor_id,
		"item_id": option.item_id,
		"target_id": String(target_picker.get_item_metadata(target_picker.selected)), "quantity": 1})
