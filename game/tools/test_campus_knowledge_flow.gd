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
		if picker.get_item_text(index).contains("打断异常"):
			picker.select(index)
			break
	picker.item_selected.emit(picker.selected)
	assert(panel.get("use_button").text.contains("打断异常"))
	panel.get("use_button").pressed.emit()
	assert(panel.get("use_button").disabled)
	var completed = await bridge.campus_combat_operation_completed
	assert(completed[0], JSON.stringify(completed))
	await process_frame
	assert(bridge.get("campus_snapshot").combat.active_battle.command_points["party:player"] == 1)
	assert(panel.get("hint").text.contains("此项已使用"))
	phone.get("_combat_end_round_action").pressed.emit()
	completed = await bridge.campus_combat_operation_completed
	assert(completed[0], JSON.stringify(completed))
	await process_frame
	var current: Dictionary = bridge.get("campus_snapshot")
	assert(current.combat.active_battle.health == initial.combat.active_battle.health)
	assert(current.combat.active_battle.round == 2)
	assert(current.clock == initial.clock)
	assert(panel.get("use_button").disabled)
	phone.get("_app_scroll").ensure_control_visible(panel.get("hint"))
	await process_frame
	if OS.get_environment("GODOT_KNOWLEDGE_INSPECT") == "1":
		print("CAMPUS_KNOWLEDGE_INSPECT_READY")
		await create_timer(45).timeout
	print("CAMPUS_KNOWLEDGE_FLOW_OK explicit_threshold_fixture real_tactic cost enemy_attack_interrupted once_per_battle")
	quit(0)
