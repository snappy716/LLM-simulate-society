extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _press(bridge: Node, button: Button) -> void:
	assert(not button.disabled, button.text)
	button.pressed.emit()
	assert(button.disabled, "Pending investigation must lock controls")
	var result = await bridge.campus_investigation_operation_completed
	assert(result[0], JSON.stringify(result))
	await process_frame


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
	phone.call("_open_app", "notes", "调查笔记")
	var panel: Control = phone.get("_investigation_root")
	assert(panel.visible)
	await _press(bridge, panel.get("observe"))
	await _press(bridge, panel.get("search"))
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(snapshot.clock == initial.clock)
	assert(snapshot.investigation.entries.size() > initial.investigation.entries.size())
	var evidence: OptionButton = panel.get("evidence")
	for index in range(evidence.item_count):
		if evidence.get_item_text(index).contains("公告《"):
			evidence.select(index)
			break
	evidence.item_selected.emit(evidence.selected)
	await _press(bridge, panel.get("record"))
	assert(panel.get("detail").text.contains("笔记快照"))
	await _press(bridge, panel.get("privacy"))
	assert(panel.get("share").disabled)
	await _press(bridge, panel.get("privacy"))
	await _press(bridge, panel.get("share"))
	var related: OptionButton = panel.get("related")
	related.select(0 if evidence.selected != 0 else 1)
	related.item_selected.emit(related.selected)
	panel.get("hypothesis").text = "公告与现场物品可能有关，仍需要核实。"
	panel.get("hypothesis").text_changed.emit(panel.get("hypothesis").text)
	await _press(bridge, panel.get("link"))
	assert(panel.get("detail").text.contains("公告与现场物品可能有关"))
	assert(panel.get("hypothesis").text.is_empty())
	# Failed requests keep the draft and release controls, not silently retry.
	panel.get("hypothesis").text = "保留这份尚未提交的草稿"
	panel.call("_send", "RECORD_EVIDENCE", {"claim_id": "does-not-exist"})
	var failed = await bridge.campus_investigation_operation_completed
	assert(not failed[0])
	await process_frame
	assert(not panel.get("_pending"))
	assert(panel.get("hypothesis").text == "保留这份尚未提交的草稿")
	assert(panel.get("feedback").text.begins_with("未执行"))
	phone.get("_app_scroll").ensure_control_visible(panel.get("detail"))
	await process_frame
	if OS.get_environment("GODOT_INVESTIGATION_INSPECT") == "1":
		print("CAMPUS_INVESTIGATION_INSPECT_READY")
		await create_timer(45).timeout
	print("CAMPUS_INVESTIGATION_FLOW_OK observe search notes privacy share hypothesis pending failure_draft")
	quit(0)
