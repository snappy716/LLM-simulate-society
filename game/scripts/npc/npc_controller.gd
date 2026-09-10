extends ModularCharacter

@export var npc_id := "npc_000"
@export_enum("male", "female") var body_type := "male"
@export var world_seed := 42
@export var move_speed := 90.0
@export var simulation_controlled := false
@export var show_name_label := true

@onready var navigation_agent: NavigationAgent2D = $NavigationAgent2D
@onready var name_label: Label = $NameLabel

var _rng := RandomNumberGenerator.new()
var _anchors: Array[Node] = []
var _wait_time := 0.0
var _simulation_route := PackedVector2Array()
var _simulation_route_index := 0
var _route_wait := 0.0
var _waypoint_pause := 0.0
var campus_profile: Dictionary = {}

signal simulation_route_finished(npc_id: String)


func _ready() -> void:
	super._ready()
	var stable_seed: int = absi(npc_id.hash()) + world_seed
	_rng.seed = stable_seed
	apply_appearance(AppearanceGenerator.generate(body_type, stable_seed))
	name_label.text = npc_id
	name_label.visible = show_name_label
	_anchors = get_tree().get_nodes_in_group("semantic_anchor")
	if not simulation_controlled:
		call_deferred("_choose_target")
	else:
		set_move_direction(Vector2.ZERO)


func _physics_process(delta: float) -> void:
	if simulation_controlled:
		_follow_simulation_route(delta)
		return
	if _wait_time > 0.0:
		_wait_time -= delta
		velocity = Vector2.ZERO
		set_move_direction(Vector2.ZERO)
		if _wait_time <= 0.0:
			_choose_target()
		return

	if navigation_agent.is_navigation_finished():
		velocity = Vector2.ZERO
		set_move_direction(Vector2.ZERO)
		_wait_time = _rng.randf_range(1.0, 3.0)
		return

	var next_position := navigation_agent.get_next_path_position()
	var direction := global_position.direction_to(next_position)
	velocity = direction * move_speed
	move_and_slide()
	set_move_direction(direction)


func play_simulation_route(points: PackedVector2Array, speed: float = 90.0, start_delay: float = 0.0, waypoint_pause: float = 0.0) -> void:
	"""Replay an authoritative semantic route without making a local decision."""
	simulation_controlled = true
	move_speed = speed
	movement_animation_speed = clampf(move_speed / 150.0, 0.45, 0.9)
	_route_wait = maxf(0.0, start_delay)
	_waypoint_pause = maxf(0.0, waypoint_pause)
	_simulation_route = points
	_simulation_route_index = 1
	if _simulation_route.is_empty():
		_finish_simulation_route()
		return
	global_position = _simulation_route[0]
	if _simulation_route.size() == 1:
		_finish_simulation_route()


func set_campus_profile(profile: Dictionary) -> void:
	campus_profile = profile.duplicate(true)
	var profile_name := String(campus_profile.get("display_name", npc_id))
	name_label.text = profile_name


func get_campus_profile() -> Dictionary:
	return campus_profile.duplicate(true)


func _follow_simulation_route(delta: float) -> void:
	if _simulation_route_index >= _simulation_route.size():
		velocity = Vector2.ZERO
		set_move_direction(Vector2.ZERO)
		return
	if _route_wait > 0.0:
		_route_wait = maxf(0.0, _route_wait - delta)
		velocity = Vector2.ZERO
		set_move_direction(Vector2.ZERO)
		return
	var target := _simulation_route[_simulation_route_index]
	var direction := global_position.direction_to(target)
	var travel_distance := move_speed * delta
	if global_position.distance_to(target) <= travel_distance:
		global_position = target
		_simulation_route_index += 1
		if _simulation_route_index >= _simulation_route.size():
			_finish_simulation_route()
		else:
			_route_wait = _waypoint_pause
			velocity = Vector2.ZERO
			set_move_direction(Vector2.ZERO)
		return
	velocity = direction * move_speed
	move_and_slide()
	set_move_direction(direction)


func _finish_simulation_route() -> void:
	_simulation_route_index = _simulation_route.size()
	velocity = Vector2.ZERO
	set_move_direction(Vector2.ZERO)
	simulation_route_finished.emit(npc_id)


func _choose_target() -> void:
	if _anchors.is_empty():
		return
	var target: Node2D = _anchors[_rng.randi_range(0, _anchors.size() - 1)] as Node2D
	if target != null:
		navigation_agent.target_position = target.global_position
