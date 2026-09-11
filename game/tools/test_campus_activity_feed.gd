extends SceneTree

func _initialize() -> void: call_deferred("_run")

func _run() -> void:
	create_timer(80).timeout.connect(func(): push_error("activity feed timeout"); quit(1))
	var bridge := root.get_node("SimulationBridge")
	while bridge.get("campus_snapshot").is_empty(): await create_timer(0.05).timeout
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	var before: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	var projection = load("res://scripts/ui/campus_activity_feed.gd")
	var fixture := {"clock": {"day": 3}, "tasks": {"t": {"title": "寻找书本", "forum": "surface", "history": [{"day": 3, "phase": "morning", "kind": "claimed", "message": "公共消息"}, {"day": 3, "phase": "morning", "kind": "choice_reason", "message": "隐藏动机"}]}}, "messaging": {"contacts": [{"actor_id": "n", "display_name": "朋友", "unread_count": 2}]}}
	var projected: Array = projection.project(fixture)
	assert(projected.size() == 1 and not str(projected).contains("隐藏动机"))
	assert(projection.project(fixture, true)[0].target == "n")
	phone.call("_set_open", true)
	phone.get("_home_brief").pressed.emit()
	var feed = phone.get("_feed_root")
	assert(feed.is_visible_in_tree())
	feed.set("query", "不存在的事项xyz")
	feed.call("refresh")
	assert(feed.get("rows").is_empty())
	feed.set("query", "")
	feed.set("mode", 2)
	feed.call("refresh")
	assert(not feed.get("rows").is_empty())
	var target = feed.get("rows")[0].target
	feed.navigate.emit("forums", target)
	assert(phone.get("_selected_task_id") == target)
	phone.call("_open_app", "messages", "校园通讯")
	var search = phone.get("_contact_search")
	var picker = phone.get("_message_contact_picker")
	if picker.item_count > 0:
		var id = phone.get("_selected_message_contact_id")
		phone.get("_message_input").text = "草稿不会发送"
		search.text = "无此人xyz"
		search.text_changed.emit(search.text)
		assert(picker.item_count == 0 and phone.get("_message_send_action").disabled)
		search.text = ""
		search.text_changed.emit("")
		assert(phone.get("_message_drafts")[id] == "草稿不会发送")
	phone.call("_set_open", false)
	var map = current_scene.get_node("CampusMapUI")
	map.call("_set_open", true)
	for size in [Vector2i(960, 540), Vector2i(1280, 720), Vector2i(1920, 1080)]:
		root.size = size
		map.call("_select_map", "east_dormitory")
		for i in range(8): await process_frame
		assert(map.get("_preview").texture != null)
		assert(root.get_visible_rect().encloses(map.get("_travel").get_global_rect()))
		assert(map.get("_pending_map_id").is_empty())
	assert(bridge.get("campus_snapshot").player.current_location_id == before.player.current_location_id)
	assert(bridge.get("campus_snapshot").player.action_budget == before.player.action_budget)
	map.call("_set_open", false)
	print("CAMPUS_ACTIVITY_FEED_OK source_filter deep_link search_drafts map_preview three_sizes no_travel_no_action_cost")
	quit(0)
