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
	phone.call("_open_app", "courses", "课程平台")
	phone.get("_growth_root").get_node("PublicCourses").pressed.emit()
	var panel: Node = phone.get("_agenda_root")
	assert(panel.visible)
	var picker: OptionButton = panel.get("opportunity")
	for index in range(picker.item_count):
		if picker.get_item_metadata(index) == "life:1:research_methods_course":
			picker.select(index)
			picker.item_selected.emit(index)
	assert(panel.get("opportunity_detail").text.contains("0/3"))
	var before: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	panel.get("enroll").pressed.emit()
	var result = await bridge.campus_life_operation_completed
	assert(result[0])
	assert(not panel.get("attend").disabled)
	panel.get("attend").pressed.emit()
	result = await bridge.campus_life_operation_completed
	assert(result[0])
	assert(panel.get("participation").text.contains("研究方法入门 · 1/3"))
	assert(panel.get("participation").text.contains("已学习：观察与记录"))
	assert(panel.get("attend").disabled)
	var after: Dictionary = bridge.get("campus_snapshot")
	assert(before.clock == after.clock)
	assert(int(before.player.action_budget.major_remaining) - 1 == int(after.player.action_budget.major_remaining))
	for viewport_size in [Vector2i(1280,720), Vector2i(1600,900), Vector2i(1920,1080)]:
		root.size = viewport_size
		await process_frame
		assert(picker.size.x <= panel.size.x + 1)
	print("CAMPUS_STUDY_FLOW_OK actual_course_platform_button actual_http_enroll_and_attend one_unit_one_action private_progress no_api")
	quit(0)
