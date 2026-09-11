extends RefCounted
## Presentation only: semantic pictograms are not NPC portraits or hidden state.
const DIRECTORY := "res://assets/ui/campus_atelier/"
static var _frames: Dictionary = {}

static func icon(kind: String) -> Texture2D:
	var path := DIRECTORY + "icons/" + kind + ".svg"
	return load(path) if ResourceLoader.exists(path) else load(DIRECTORY + "icons/knowledge.svg")

static func card_kind(effects: Array) -> String:
	for effect in effects:
		if String(effect) in ["restore_health", "restore_focus", "grant_guard"]:
			return "support"
	for effect in effects:
		if String(effect) in ["deal_physical", "deal_technique"]: return "combat"
	return "knowledge"

static func frame(active: bool = false) -> StyleBoxTexture:
	if not _frames.has(active):
		var style := StyleBoxTexture.new()
		style.texture = load(DIRECTORY + ("card_active.svg" if active else "card_idle.svg"))
		for side in [SIDE_LEFT, SIDE_TOP, SIDE_RIGHT, SIDE_BOTTOM]:
			style.set_texture_margin(side, 18)
			style.set_content_margin(side, 12)
		_frames[active] = style
	return _frames[active]

static func decorate_card(button: Button, kind: String, selected: bool) -> void:
	button.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	button.icon = icon(kind)
	button.expand_icon = true
	button.add_theme_constant_override("icon_max_width", 34)
	button.add_theme_constant_override("h_separation", 10)
	button.add_theme_stylebox_override("normal", frame(selected))
	button.add_theme_stylebox_override("hover", frame(true))
	button.add_theme_stylebox_override("pressed", frame(true))
	button.custom_minimum_size = Vector2(194, 132)

static func emblem(kind: String, dimension: int = 42) -> TextureRect:
	var texture := TextureRect.new()
	texture.texture = icon(kind)
	texture.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	texture.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	texture.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	texture.custom_minimum_size = Vector2(dimension, dimension)
	texture.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return texture
