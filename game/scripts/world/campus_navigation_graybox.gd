extends Node2D

const OUTDOOR_SCENE := "res://scenes/debug/campus_navigation_test.tscn"
const LOBBY_SCENE := "res://scenes/debug/campus_lobby_test.tscn"


func _ready() -> void:
	var navigation := get_node("/root/CampusNavigation")
	navigation.call("register_presentation_scene", "campus_outdoor", OUTDOOR_SCENE)
	navigation.call("register_presentation_scene", "interior_building_lobby", LOBBY_SCENE)
	queue_redraw()


func _draw() -> void:
	# Temporary program-art only: two outdoor semantic regions remain one scene.
	draw_rect(Rect2(0, 0, 1280, 720), Color("#9fb98c"))
	draw_rect(Rect2(650, 0, 180, 720), Color("#777b80"))
	draw_rect(Rect2(690, 0, 8, 720), Color("#d9c65b"))
	draw_rect(Rect2(782, 0, 8, 720), Color("#d9c65b"))
	draw_rect(Rect2(0, 0, 1280, 350), Color("#94b184"))
	draw_line(Vector2(650, 350), Vector2(830, 350), Color("#60c9ff"), 5.0)

	# Student centre on the left, with a short stair run facing the road.
	draw_rect(Rect2(90, 25, 430, 180), Color("#8d4c3f"))
	draw_rect(Rect2(112, 48, 386, 135), Color("#b5604e"))
	for x in range(140, 490, 58):
		draw_rect(Rect2(x, 72, 32, 52), Color("#355e74"))
	draw_rect(Rect2(255, 128, 92, 55), Color("#303b43"))
	for index in range(4):
		draw_rect(Rect2(235 - index * 10, 205 + index * 10, 132 + index * 20, 10), Color("#a9a6a0"))

	var font := ThemeDB.fallback_font
	draw_string(font, Vector2(18, 330), "学生生活区", HORIZONTAL_ALIGNMENT_LEFT, -1, 26, Color.WHITE)
	draw_string(font, Vector2(18, 680), "南门区", HORIZONTAL_ALIGNMENT_LEFT, -1, 26, Color.WHITE)
	draw_string(font, Vector2(112, 60), "学生中心（灰盒）", HORIZONTAL_ALIGNMENT_LEFT, -1, 22, Color.WHITE)
	draw_string(font, Vector2(850, 375), "沿道路向上跨区", HORIZONTAL_ALIGNMENT_LEFT, -1, 22, Color("#17313d"))
