class_name CampusArrivalAnchor
extends Marker2D

@export var anchor_id := ""


func _ready() -> void:
	add_to_group("campus_arrival_anchor")
	set_meta("anchor_id", anchor_id)
	if anchor_id.is_empty():
		push_warning("CampusArrivalAnchor has no anchor_id")
