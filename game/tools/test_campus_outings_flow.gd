extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(100).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "agenda", "日程与约定")
	var panel: Node = phone.get("_agenda_root").get_node("Outings")
	var before: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	assert(before.agenda.outings.records[-1].status == "pending")
	assert(not panel.get("accept").disabled and panel.get("attend").disabled)
	assert(panel.get("contacts").item_count < 200)
	panel.get("accept").pressed.emit()
	assert(panel.get("accept").disabled)
	var accepted = await bridge.campus_outing_operation_completed
	assert(accepted[0], JSON.stringify(accepted[1]))
	assert(before.action_economy == bridge.get("campus_snapshot").action_economy)
	assert(phone.get("_agenda_root").get("detail").text.contains("已确认的共同活动"))
	bridge.call("advance_campus_phase")
	for _attempt in range(600):
		await create_timer(0.05).timeout
		if not bridge.call("is_campus_busy"): break
	var arrived: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	assert(arrived.clock.phase == "afternoon")
	assert(arrived.agenda.outings.records[-1].attended.size() == 1)
	assert(arrived.agenda.outings.records[-1].receipt == null)
	assert(not panel.get("attend").disabled)
	panel.get("attend").pressed.emit()
	var result = await bridge.campus_outing_operation_completed
	assert(result[0], JSON.stringify(result[1]))
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(after.clock == arrived.clock)
	assert(after.agenda.outings.records[-1].status == "completed")
	assert(after.player.action_budget.major_remaining == arrived.player.action_budget.major_remaining - 1)
	assert(panel.get("detail").text.contains("共同经历"))
	assert(panel.get("attend").disabled)
	assert(after.agenda.outings.records[-1].receipt.costs.keys() == ["player"])
	for viewport_size in [Vector2i(1280,720), Vector2i(1600,900), Vector2i(1920,1080)]:
		root.size = viewport_size
		await process_frame
		assert(panel.get("contacts").size.x <= panel.size.x + 1)
		assert(panel.get("attend").size.x <= panel.size.x + 1)
	print("CAMPUS_OUTINGS_FLOW_OK actual_incoming_invitation explicit_player_consent real_npc_arrival actual_shared_cost private_receipt three_sizes no_api")
	quit(0)
