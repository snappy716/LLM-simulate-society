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
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	var inspector := current_scene.get_node("CampusNpcInspectorUI")
	var observed := 0
	for _attempt in range(100):
		for npc in get_nodes_in_group("campus_interactable_npc"):
			var profile: Dictionary = npc.call("get_campus_profile")
			if profile.get("current_activity", {}).get("activity_id", "") != "ATTEND_CAMPUS_OUTING": continue
			inspector.call("inspect_npc", npc)
			assert(inspector.get("_opened"))
			var displayed: String = inspector.get("_details").text
			assert(displayed.contains("与熟人共同活动"))
			assert(not displayed.contains("ATTEND_CAMPUS_OUTING"))
			assert(not npc.get("show_name_label"))
			observed += 1
		if observed > 0: break
		await create_timer(0.05).timeout
	assert(observed > 0, "No real naturally socializing NPC available for inspection")
	# Other people's invitations and relationship receipts stay out of our phone.
	for row in snapshot.agenda.outings.records:
		assert(row.proposer_id == "player" or row.recipient_id == "player")
	for row in snapshot.agenda.bonds.records:
		assert(row.proposer_id == "player" or row.recipient_id == "player")
	assert(bridge.get("campus_snapshot").clock == snapshot.clock)
	print("CAMPUS_SOCIAL_PACING_FLOW_OK natural_npc_shared_activity actual_scene_actor readable_inspector no_floating_status private_phone no_api")
	quit(0)
