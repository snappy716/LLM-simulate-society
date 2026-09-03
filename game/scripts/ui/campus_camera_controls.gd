extends CanvasLayer


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	var panel := PanelContainer.new()
	panel.position = Vector2(18, 470)
	panel.size = Vector2(250, 50)
	add_child(panel)
	var row := HBoxContainer.new()
	row.alignment = BoxContainer.ALIGNMENT_CENTER
	panel.add_child(row)
	var title := Label.new()
	title.text = "镜头 "
	row.add_child(title)
	for multiplier in [1, 2, 3]:
		var button := Button.new()
		button.text = "%d×" % multiplier
		button.custom_minimum_size.x = 54
		button.pressed.connect(_set_zoom.bind(multiplier))
		row.add_child(button)


func _set_zoom(multiplier: int) -> void:
	var camera_controller := get_tree().get_first_node_in_group("campus_art_camera")
	if camera_controller != null:
		camera_controller.set_zoom_multiplier(multiplier)
