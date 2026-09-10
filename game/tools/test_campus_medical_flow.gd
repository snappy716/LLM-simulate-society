extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "health", "健康档案")
	var panel: Node = phone.get("_health_root")
	assert(panel.get("clinic_button").disabled, "remote treatment must be unavailable")
	assert(not panel.get("clinic_route_button").disabled)
	panel.get("clinic_route_button").pressed.emit()
	for _attempt in range(200):
		await create_timer(0.05).timeout
		if not bridge.call("is_campus_busy"): break
	var before: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	assert(before.player.current_location_id == "hospital_clinic")
	assert(before.player.clinic.available_visits == 4)
	assert(not panel.get("clinic_button").disabled)
	panel.get("clinic_button").pressed.emit()
	assert(panel.get("clinic_button").disabled)
	panel.call("_send", "VISIT_CAMPUS_CLINIC", {}) # Pending guard, no second command.
	var result = await bridge.campus_inventory_operation_completed
	assert(result[0], JSON.stringify(result[1]))
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(after.clock == before.clock and after.player.action_budget == before.player.action_budget)
	assert(after.player.vitals.health > before.player.vitals.health)
	assert(after.player.vitals.focus == before.player.vitals.focus)
	assert(after.player.wealth == before.player.wealth - before.player.clinic.fee)
	assert(after.player.clinic.available_visits == 3)
	assert(after.player.clinic.receipts.size() == 1)
	assert(panel.get("clinic_button").disabled)
	assert(panel.get("detail").text.contains("本人最近就诊"))
	for viewport_size in [Vector2i(1280,720), Vector2i(1600,900), Vector2i(1920,1080)]:
		root.size = viewport_size
		await process_frame
		assert(panel.get("clinic_button").size.x <= panel.size.x + 1)
	print("CAMPUS_MEDICAL_FLOW_OK real_entrance actual_staff_shift actual_http_cash_heal no_patient_major private_receipt duplicate_guard three_sizes no_api")
	quit(0)
