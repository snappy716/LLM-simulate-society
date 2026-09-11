extends CanvasLayer
## Dedicated presentation, using the phone's existing command controller.
const KIT = preload("res://scripts/ui/campus_ui_kit.gd")
const ART = preload("res://scripts/ui/campus_ui_art.gd")
const ROWS := {"front": "前排", "middle": "中排", "back": "后排"}
var controller: Node
var overlay: Control
var body: VBoxContainer
var arena: GridContainer
var hand: HBoxContainer
var heading: Label
var receipt: Label
var footer: HBoxContainer
var source_parent: Node
var source_index := 0
var opened := false
var actions: Dictionary = {}
var hidden_huds: Array[WeakRef] = []
var render_key := ""
var deploy_buttons: Dictionary = {}
var hand_heading: Label

func _ready() -> void:
	layer = 25
	process_mode = Node.PROCESS_MODE_ALWAYS
	controller = get_parent()
	overlay = ColorRect.new()
	overlay.color = Color("091b2bea")
	overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(overlay)
	var margin := MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	for side in ["left", "right", "top", "bottom"]: margin.add_theme_constant_override("margin_" + side, 20)
	overlay.add_child(margin)
	var column := VBoxContainer.new()
	margin.add_child(column)
	heading = KIT.label("月下行动", 23)
	column.add_child(heading)
	var scroll := KIT.scroll_body()
	column.add_child(scroll)
	body = VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(body)
	arena = GridContainer.new()
	arena.columns = 3
	body.add_child(arena)
	hand_heading = KIT.label("共享手牌 · 先选牌，再选高亮目标，最后确认出牌", 16)
	body.add_child(hand_heading)
	var hand_scroll := ScrollContainer.new()
	hand_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	hand_scroll.follow_focus = true
	hand_scroll.custom_minimum_size.y = 128
	body.add_child(hand_scroll)
	hand = HBoxContainer.new()
	hand_scroll.add_child(hand)
	receipt = KIT.label("", 14)
	column.add_child(receipt)
	footer = HBoxContainer.new()
	column.add_child(footer)
	for entry in [["play", "确认出牌", "_combat_play_card_action"], ["end", "结束本轮", "_combat_end_round_action"], ["confirm", "锁定阵型", "_combat_confirm_action"], ["start", "开始战斗", "_combat_start_action"]]:
		var button := KIT.button(entry[1], func():
			var source: Button = controller.get(entry[2])
			if not source.disabled and not controller.get("_combat_pending"):
				source.pressed.emit()
				refresh()
		, "primary" if entry[0] == "play" else "secondary")
		actions[entry[0]] = button
		footer.add_child(button)
	footer.add_child(KIT.button("返回终端", close_screen))
	overlay.hide()
	SimulationBridge.campus_snapshot_updated.connect(func(_snapshot): call_deferred("refresh"))
	SimulationBridge.campus_combat_operation_completed.connect(func(_success, _result, _action, _id): call_deferred("refresh"))

func open_screen() -> void:
	if opened: return
	opened = true
	var controls: Control = controller.get("_combat_root")
	source_parent = controls.get_parent()
	source_index = controls.get_index()
	controls.reparent(body)
	controls.get_child(0).hide()
	controller.get("_overlay").hide()
	for hud in get_tree().get_nodes_in_group("campus_hud"):
		if hud.visible:
			hidden_huds.append(weakref(hud))
			hud.hide()
	overlay.show()
	render_key = ""
	refresh()
	footer.get_child(footer.get_child_count() - 1).grab_focus()

func close_screen() -> void:
	if not opened: return
	opened = false
	var controls: Control = controller.get("_combat_root")
	controls.reparent(source_parent)
	controls.get_child(0).show()
	source_parent.move_child(controls, source_index)
	overlay.hide()
	controller.get("_overlay").show()
	for ref in hidden_huds:
		var hud = ref.get_ref()
		if is_instance_valid(hud): hud.show()
	hidden_huds.clear()
	controller.get("_back_button").grab_focus()

