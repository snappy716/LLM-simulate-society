extends SceneTree
## Real enemy turn crosses the first persistent pollution threshold.


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
	assert(initial.combat.active_battle.pollution.player == 29)
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "combat", "夜战部署")
	assert(phone.get("_combat_formation_detail").text.contains("污染 29%"))
	assert(phone.get("_combat_formation_detail").text.contains("意图：攻击"))
	assert(phone.get("_combat_formation_detail").text.contains("污染 2"))
	var end_round: Button = phone.get("_combat_end_round_action")
	end_round.pressed.emit()
	var completed = await bridge.campus_combat_operation_completed
	assert(completed[0], "enemy pollution turn failed")
	await process_frame
	await process_frame
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	var pollution := int(snapshot.combat.active_battle.pollution.player)
	assert(pollution >= 30)
	assert(snapshot.night_world.pollution == pollution)
	assert("pollution_noticeable" in snapshot.combat.active_battle.statuses.player)
	assert(phone.get("_combat_formation_detail").text.contains("月蚀显现"))
	assert(phone.get("_combat_formation_detail").text.contains("污染 %d%%" % pollution))
	print("CAMPUS_POLLUTION_FLOW_OK real_enemy_intent persistent_gain threshold_status rendered_feedback")
	quit(0)
