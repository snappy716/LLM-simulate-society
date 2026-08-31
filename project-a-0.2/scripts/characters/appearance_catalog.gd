class_name AppearanceCatalog
extends RefCounted

const CATALOG_PATH := "res://data/appearance_catalog.json"
const SLOTS := [&"skin", &"underwear", &"pants", &"shirt", &"shoes", &"hair", &"hand_item"]

static var _catalog: Dictionary = {}


static func _ensure_loaded() -> void:
	if not _catalog.is_empty():
		return

	var file := FileAccess.open(CATALOG_PATH, FileAccess.READ)
	if file == null:
		push_error("无法打开外观目录：%s" % CATALOG_PATH)
		return

	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		_catalog = parsed
	else:
		push_error("外观目录不是有效的 JSON 对象")


static func get_ids(body_type: String, slot: StringName) -> Array[String]:
	_ensure_loaded()
	var result: Array[String] = []
	var body: Dictionary = _catalog.get(body_type, {})
	var entries: Dictionary = body.get(String(slot), {})
	for id in entries.keys():
		result.append(String(id))
	result.sort()
	return result


static func get_texture_path(body_type: String, slot: StringName, item_id: String) -> String:
	_ensure_loaded()
	var body: Dictionary = _catalog.get(body_type, {})
	var entries: Dictionary = body.get(String(slot), {})
	return String(entries.get(item_id, ""))


static func has_item(body_type: String, slot: StringName, item_id: String) -> bool:
	_ensure_loaded()
	var body: Dictionary = _catalog.get(body_type, {})
	var entries: Dictionary = body.get(String(slot), {})
	return entries.has(item_id)
