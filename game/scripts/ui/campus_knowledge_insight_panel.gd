extends VBoxContainer
## Knowledge tactics are always accessible, never lost in the draw pile.

signal use_requested(parameters: Dictionary)
var picker: OptionButton
var use_button: Button
var hint: Label
var _options: Array = []


func _init() -> void:
	var label := Label.new()
	label.text = "知识洞察区 · 不占共享手牌"
	add_child(label)
	picker = OptionButton.new()
	picker.fit_to_longest_item = false
	picker.item_selected.connect(func(_index): _details())
	add_child(picker)
	use_button = Button.new()
	use_button.text = "运用洞察"
	use_button.pressed.connect(func():
		if not use_button.disabled and picker.selected >= 0:
			var option: Dictionary = _options[picker.selected]
			use_requested.emit({"source_actor_id": option.source_actor_id, "target_id": option.target_id, "tactic": option.tactic})
	)
	add_child(use_button)
	hint = Label.new()
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(hint)
	refresh({})


func refresh(battle: Dictionary) -> void:
	var previous: Dictionary = _options[picker.selected] if picker.selected >= 0 and picker.selected < _options.size() else {}
	_options = battle.get("action_options", {}).get("insights", [])
	picker.clear()
	for index in range(_options.size()):
		var option: Dictionary = _options[index]
		picker.add_item("%s · %s → %s · %d费" % [option.source_name, option.name, option.target_name, int(option.command_cost)])
		if option.source_actor_id == previous.get("source_actor_id") and option.target_id == previous.get("target_id") and option.tactic == previous.get("tactic"):
			picker.select(index)
	_details()


func _details() -> void:
	picker.disabled = _options.is_empty()
	use_button.disabled = true
	if _options.is_empty():
		hint.text = "己方回合且对应现象理解达到 25/50/75，可辨析规律、标记弱点或打断。通过阅读、真实案例、运用和反思获得理解。"
		return
	var option: Dictionary = _options[picker.selected]
	use_button.disabled = not option.playable
	use_button.text = "%s · %d指令" % [option.name, int(option.command_cost)]
	var descriptions := {"observe": "读取目标当前真实位置、速度和污染强度。", "expose": "标记真实弱点；本战命中该弱点额外增伤15%。", "interrupt": "阻止目标下一次攻击，不解除其后续威胁。"}
	hint.text = "理解 %d/100。%s 每角色对每目标每项洞察每战一次。%s" % [int(option.mastery), descriptions.get(option.tactic, ""), "此项已使用。" if option.used else ("指令或状态不满足。" if not option.playable else "")]
