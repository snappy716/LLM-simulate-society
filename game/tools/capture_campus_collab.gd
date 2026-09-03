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
	await RenderingServer.frame_post_draw
	var image := root.get_viewport().get_texture().get_image()
	assert(not image.is_empty())
	var output_path := "user://campus_collab_capture.png"
	var error := image.save_png(output_path)
	assert(error == OK)
	print("CAMPUS_COLLAB_CAPTURE=", ProjectSettings.globalize_path(output_path))
	scene.queue_free()
	current_scene = null
	await process_frame
	quit(0)
