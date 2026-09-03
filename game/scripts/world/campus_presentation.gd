extends Node

signal map_changed(entry: Dictionary)

const CATALOG_PATH := "res://data/campus_art_catalog.json"

var current_map_id := "campus_gate"
var camera_zoom_multiplier := 1
var _maps: Dictionary = {}
var _ordered_ids: Array[String] = []


func _ready() -> void:
	_load_catalog()


func all_maps() -> Array[Dictionary]:
	var result: Array[Dictionary] = []
	for map_id in _ordered_ids:
		result.append((_maps[map_id] as Dictionary).duplicate(true))
	return result


func get_map(map_id: String = "") -> Dictionary:
	var resolved_id := current_map_id if map_id.is_empty() else map_id
	return (_maps.get(resolved_id, {}) as Dictionary).duplicate(true)


func select_map(map_id: String) -> bool:
	if not _maps.has(map_id):
		return false
	current_map_id = map_id
	map_changed.emit(get_map(map_id))
	return true


func set_camera_zoom_multiplier(value: int) -> void:
	camera_zoom_multiplier = clampi(value, 1, 3)


func get_camera_zoom_multiplier() -> int:
	return camera_zoom_multiplier


func _load_catalog() -> void:
	var file := FileAccess.open(CATALOG_PATH, FileAccess.READ)
	if file == null:
		push_error("无法打开校园美术目录：%s" % CATALOG_PATH)
		return
	var parsed = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		push_error("校园美术目录不是有效 JSON")
		return
	_maps.clear()
	_ordered_ids.clear()
	for value in parsed.get("maps", []):
		if not value is Dictionary:
			continue
		var entry: Dictionary = value
		var map_id := String(entry.get("id", ""))
		if map_id.is_empty() or _maps.has(map_id):
			continue
		_maps[map_id] = entry.duplicate(true)
		_ordered_ids.append(map_id)
	current_map_id = String(parsed.get("default_map_id", "campus_gate"))
	if not _maps.has(current_map_id) and not _ordered_ids.is_empty():
		current_map_id = _ordered_ids[0]
