extends Node2D

const OUTDOOR_SCENE := "res://scenes/debug/campus_navigation_test.tscn"
const LOBBY_SCENE := "res://scenes/debug/campus_lobby_test.tscn"


func _ready() -> void:
	var camera := get_node_or_null("Player/Camera2D") as Camera2D
	if camera != null:
		camera.enabled = true
	var navigation := get_node("/root/CampusNavigation")
	# Preserve the outdoor scene that opened this shared lobby.  The graybox
	# registers itself only when it is launched directly by the navigation test.
	if not bool(navigation.call("has_presentation_scene", "campus_outdoor")):
		navigation.call("register_presentation_scene", "campus_outdoor", OUTDOOR_SCENE)
	navigation.call("register_presentation_scene", "interior_building_lobby", LOBBY_SCENE)
	queue_redraw()


func _draw() -> void:
	draw_rect(Rect2(0, 0, 1280, 720), Color("#d8d0c1"))
	draw_rect(Rect2(80, 60, 1120, 580), Color("#eee8dc"))
	draw_rect(Rect2(570, 590, 140, 50), Color("#444e54"))
	draw_rect(Rect2(130, 120, 300, 180), Color("#9b5948"))
	draw_rect(Rect2(850, 120, 300, 180), Color("#9b5948"))
	var font := ThemeDB.fallback_font
	draw_string(font, Vector2(490, 105), "学生中心大厅（复用室内模板）", HORIZONTAL_ALIGNMENT_LEFT, -1, 24, Color("#24323a"))
	draw_string(font, Vector2(515, 575), "向下走出门返回楼梯", HORIZONTAL_ALIGNMENT_LEFT, -1, 20, Color("#24323a"))
