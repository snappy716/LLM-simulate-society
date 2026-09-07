extends SceneTree
## Real HTTP retreat from the rendered combat page; no mocked combat result.


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			quit(1)
	)
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	var initial: Dictionary = bridge.get("campus_snapshot")
	assert(initial.combat.active_battle.phase == "player_turn")
	assert(initial.night_world.current_layer == "night")
	var initial_health := int(initial.player.vitals.health)
	var initial_clock: Dictionary = initial.clock.duplicate(true)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phase_panel := current_scene.get_node("UI/PhasePanel")
	phase_panel.call("_refresh_availability")
	assert(phase_panel.get_node("Margin/VBox/Advance").disabled)
	assert(phase_panel.get_node("Margin/VBox/Advance").tooltip_text.contains("正式战斗中"))
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "combat", "夜战部署")
	var retreat: Button = phone.get("_combat_retreat_action")
	assert(not retreat.disabled)
	assert(retreat.text.contains("承受追击"))
	retreat.pressed.emit()
	var completed = await bridge.campus_combat_operation_completed
	assert(completed[0], "retreat operation failed")
	var response: Dictionary = completed[1]
	assert(response.result.payload.result == "escaped")
	assert(response.result.payload.task_reopened)
	await process_frame
	await process_frame
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(snapshot.clock == initial_clock)
	assert(int(snapshot.player.vitals.health) < initial_health)
	assert(snapshot.combat.active_battle == null)
	assert(snapshot.night_world.current_layer == "surface")
	assert(phone.get("_combat_feedback").text.contains("撤回表世界"))
	assert(phone.get("_combat_formation_detail").text.contains("上次战斗结果"))
	assert(retreat.disabled)
	print("CAMPUS_RETREAT_FLOW_OK real_http pursuit_damage surface_return task_reopened phase_unchanged time_skip_blocked")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
