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
	var panel: Node = phone.get("_agenda_root").get_node("Bonds")
	var before: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	assert(panel.get("contacts").item_count < 200)
	var romance_ids: Array = []
	for row in before.agenda.bonds.records:
		if row.kind == "romance":
			assert(row.status == "pending")
			romance_ids.append(row.bond_id)
	assert(romance_ids.size() == 2)
	for bond_id in romance_ids:
		var history: OptionButton = panel.get("history")
		for i in range(history.item_count):
			if history.get_item_metadata(i) == bond_id: history.select(i)
		panel.call("_show_record")
		assert(not panel.get("accept").disabled)
		panel.get("accept").pressed.emit()
		assert(panel.get("accept").disabled)
		var response = await bridge.campus_bond_operation_completed
		assert(response[0], JSON.stringify(response[1]))
	var active := 0
	for row in bridge.get("campus_snapshot").agenda.bonds.records:
		if row.kind == "romance" and row.status == "active": active += 1
	assert(active == 2)
	assert(not panel.get("end_bond").disabled)
	panel.get("end_bond").pressed.emit()
	var ended = await bridge.campus_bond_operation_completed
	assert(ended[0], JSON.stringify(ended[1]))
	active = 0
	var after: Dictionary = bridge.get("campus_snapshot")
	for row in after.agenda.bonds.records:
		if row.kind == "romance" and row.status == "active": active += 1
	assert(active == 1)
	assert(after.clock == before.clock and after.action_economy == before.action_economy)
	assert(panel.get("detail").text.contains("不影响其他关系") or panel.get("detail").text.contains("不限制"))
	for viewport_size in [Vector2i(1280,720), Vector2i(1600,900), Vector2i(1920,1080)]:
		root.size = viewport_size
		await process_frame
		assert(panel.get("contacts").size.x <= panel.size.x + 1)
		assert(panel.get("end_bond").size.x <= panel.size.x + 1)
	print("CAMPUS_BONDS_FLOW_OK two_explicit_consents two_active_partners independent_ending private_history unchanged_clock_and_budget three_sizes no_api")
	quit(0)
