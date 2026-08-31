extends ModularCharacter

@export var npc_id := "npc_000"
@export_enum("male", "female") var body_type := "male"
@export var world_seed := 42
@export var move_speed := 90.0
@export var simulation_controlled := false

@onready var navigation_agent: NavigationAgent2D = $NavigationAgent2D
@onready var name_label: Label = $NameLabel

var _rng := RandomNumberGenerator.new()
var _anchors: Array[Node] = []
var _wait_time := 0.0


func _ready() -> void:
	super._ready()
	var stable_seed: int = absi(npc_id.hash()) + world_seed
	_rng.seed = stable_seed
	apply_appearance(AppearanceGenerator.generate(body_type, stable_seed))
	name_label.text = npc_id
	_anchors = get_tree().get_nodes_in_group("semantic_anchor")
	if not simulation_controlled:
		call_deferred("_choose_target")
	else:
		set_move_direction(Vector2.ZERO)


func _physics_process(delta: float) -> void:
	if simulation_controlled:
		velocity = Vector2.ZERO
		set_move_direction(Vector2.ZERO)
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


func _choose_target() -> void:
	if _anchors.is_empty():
		return
	var target: Node2D = _anchors[_rng.randi_range(0, _anchors.size() - 1)] as Node2D
	if target != null:
		navigation_agent.target_position = target.global_position
