extends VBoxContainer
## Persistent expedition resources, not a second Godot-side HP ledger.

var detail: RichTextLabel
var rest_button: Button
var home_button: Button
var _home_passage := ""
var skill_picker: OptionButton
var target_picker: OptionButton
var heal_button: Button
var feedback: Label
var _pending := false


func _ready() -> void:
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	detail = RichTextLabel.new()
	detail.size_flags_vertical = Control.SIZE_EXPAND_FILL
	add_child(detail)
	home_button = Button.new()
	home_button.text = "沿道路 / 入口返回住处（下一段）"
	home_button.pressed.connect(func(): SimulationBridge.traverse_campus_passage(_home_passage))
	add_child(home_button)
	rest_button = Button.new()
	rest_button.text = "在住处充分休息（1 次主要行动）"
	rest_button.pressed.connect(func(): _send("REST", {}))
	add_child(rest_button)
	skill_picker = OptionButton.new()
	add_child(skill_picker)
	target_picker = OptionButton.new()
	add_child(target_picker)
	heal_button = Button.new()
	heal_button.text = "使用战斗间恢复技能"
	heal_button.pressed.connect(_heal)
	add_child(heal_button)
	feedback = Label.new()
	feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(feedback)
	SimulationBridge.campus_snapshot_updated.connect(func(_snapshot): refresh())
	SimulationBridge.campus_inventory_operation_completed.connect(_completed)
	refresh()


func refresh() -> void:
	var snapshot: Dictionary = SimulationBridge.campus_snapshot
	var player: Dictionary = snapshot.get("player", {})
	var vitals: Dictionary = player.get("vitals", {})
	var home: Dictionary = (snapshot.get("places", {}) as Dictionary).get(player.get("home_location_id", ""), {})
	var budget := int((player.get("action_budget", {}) as Dictionary).get("major_remaining", 0))
	_home_passage = preload("res://scripts/ui/campus_inventory_panel.gd")._route_first_passage(String(player.get("home_location_id", "")))
	home_button.disabled = _pending or _home_passage.is_empty() or bool((snapshot.get("economy", {}) as Dictionary).get("battle_locked", false))
	var full: bool = vitals.get("health", 0) == vitals.get("max_health", 0) and vitals.get("focus", 0) == vitals.get("max_focus", 0)
	rest_button.disabled = _pending or full or not bool(player.get("can_rest_recover", false)) or budget <= 0
	var lines := PackedStringArray([
		"生命：%d / %d" % [int(vitals.get("health", 0)), int(vitals.get("max_health", 0))],
		"专注：%d / %d" % [int(vitals.get("focus", 0)), int(vitals.get("max_focus", 0))],
		"多场战斗继承损耗；换场、返校不自动回满。",
		"表世界在 %s 充分休息，生命/专注全部恢复。" % home.get("name", "住处"),
		"主要行动剩余：%d；污染按原规则处理。" % budget,
	])
	if not bool(player.get("can_rest_recover", false)):
		lines.append("请先回到表世界的住处；战斗和里世界不能靠休息回血。")
	var options: Array = player.get("field_recovery_options", [])
	var previous := skill_picker.selected
	skill_picker.clear()
	for option in options:
		skill_picker.add_item("%s · %s（专注 %d）" % [option.caster_name, option.name, int(option.focus_cost)])
		skill_picker.set_item_metadata(skill_picker.item_count - 1, option)
	if previous >= 0 and previous < skill_picker.item_count:
		skill_picker.select(previous)
	var previous_target := "player"
	if target_picker.selected >= 0:
		previous_target = String(target_picker.get_item_metadata(target_picker.selected))
	target_picker.clear()
	target_picker.add_item("自己")
	target_picker.set_item_metadata(0, "player")
	for actor_id in (snapshot.get("economy", {}) as Dictionary).get("nearby_actor_ids", []):
		var actor: Dictionary = (snapshot.get("population", {}) as Dictionary).get(actor_id, {})
		target_picker.add_item(String(actor.get("display_name", actor_id)))
		target_picker.set_item_metadata(target_picker.item_count - 1, actor_id)
		if actor_id == previous_target:
			target_picker.select(target_picker.item_count - 1)
	heal_button.disabled = _pending or options.is_empty() or bool((snapshot.get("economy", {}) as Dictionary).get("battle_locked", false))
	if options.is_empty():
		lines.append("现场没有自己或队友已掌握的恢复技能。绷带可在商城背包中使用。")
	lines.append("\n生活需求")
	for key in (player.get("needs", {}) as Dictionary):
		lines.append("%s：%s" % [key, player.needs[key]])
	detail.text = "\n".join(lines)


func _heal() -> void:
	if skill_picker.selected < 0:
		return
	var option: Dictionary = skill_picker.get_item_metadata(skill_picker.selected)
	_send("USE_RECOVERY_SKILL", {"caster_id": option.caster_id, "skill_id": option.skill_id, "target_id": target_picker.get_item_metadata(target_picker.selected)})


func _send(action: String, parameters: Dictionary) -> void:
	_pending = true
	refresh()
	SimulationBridge.operate_campus_inventory(action, parameters)


func _completed(_success: bool, result: Dictionary) -> void:
	if not _pending:
		return
	_pending = false
	feedback.text = String((result.get("result", {}) as Dictionary).get("message", result.get("error", "操作失败")))
	refresh()