func _clear(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()

func refresh() -> void:
	if not opened: return
	var value: Variant = SimulationBridge.campus_snapshot.get("combat", {}).get("active_battle")
	var battle: Dictionary = value if value is Dictionary else {}
	var next_key := "%s:%s:%s:%s:%s:%s" % [battle.get("battle_id", ""), battle.get("revision", -1), controller.get("_selected_combat_card_id"), controller.get("_selected_character_card_id"), controller.get("_combat_pending"), controller.get("_combat_feedback").text]
	if next_key == render_key: return
	render_key = next_key
	var focused := get_viewport().gui_get_focus_owner()
	var focus_card := String(focused.get_meta("card_id", "")) if focused != null else ""
	var focus_target := String(focused.get_meta("target_id", "")) if focused != null else ""
	_clear(arena)
	_clear(hand)
	deploy_buttons.clear()
	var phase := String(battle.get("phase", ""))
	hand_heading.text = "人物牌 · 选择成员，再点击排位部署" if phase == "setup" else "共享手牌 · 先选牌，再选高亮目标，最后确认出牌"
	var phase_names := {"setup": "部署", "ready": "阵型已锁定", "player_turn": "我方行动", "enemy_turn": "敌方行动", "round_end": "轮次结算", "resolved": "战斗结束"}
	heading.text = "月下行动 · %s · 第 %d 轮 · 指令点 %d/%d" % [phase_names.get(phase, "尚未建立战斗"), int(battle.get("round", 0)), int(battle.get("command_points", {}).get("party:player", 0)), int(battle.get("command_point_cap", 0))]
	var options: Dictionary = battle.get("action_options", {}).get("cards", {}).get(controller.get("_selected_combat_card_id"), {})
	var targets: Array = options.get("target_ids", []) if options.get("playable", false) else []
	for enemy in [true, false]:
		for row in ROWS:
			var lane := VBoxContainer.new()
			lane.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			arena.add_child(lane)
			lane.add_child(KIT.label(("异常 · " if enemy else "我方 · ") + ROWS[row], 16))
			var units: Dictionary = battle.get("enemy_units", {}) if enemy else battle.get("character_cards", {})
			var count := 0
			for id in units:
				var unit: Dictionary = units[id]
				if unit.get("row") != row: continue
				count += 1
				var target_id := String(id if enemy else unit.get("actor_id", ""))
				var health := int(battle.get("enemy_health" if enemy else "health", {}).get(target_id, 0))
				var title := "%s\n生命 %d / %d" % [unit.get("display_name", "人物"), health, int(unit.get("max_health", 0))]
				if enemy:
					var intent: Dictionary = battle.get("enemy_intents", {}).get(id, {})
					if not intent.is_empty(): title += "\n意图：%s · 威力 %d" % [ROWS.get(intent.get("target_row"), "攻击"), int(intent.get("power", 0))]
				else: title += "\n护盾 %d · 月蚀 %d%%" % [int(battle.get("barriers", {}).get(target_id, 0)), int(battle.get("pollution", {}).get(target_id, 0))]
				var target_button := KIT.button(title, func(): _choose_target(target_id), "primary" if target_id in targets else "secondary")
				target_button.disabled = target_id not in targets or controller.get("_combat_pending")
				target_button.add_theme_color_override("font_disabled_color", KIT.INK)
				target_button.set_meta("target_id", target_id)
				target_button.icon = ART.icon("anomaly" if enemy else "character")
				target_button.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
				target_button.expand_icon = true
				target_button.add_theme_constant_override("icon_max_width", 34)
				lane.add_child(target_button)
				var bar := ProgressBar.new()
				bar.max_value = maxi(1, int(unit.get("max_health", 0)))
				bar.value = health
				bar.show_percentage = false
				bar.custom_minimum_size.y = 6
				lane.add_child(bar)
				if focus_target == target_id and not target_button.disabled: target_button.call_deferred("grab_focus")
			if count == 0: lane.add_child(KIT.label("—", 14))
			if not enemy and phase == "setup":
				var deploy := KIT.button("部署到" + ROWS[row], func():
					controller.get("_combat_row_picker").select(ROWS.keys().find(row))
					var source: Button = controller.get("_combat_deploy_action")
					if not source.disabled and not controller.get("_combat_pending"): source.pressed.emit()
					refresh()
				)
				deploy.disabled = controller.get("_combat_deploy_action").disabled or controller.get("_combat_pending")
				lane.add_child(deploy)
				deploy_buttons[row] = deploy
	if phase == "setup":
		var candidates: OptionButton = controller.get("_combat_character_picker")
		for index in range(candidates.item_count):
			var id := String(candidates.get_item_metadata(index))
			var unit: Dictionary = battle.get("character_cards", {}).get(id, {})
			var character := KIT.button("%s\n生命上限 %d\n%s" % [unit.get("display_name", "人物牌"), int(unit.get("max_health", 0)), ROWS.get(unit.get("row"), "候选")], func():
				candidates.select(index)
				candidates.item_selected.emit(index)
				refresh()
			, "primary" if id == controller.get("_selected_character_card_id") else "secondary")
			ART.decorate_card(character, "character", id == controller.get("_selected_character_card_id"))
			character.disabled = controller.get("_combat_pending")
			hand.add_child(character)
	var picker: OptionButton = controller.get("_combat_card_picker")
	for index in range(picker.item_count):
		var id := String(picker.get_item_metadata(index))
		var instance: Dictionary = battle.get("card_instances", {}).get(id, {})
		var option: Dictionary = battle.get("action_options", {}).get("cards", {}).get(id, {})
		var card := KIT.button(picker.get_item_text(index).replace(" · ", "\n"), func():
			picker.select(index)
			picker.item_selected.emit(index)
			refresh()
		, "primary" if id == controller.get("_selected_combat_card_id") else "secondary")
		ART.decorate_card(card, ART.effect_kind(instance.get("effect_ids", [])), id == controller.get("_selected_combat_card_id"))
		card.tooltip_text = "可选目标与费用以当前规则校验为准。" if option.get("playable", false) else "当前不可出牌，可在下方查看具体条件。"
		card.tooltip_text += "\n基础效力 %d（非最终伤害）；作用范围 %s。" % [int(instance.get("base_power", 0)), {"any_ally":"任意友方", "any_enemy":"任意敌方", "frontmost_enemy":"最前排敌方", "front_two_enemy_rows":"前两排敌方", "same_or_adjacent_ally":"同排或相邻排友方"}.get(String(instance.get("range_pattern", "")), "依卡牌规则")]
		card.disabled = controller.get("_combat_pending")
		card.set_meta("card_id", id)
		hand.add_child(card)
		if focus_card == id and not card.disabled: card.call_deferred("grab_focus")
	if hand.get_child_count() == 0: hand.add_child(KIT.label("开战并抽牌后显示手牌。" if phase in ["setup", "ready", ""] else "当前没有手牌，可使用下方基础指令或结束本轮。", 14))
	for entry in [["play", "_combat_play_card_action"], ["end", "_combat_end_round_action"], ["confirm", "_combat_confirm_action"], ["start", "_combat_start_action"]]:
		var source: Button = controller.get(entry[1])
		actions[entry[0]].disabled = source.disabled or controller.get("_combat_pending")
		actions[entry[0]].tooltip_text = source.tooltip_text
		actions[entry[0]].visible = (entry[0] == "play" or entry[0] == "end") if phase == "player_turn" else (entry[0] == "confirm" if phase == "setup" else entry[0] == "start" and phase == "ready")
	receipt.text = controller.get("_combat_feedback").text
	if controller.get("_combat_pending"): receipt.text = "正在核验与结算，请勿重复操作……"

func _choose_target(id: String) -> void:
	var picker: OptionButton = controller.get("_combat_card_target_picker")
	for index in range(picker.item_count):
		if String(picker.get_item_metadata(index)) == id:
			picker.select(index)
			receipt.text = "目标已选：%s · 点击确认出牌才执行。" % picker.get_item_text(index)
			return
