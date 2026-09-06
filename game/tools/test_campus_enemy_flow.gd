extends SceneTree


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
	assert(bridge.get("campus_snapshot").player.vitals.health == 1, "requires explicit one-HP enemy fixture")
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "combat", "夜战部署")
	assert(phone.get("_combat_formation_detail").text.contains("意图：攻击"))
	assert(phone.get("_combat_formation_detail").text.contains("生命 1/"))
	var end_round: Button = phone.get("_combat_end_round_action")
	assert(not end_round.disabled)
	end_round.pressed.emit()
	var ended = await bridge.campus_combat_operation_completed
	assert(ended[0], "enemy turn failed")
	await process_frame
	await process_frame
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(snapshot.clock.day == 2 and snapshot.clock.phase == "morning")
	assert(snapshot.player.vitals.health == snapshot.player.vitals.max_health)
	assert(snapshot.player.vitals.focus == snapshot.player.vitals.max_focus)
	assert(snapshot.combat.active_battle == null)
	assert(phone.get("_combat_feedback").text.contains("小队败北"))
	assert(phone.get("_combat_formation_detail").text.contains("上次战斗结果"))
	var location_id: String = snapshot.player.current_location_id
	var region_id: String = snapshot.places[location_id].get("region_id", location_id)
	assert(region_id in root.get_node("CampusPresentation").call("get_map").visible_region_ids)
	assert(phone.get("_combat_start_action").disabled)
	print("CAMPUS_ENEMY_FLOW_OK explicit_one_hp_fixture real_intent damage defeat next_morning_full_recovery dorm_map")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
