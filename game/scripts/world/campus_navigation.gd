extends Node

signal semantic_location_changed(location_id: String, transition: Dictionary)
signal scene_transition_requested(presentation_key: String, arrival_anchor_id: String, transition: Dictionary)
signal scene_transition_failed(message: String, transition: Dictionary)
signal player_arrived(anchor_id: String)

var _presentation_scenes: Dictionary = {}
var _pending_arrival_anchor_id := ""
var _pending_transition: Dictionary = {}
var _arrival_attempts := 0


func restore_saved_location(snapshot: Dictionary, saved_map_id: String = "") -> void:
	_pending_arrival_anchor_id = ""
	_pending_transition = {}
	var location_id := String(snapshot.player.current_location_id)
	var place: Dictionary = snapshot.places.get(location_id, {})
	var region_id := String(place.get("region_id", location_id))
	var presentation := get_node("/root/CampusPresentation")
	var selected_map := saved_map_id if not saved_map_id.is_empty() else "campus_gate"
	var matches: Array[String] = []
	for entry in presentation.call("all_maps"):
		if region_id in entry.get("visible_region_ids", []):
			matches.append(String(entry.id))
	if not matches.is_empty():
		selected_map = saved_map_id if saved_map_id in matches else matches[0]
	presentation.call("select_map", selected_map)
	# Restore to existing safe ground/entry anchors, not stale pixel coordinates.
	# Only the student-center lobby currently has a separate rendered interior.
	var scene := "res://scenes/debug/campus_lobby_test.tscn" if location_id == "student_center" else "res://scenes/campus/campus_collab_test.tscn"
	register_presentation_scene("campus_outdoor", "res://scenes/campus/campus_collab_test.tscn")
	register_presentation_scene("interior_building_lobby", "res://scenes/debug/campus_lobby_test.tscn")
	var error := get_tree().change_scene_to_file(scene)
	if error != OK:
		scene_transition_failed.emit("读档成功，但场景重建失败。", {})


func register_presentation_scene(presentation_key: String, scene_path: String) -> void:
	if presentation_key.is_empty() or scene_path.is_empty():
		push_error("Campus presentation registration requires a key and scene path")
		return
	_presentation_scenes[presentation_key] = scene_path


func unregister_presentation_scene(presentation_key: String) -> void:
	_presentation_scenes.erase(presentation_key)


func has_presentation_scene(presentation_key: String) -> bool:
	return _presentation_scenes.has(presentation_key)


func handle_transition(transition: Dictionary) -> void:
	var location_id := String(transition.get("current_location_id", ""))
	if not bool(transition.get("requires_scene_change", false)):
		semantic_location_changed.emit(location_id, transition)
		return
	var presentation_key := String(transition.get("presentation_key", ""))
	var arrival_anchor_id := String(transition.get("arrival_anchor_id", ""))
	scene_transition_requested.emit(presentation_key, arrival_anchor_id, transition)
	if not _presentation_scenes.has(presentation_key):
		# Campus art scenes are registered later.  Keeping the current scene here
		# prevents a semantic success from accidentally loading a legacy town map.
		return
	var scene_path := String(_presentation_scenes[presentation_key])
	if not ResourceLoader.exists(scene_path, "PackedScene"):
		scene_transition_failed.emit("找不到校园场景：%s" % scene_path, transition)
		return
	_pending_arrival_anchor_id = arrival_anchor_id
	_pending_transition = transition.duplicate(true)
	_arrival_attempts = 0
	var error := get_tree().change_scene_to_file(scene_path)
	if error != OK:
		_pending_arrival_anchor_id = ""
		_pending_transition = {}
		scene_transition_failed.emit("无法加载校园场景：%s" % error, transition)
		return
	_place_player_after_scene_change()


func _place_player_after_scene_change() -> void:
	for _attempt in range(30):
		await get_tree().process_frame
		if _pending_arrival_anchor_id.is_empty():
			return
		_arrival_attempts += 1
		var player := get_tree().get_first_node_in_group("player") as Node2D
		if player == null or player.is_queued_for_deletion():
			continue
		for candidate in get_tree().get_nodes_in_group("campus_arrival_anchor"):
			if (
				candidate is Node2D
				and not candidate.is_queued_for_deletion()
				and String(candidate.get_meta("anchor_id", "")) == _pending_arrival_anchor_id
			):
				player.global_position = candidate.global_position
				var completed_anchor_id := _pending_arrival_anchor_id
				_pending_arrival_anchor_id = ""
				_pending_transition = {}
				player_arrived.emit(completed_anchor_id)
				return
	var failed_transition := _pending_transition
	_pending_arrival_anchor_id = ""
	_pending_transition = {}
	scene_transition_failed.emit("新场景缺少玩家或到达锚点", failed_transition)
