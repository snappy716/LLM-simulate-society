class_name CampusTransitionTrigger
extends Area2D

signal traversal_started(passage_id: String)
signal traversal_resolved(success: bool, result: Dictionary)

@export var passage_id := ""
@export var actor_group: StringName = &"player"
@export var automatic := true

var _actor_inside := false
var _request_in_flight := false


func _ready() -> void:
	body_entered.connect(_on_body_entered)
	body_exited.connect(_on_body_exited)
	if passage_id.is_empty():
		push_warning("CampusTransitionTrigger has no passage_id")


func request_traversal() -> void:
	if _request_in_flight or passage_id.is_empty():
		return
	var bridge := get_node_or_null("/root/SimulationBridge")
	if bridge == null:
		traversal_resolved.emit(false, {"error": "找不到校园模拟服务"})
		return
	var presentation_key := _required_presentation_key(bridge)
	var navigation := get_node_or_null("/root/CampusNavigation")
	if not presentation_key.is_empty() and (
		navigation == null or not bool(navigation.call("has_presentation_scene", presentation_key))
	):
		traversal_resolved.emit(false, {
			"error": "尚未注册入口所需的校园场景：%s" % presentation_key,
			"passage_id": passage_id,
		})
		return
	_request_in_flight = true
	traversal_started.emit(passage_id)
	var callback := Callable(self, "_on_traversal_completed")
	if not bridge.is_connected("campus_traversal_completed", callback):
		bridge.connect("campus_traversal_completed", callback)
	bridge.call("traverse_campus_passage", passage_id)


func _on_body_entered(body: Node) -> void:
	if not body.is_in_group(actor_group):
		return
	_actor_inside = true
	if automatic:
		request_traversal()


func _on_body_exited(body: Node) -> void:
	if body.is_in_group(actor_group):
		_actor_inside = false
		_request_in_flight = false


func _on_traversal_completed(success: bool, result: Dictionary, completed_passage_id: String) -> void:
	if completed_passage_id != passage_id:
		return
	var bridge := get_node_or_null("/root/SimulationBridge")
	var callback := Callable(self, "_on_traversal_completed")
	if bridge != null and bridge.is_connected("campus_traversal_completed", callback):
		bridge.disconnect("campus_traversal_completed", callback)
	_request_in_flight = false
	traversal_resolved.emit(success, result)
	if not success:
		return
	var command_result: Dictionary = result.get("result", {})
	var transition: Dictionary = command_result.get("payload", {})
	var navigation := get_node_or_null("/root/CampusNavigation")
	if navigation != null:
		navigation.call("handle_transition", transition)


func _required_presentation_key(bridge: Node) -> String:
	var snapshot = bridge.get("campus_snapshot")
	if not snapshot is Dictionary:
		return ""
	var passages: Dictionary = snapshot.get("passages", {})
	var passage: Dictionary = passages.get(passage_id, {})
	if String(passage.get("transition_kind", "continuous_boundary")) == "continuous_boundary":
		return ""
	var player: Dictionary = snapshot.get("player", {})
	var current_id := String(player.get("current_location_id", ""))
	var destination_id := String(passage.get("to_id", ""))
	if current_id == destination_id:
		destination_id = String(passage.get("from_id", ""))
	var places: Dictionary = snapshot.get("places", {})
	var destination: Dictionary = places.get(destination_id, {})
	if String(destination.get("node_type", "")) == "region":
		return "campus_outdoor"
	var template_id := String(destination.get("interior_template_id", ""))
	var templates: Dictionary = snapshot.get("interior_templates", {})
	var template: Dictionary = templates.get(template_id, {})
	return String(template.get("presentation_key", ""))
