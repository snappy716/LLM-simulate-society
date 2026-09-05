extends SceneTree

const COLLAB_SCENE := "res://scenes/campus/campus_collab_test.tscn"


func _initialize() -> void:
	call_deferred("_run_flow")


func _run_flow() -> void:
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(100):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())

	var packed := load(COLLAB_SCENE) as PackedScene
	assert(packed != null)
	var scene = packed.instantiate()
	root.add_child(scene)
	current_scene = scene
	await process_frame

	bridge.call("advance_campus_phase")
	var afternoon = await bridge.campus_phase_advanced
	assert(bool(afternoon[0]), "advance to afternoon failed: %s" % afternoon[1])
	bridge.call("advance_campus_phase")
	var evening = await bridge.campus_phase_advanced
	assert(bool(evening[0]), "advance to evening failed: %s" % evening[1])
	bridge.call("operate_campus_night_world", "ENTER_NIGHT_WORLD")
	var entered = await bridge.campus_night_world_operation_completed
	assert(bool(entered[0]), "night entry failed: %s" % entered[1])

	var task: Dictionary = {}
	for value in (bridge.get("campus_snapshot") as Dictionary).get("tasks", {}).values():
		if value is Dictionary and value.get("forum") == "night" and value.get("state") in ["open", "viewed", "considering"]:
			task = value
			break
	assert(not task.is_empty())
	bridge.call("operate_campus_task", "CLAIM_FORUM_TASK", String(task.get("task_id")), int(task.get("lock_revision", 0)))
	var claimed = await bridge.campus_task_operation_completed
	assert(bool(claimed[0]), "night task claim failed: %s" % claimed[1])
	bridge.call("fast_travel_campus", String(task.get("execution_region_id", "")))
	var travelled = await bridge.campus_fast_travel_completed
	assert(bool(travelled[0]) or String((travelled[1].get("result", {}) as Dictionary).get("code", "")) == "already_there")

	var phone = scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "combat", "夜战部署")
	var prepare := phone.get("_combat_prepare_action") as Button
	assert(not prepare.disabled)
	prepare.pressed.emit()
	var prepared = await bridge.campus_combat_operation_completed
	assert(bool(prepared[0]), "combat prepare failed: %s" % prepared[1])

	var row_picker := phone.get("_combat_row_picker") as OptionButton
	row_picker.select(2)
	var deploy := phone.get("_combat_deploy_action") as Button
	deploy.pressed.emit()
	var deployed = await bridge.campus_combat_operation_completed
	assert(bool(deployed[0]), "combat deploy failed: %s" % deployed[1])
	var confirm := phone.get("_combat_confirm_action") as Button
	assert(not confirm.disabled)
	confirm.pressed.emit()
	var confirmed = await bridge.campus_combat_operation_completed
	assert(bool(confirmed[0]), "combat confirm failed: %s" % confirmed[1])

	var start := phone.get("_combat_start_action") as Button
	assert(not start.disabled)
	start.pressed.emit()
	var started = await bridge.campus_combat_operation_completed
	assert(bool(started[0]), "card combat start failed: %s" % started[1])
	var battle: Dictionary = ((bridge.get("campus_snapshot") as Dictionary).get("combat", {}) as Dictionary).get("active_battle", {})
	assert(String(battle.get("phase", "")) == "player_turn")
	assert(int(battle.get("round", 0)) == 1)
	assert(int(battle.get("command_point_cap", 0)) == 3)
	assert((battle.get("actor_decks", {}) as Dictionary).get("player", []).size() == 8)
	assert((battle.get("shared_hand_ids", []) as Array).size() == 2)
	var hand_detail := phone.get("_combat_hand_detail") as RichTextLabel
	assert(hand_detail.text.contains("共享指令点 3/3"))

	var end_round := phone.get("_combat_end_round_action") as Button
	assert(not end_round.disabled)
	end_round.pressed.emit()
	var ended = await bridge.campus_combat_operation_completed
	assert(bool(ended[0]), "combat round end failed: %s" % ended[1])
	battle = ((bridge.get("campus_snapshot") as Dictionary).get("combat", {}) as Dictionary).get("active_battle", {})
	assert(int(battle.get("round", 0)) == 2)
	assert(int(battle.get("command_point_cap", 0)) == 4)
	assert((battle.get("discard_piles", {}) as Dictionary).get("player", []).size() == 2)
	assert((battle.get("shared_hand_ids", []) as Array).size() == 2)
	assert(hand_detail.text.contains("共享指令点 4/4"))

	print("CAMPUS_COMBAT_ROUND_FLOW_OK")
	phone.call("_set_open", false)
	current_scene.queue_free()
	current_scene = null
	await process_frame
	quit(0)
