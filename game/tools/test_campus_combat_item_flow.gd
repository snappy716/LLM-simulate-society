extends SceneTree
## Rendered inventory -> combat medicine -> shared vitals and command point flow.


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	var initial: Dictionary = bridge.get("campus_snapshot")
	var option: Dictionary = initial.combat.active_battle.action_options.items[0]
	assert(option.quantity == 2)
	assert(option.playable)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "combat", "夜战部署")
	var panel: Control = phone.get("_combat_items")
	var button: Button = panel.get("use_button")
	assert(not button.disabled)
	assert(panel.get("item_picker").get_item_text(0).contains("医用绷带"))
	assert(panel.get("hint").text.contains("不复活"))
	phone.get("_app_scroll").ensure_control_visible(button)
	await process_frame
	button.pressed.emit()
	assert(button.disabled, "pending request must lock item button")
	var completed = await bridge.campus_combat_operation_completed
	assert(completed[0], "combat item request failed")
	await process_frame
	await process_frame
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	var battle: Dictionary = snapshot.combat.active_battle
	assert(battle.health.player == initial.combat.active_battle.health.player + option.targets[0].heal_amount)
	assert(battle.command_points["party:player"] == initial.combat.active_battle.command_points["party:player"] - 1)
	assert(battle.action_options.items[0].quantity == 1)
	assert(snapshot.clock == initial.clock)
	assert(phone.get("_combat_feedback").text.contains("恢复"))
	assert(panel.get("item_picker").get_item_text(0).contains("× 1"))
	phone.get("_app_scroll").ensure_control_visible(panel.get("hint"))
	await process_frame
	# Keep the rendered result inspectable for desktop UI QA when requested.
	if OS.get_environment("GODOT_COMBAT_ITEM_INSPECT") == "1":
		print("CAMPUS_COMBAT_ITEM_INSPECT_READY")
		await create_timer(45).timeout
	print("CAMPUS_COMBAT_ITEM_FLOW_OK real_pharmacy_stock healing command_cost pending_lock rendered_feedback")
	quit(0)
