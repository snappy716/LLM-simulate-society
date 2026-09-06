extends SceneTree
## UI-only projection fixtures; never submit their data to the simulation server.


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func():
		if not "--keep-open" in OS.get_cmdline_user_args():
			quit(1)
	)
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	assert(not (bridge.get("campus_snapshot") as Dictionary).is_empty())
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var phone := current_scene.get_node("CampusPhoneUI")
	phone.call("_set_open", true)
	var original: Dictionary = bridge.get("campus_snapshot").duplicate(true)
	var fixture := original.duplicate(true)
	fixture.party.is_full = true
	fixture.party.candidates = [{"actor_id": "ui_fixture_candidate", "display_name": "测试候选", "expected_response": "uncertain", "is_phone_contact": true}]
	bridge.set("campus_snapshot", fixture)
	phone.call("_open_app", "party", "行动小队")
	phone.call("_select_party_candidate", 0)
	assert(phone.get("_party_invite_action").disabled, "selection bypassed full party")
	assert(phone.get("_party_invite_action").tooltip_text == "队伍已满。")
	fixture.party.is_full = false
	phone.call("_refresh_party_page")
	assert(not phone.get("_party_invite_action").disabled)
	phone.get("_social_pending").party = "ui_fixture_candidate"
	phone.call("_refresh_party_page")
	assert(phone.get("_party_invite_action").disabled)
	assert(phone.get("_party_candidate_picker").disabled)
	phone.call("_on_social_proposal_completed", false, {"error": "测试拒绝"}, "ui_fixture_candidate", "party_invite")
	assert(not phone.get("_party_invite_action").disabled)
	assert(not phone.get("_party_candidate_picker").disabled)
	phone.get("_social_pending").party = "ui_fixture_candidate"
	fixture.party.candidates = []
	phone.call("_refresh_party_page")
	phone.call("_on_social_proposal_completed", true, {"result": {"payload": {"reply_text": "已接受邀请"}}}, "ui_fixture_candidate", "party_invite")
	assert(phone.get("_party_feedback").text == "已接受邀请", "candidate removal lost the invitation result")
	assert(phone.get("_social_pending").party == "")
	fixture.party = {}
	phone.call("_refresh_party_page")
	assert(phone.get("_party_candidate_picker").item_count == 0)
	assert(phone.get("_party_invite_action").disabled)
	bridge.set("campus_snapshot", original)
	phone.call("_open_app", "clubs", "社团中心")
	var club_id: String = phone.get("_selected_club_id")
	assert(not club_id.is_empty())
	phone.get("_social_pending").club = club_id
	phone.call("_refresh_club_detail")
	assert(phone.get("_club_picker").disabled)
	assert(phone.get("_club_membership_action").disabled and phone.get("_club_activity_action").disabled)
	phone.call("_on_club_operation_completed", false, {"error": "申请条件不满足"}, "JOIN_CAMPUS_CLUB", club_id)
	assert(not phone.get("_club_picker").disabled)
	assert(phone.get("_club_feedback").text == "申请条件不满足")
	assert(not phone.get("_club_membership_action").tooltip_text.is_empty())
	assert(not phone.get("_club_activity_action").tooltip_text.is_empty())
	phone.call("_open_app", "forums", "双层论坛")
	var task_id: String = original.tasks.keys()[0]
	phone.set("_selected_task_id", task_id)
	phone.get("_social_pending").forum = task_id
	phone.call("_refresh_forum_detail")
	assert(phone.get("_forum_primary_action").disabled and phone.get("_forum_abandon_action").disabled)
	phone.call("_on_task_operation_completed", false, {"error": "任务已被其他人接走"}, "CLAIM_FORUM_TASK", task_id)
	assert(phone.get("_social_pending").forum == "")
	assert(phone.get("_forum_feedback").text == "任务已被其他人接走")
	phone.call("_open_app", "clubs", "社团中心")
	phone.get("_club_feedback").text = ""
	assert(bridge.get("campus_snapshot") == original)
	print("CAMPUS_SOCIAL_UI_OK explicit_projection_fixtures full_party pending_release refusal empty_lists no_commands")
	if not "--keep-open" in OS.get_cmdline_user_args():
		quit(0)
