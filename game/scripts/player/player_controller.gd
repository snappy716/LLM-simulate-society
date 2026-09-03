extends ModularCharacter

@export var move_speed := 150.0
var appearance_seed := 1001


func _ready() -> void:
	super._ready()
	add_to_group("player")
	apply_appearance(AppearanceGenerator.generate("female", appearance_seed))


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("randomize_outfit"):
		appearance_seed += 1
		apply_appearance(AppearanceGenerator.generate("female", appearance_seed))


func _physics_process(_delta: float) -> void:
	var direction := Input.get_vector("move_left", "move_right", "move_up", "move_down")
	velocity = direction * move_speed
	move_and_slide()
	set_move_direction(direction)
