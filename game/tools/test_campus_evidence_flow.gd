extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	var initial: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "combat", "夜战部署")
	var panel: Control = phone.get("_combat_insights")
	var picker: OptionButton = panel.get("picker")
	for index in range(picker.item_count):
		if picker.get_item_text(index).contains("现实参照"):
			picker.select(index)
			break
	picker.item_selected.emit(picker.selected)
	assert(panel.get("use_button").text.contains("现实参照"))
	assert(panel.get("hint").text.contains("全队每战一次"))
	assert(panel.get("hint").text.contains("不解决当事人的心结"))
	panel.get("use_button").pressed.emit()
	assert(panel.get("use_button").disabled)
	var completed = await bridge.campus_combat_operation_completed
	assert(completed[0], JSON.stringify(completed))
	await process_frame
	var battle: Dictionary = bridge.get("campus_snapshot").combat.active_battle
	assert(battle.command_points["party:player"] == 2)
	assert(not battle.has("anomaly_origin") and not battle.has("evidence_insight_receipts"))
	assert(panel.get("hint").text.contains("此项已使用"))
	phone.get("_combat_end_round_action").pressed.emit()
	completed = await bridge.campus_combat_operation_completed
	assert(completed[0], JSON.stringify(completed))
	await process_frame
	var current: Dictionary = bridge.get("campus_snapshot")
	assert(current.combat.active_battle.health == initial.combat.active_battle.health)
	assert(current.combat.active_battle.pollution == initial.combat.active_battle.pollution)
	assert(current.clock == initial.clock)
	assert(panel.get("use_button").disabled)
	print("CAMPUS_EVIDENCE_FLOW_OK actual_shared_experience real_card_battle one_command skipped_attack no_remote_cure private_source no_api")
	quit(0)
