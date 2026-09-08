extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(100).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.1).timeout
	assert(bridge.campus_snapshot.forums.night.situations.is_empty())
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	phone.call("_open_app", "forums", "双层论坛")
	assert(phone.get("_forum_situations").visible)
	assert(phone.get("_forum_situations").text.contains("库存偏低"))
	assert(not phone.get("_forum_situations").text.contains("异常压力"))
	phone.call("_set_open", false)
	bridge.operate_campus_night_world("ENTER_NIGHT_WORLD")
	var reply: Array = await bridge.campus_night_world_operation_completed
	assert(reply[0], JSON.stringify(reply))
	phone.call("_set_open", true)
	phone.call("_open_app", "forums", "双层论坛")
	phone.get("_forum_night_button").pressed.emit()
	assert(phone.get("_forum_situations").text.contains("异常压力"))
	assert(phone.get("_forum_situations").text.contains("额外暴露"))
	phone.get("_forum_surface_button").pressed.emit()
	assert(not phone.get("_forum_situations").text.contains("异常压力"))
	print("CAMPUS_SITUATIONS_FLOW_OK dual_forum_real_buttons actual_night_unlock natural_pressure explicit_stock secret_filter no_api")
	quit(0)
