extends SceneTree

const COLLAB_SCENE := "res://scenes/campus/campus_collab_test.tscn"


func _initialize() -> void:
	call_deferred("_capture")


func _capture() -> void:
	var packed := load(COLLAB_SCENE) as PackedScene
	assert(packed != null)
	var scene := packed.instantiate()
	root.add_child(scene)
	current_scene = scene
	for _frame in range(12):
		await process_frame
	var movement_layer = scene.get_node("NpcMovementLayer")
	for _attempt in range(100):
		if int(movement_layer.call("visible_resident_count")) > 0:
			break
		await create_timer(0.05).timeout
	await _save_view("user://campus_collab_capture.png", "CAMPUS_COLLAB_CAPTURE")
	var player := scene.get_node("Player") as Node2D
	var nearby_npc = movement_layer.call("nearest_interactable_npc", player.global_position, 120.0)
	if nearby_npc != null:
		var inspector = scene.get_node("CampusNpcInspectorUI")
		inspector.call("inspect_npc", nearby_npc)
		await process_frame
		await _save_view("user://campus_npc_ui_capture.png", "CAMPUS_NPC_UI_CAPTURE")
		inspector.call("_set_open", false)

	var map_ui = scene.get_node("CampusMapUI")
	map_ui.call("_set_open", true)
	await process_frame
	await _save_view("user://campus_map_ui_capture.png", "CAMPUS_MAP_UI_CAPTURE")
	map_ui.call("_set_open", false)

	var phone_ui = scene.get_node("CampusPhoneUI")
	phone_ui.call("_set_open", true)
	phone_ui.call("_open_app", "album", "校园相册")
	await process_frame
	await _save_view("user://campus_phone_ui_capture.png", "CAMPUS_PHONE_UI_CAPTURE")
	phone_ui.call("_open_app", "forums", "校园互助")
	await process_frame
	await _save_view("user://campus_forum_ui_capture.png", "CAMPUS_FORUM_UI_CAPTURE")
	var forum_cards := phone_ui.get("_forum_cards") as VBoxContainer
	if forum_cards.get_child_count() > 0 and forum_cards.get_child(0) is Button:
		(forum_cards.get_child(0) as Button).pressed.emit()
		await root.get_node("SimulationBridge").campus_task_operation_completed
		await process_frame
		await _save_view("user://campus_forum_detail_capture.png", "CAMPUS_FORUM_DETAIL_CAPTURE")
	phone_ui.call("_set_open", false)
	scene.queue_free()
	current_scene = null
	await process_frame
	quit(0)


func _save_view(output_path: String, label: String) -> void:
	await RenderingServer.frame_post_draw
	var image := root.get_viewport().get_texture().get_image()
	assert(not image.is_empty())
	var error := image.save_png(output_path)
	assert(error == OK)
	print("%s=%s" % [label, ProjectSettings.globalize_path(output_path)])
