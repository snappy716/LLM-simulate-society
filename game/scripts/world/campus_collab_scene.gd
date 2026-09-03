extends Node2D

const OUTDOOR_SCENE := "res://scenes/campus/campus_collab_test.tscn"
const LOBBY_SCENE := "res://scenes/debug/campus_lobby_test.tscn"
const MAP_SIZE := Vector2i(1774, 887)


func _ready() -> void:
	var navigation := get_node("/root/CampusNavigation")
	navigation.call("register_presentation_scene", "campus_outdoor", OUTDOOR_SCENE)
	navigation.call("register_presentation_scene", "interior_building_lobby", LOBBY_SCENE)
	var camera := get_node_or_null("Player/Camera2D") as Camera2D
	if camera != null:
		camera.enabled = true
		camera.position = Vector2(0, -180)
		camera.limit_left = 0
		camera.limit_top = 0
		camera.limit_right = MAP_SIZE.x
		camera.limit_bottom = MAP_SIZE.y
