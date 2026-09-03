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
	await _save_view("user://campus_collab_capture.png", "CAMPUS_COLLAB_CAPTURE")

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
