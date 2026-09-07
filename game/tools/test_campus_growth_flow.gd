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
	phone.call("_open_app", "courses", "课程与成长")
	var panel: Control = phone.get("_growth_root")
	assert(panel.visible)
	assert(panel.get("reflect").disabled)
	assert(not panel.get("read").disabled)
	panel.get("read").pressed.emit()
	assert(panel.get("read").disabled)
	var completed = await bridge.campus_growth_operation_completed
	assert(completed[0], JSON.stringify(completed))
	await process_frame
	var current: Dictionary = bridge.get("campus_snapshot")
	assert(current.clock == initial.clock)
	assert(current.growth.topics[0].mastery == 20)
	assert(panel.get("detail").text.contains("理论 20/40"))
	var slots: Array = panel.get("slots")
	var expected: Array = []
	for picker in slots:
		expected.append(String(picker.get_item_metadata(picker.selected)))
	assert(expected.size() == 8)
	panel.get("save_deck").pressed.emit()
	assert(panel.get("save_deck").disabled)
	completed = await bridge.campus_growth_operation_completed
	assert(completed[0], JSON.stringify(completed))
	await process_frame
	assert(bridge.get("campus_snapshot").growth.deck_actors[0].deck_ids == expected)
	# A rejected deck keeps the user's draft selections and releases controls.
	var first: OptionButton = slots[0]
	first.select(0)
	first.item_selected.emit(0)
	var draft := String(first.get_item_metadata(first.selected))
	panel.call("_send", "CONFIGURE_ACTOR_DECK", {"card_ids": []})
	completed = await bridge.campus_growth_operation_completed
	assert(not completed[0])
	await process_frame
	assert(String(first.get_item_metadata(first.selected)) == draft)
	assert(not panel.get("_pending"))
	assert(panel.get("feedback").text.begins_with("未执行"))
	phone.get("_app_scroll").ensure_control_visible(panel.get("detail"))
	await process_frame
	if OS.get_environment("GODOT_GROWTH_INSPECT") == "1":
		print("CAMPUS_GROWTH_INSPECT_READY")
		await create_timer(45).timeout
	print("CAMPUS_GROWTH_FLOW_OK real_reading theory_only action_cost owned_eight_card_deck failure_preserves_draft")
	quit(0)
