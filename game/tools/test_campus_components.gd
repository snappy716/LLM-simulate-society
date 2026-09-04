extends SceneTree


func _init() -> void:
	var trigger_scene := load("res://scenes/world/components/campus_transition_trigger.tscn") as PackedScene
	assert(trigger_scene != null)
	var trigger = trigger_scene.instantiate()
	assert(trigger != null)
	assert(trigger.collision_mask == 2)
	trigger.passage_id = "road_gate_to_student_life"
	assert(trigger.passage_id == "road_gate_to_student_life")

	var anchor_scene := load("res://scenes/world/components/campus_arrival_anchor.tscn") as PackedScene
	assert(anchor_scene != null)
	var anchor = anchor_scene.instantiate()
	assert(anchor != null)
	anchor.anchor_id = "region:student_life_region:entry:road_gate_to_student_life"
	assert(not anchor.anchor_id.is_empty())

	trigger.free()
	anchor.free()
	print("CAMPUS_COMPONENTS_OK")
	quit(0)
