class_name ModularCharacter
extends CharacterBody2D

const COLUMNS := 10
const ROWS := 7
const IDLE_ROW := 0
const IDLE_FRAMES := 5
const IDLE_FPS := 5.0
const RUN_ROW := 2
const RUN_FRAMES := 8
const RUN_FPS := 10.0

@onready var visual: Node2D = $Visual

var appearance: Dictionary = {}
var current_animation: StringName = &"idle"
var current_frame_index := 0
var frame_elapsed := 0.0
var facing_right := false
var _layers: Dictionary = {}


func _ready() -> void:
	_layers = {
		&"skin": $Visual/Skin,
		&"underwear": $Visual/Underwear,
		&"pants": $Visual/Pants,
		&"shirt": $Visual/Shirt,
		&"shoes": $Visual/Shoes,
		&"hair": $Visual/Hair,
		&"hand_item": $Visual/HandItem,
	}

	for layer in _layers.values():
		layer.hframes = COLUMNS
		layer.vframes = ROWS
		layer.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	_apply_frame()


func _process(delta: float) -> void:
	var fps := IDLE_FPS if current_animation == &"idle" else RUN_FPS
	var frame_count := IDLE_FRAMES if current_animation == &"idle" else RUN_FRAMES
	frame_elapsed += delta
	var frame_duration := 1.0 / fps
	while frame_elapsed >= frame_duration:
		frame_elapsed -= frame_duration
		current_frame_index = (current_frame_index + 1) % frame_count
		_apply_frame()


func apply_appearance(new_appearance: Dictionary) -> void:
	appearance = new_appearance.duplicate(true)
	var body_type := String(appearance.get("body_type", "male"))

	for slot in AppearanceCatalog.SLOTS:
		var layer: Sprite2D = _layers.get(slot)
		if layer == null:
			continue
		var item_id := String(appearance.get(String(slot), "none"))
		var texture_path := AppearanceCatalog.get_texture_path(body_type, slot, item_id)
		if texture_path.is_empty():
			layer.texture = null
			layer.visible = false
			continue
		var texture := load(texture_path) as Texture2D
		if texture == null:
			push_warning("外观纹理加载失败：%s" % texture_path)
			layer.visible = false
			continue
		layer.texture = texture
		layer.visible = true
	_apply_frame()


func set_move_direction(direction: Vector2) -> void:
	if direction.x > 0.0:
		facing_right = true
	elif direction.x < 0.0:
		facing_right = false

	visual.scale.x = -abs(visual.scale.x) if facing_right else abs(visual.scale.x)
	_set_animation(&"idle" if direction.is_zero_approx() else &"run")


func _set_animation(animation_name: StringName) -> void:
	if current_animation == animation_name:
		return
	current_animation = animation_name
	current_frame_index = 0
	frame_elapsed = 0.0
	_apply_frame()


func _apply_frame() -> void:
	var row := IDLE_ROW if current_animation == &"idle" else RUN_ROW
	var sheet_frame := row * COLUMNS + current_frame_index
	for layer in _layers.values():
		layer.frame = sheet_frame
