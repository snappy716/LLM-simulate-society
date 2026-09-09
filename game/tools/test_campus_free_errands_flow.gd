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
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	await process_frame
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(snapshot.clock.phase == "evening")
	assert(snapshot.population.campus_student_001.current_activity.activity_id != "BUY_ITEM")
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	bridge.call("request_npc_chronicle", "campus_student_001", "recent", "", 50)
	var reply = await bridge.campus_npc_chronicle_loaded
	assert(reply[0], JSON.stringify(reply))
	var page: Dictionary = reply[1]
	var purchase := false
	var primary := false
	for entry in page.items:
		if entry.phase != "evening":
			continue
		purchase = purchase or entry.event_type == "NPC_FREE_ERRAND_COMPLETED"
		primary = primary or entry.event_type == "NPC_ACTIVITY_COMPLETED"
	assert(purchase and primary, "disclosed log must retain both real outcomes")
	inspector.set("_chronicle_pages", {"recent": page})
	inspector.call("_render_chronicle", "recent")
	assert(inspector.get("_details").text.contains("购买"))
	assert(inspector.get("_details").text.contains("本人告知"))
	assert((bridge.get("campus_snapshot") as Dictionary).clock == snapshot.clock)
	print("CAMPUS_FREE_ERRANDS_FLOW_OK real_purchase_then_primary real_routes disclosed_log explicit_fixture no_paid_model")
	quit(0)
