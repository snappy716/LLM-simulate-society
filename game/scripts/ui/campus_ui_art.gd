extends RefCounted
## Presentation only: semantic pictograms are not NPC portraits or hidden state.
const DIRECTORY := "res://assets/ui/campus_atelier/"
static var _frames: Dictionary = {}
const PAGE_ICONS := {"relationships":"friendship", "character":"character", "time":"pending", "feed":"feed", "cards":"combat"}
const PAGE_PICTURES := {"courses":"study", "notes":"study", "cards":"study", "messages":"social", "relationships":"social", "clubs":"social", "party":"social", "agenda":"campus", "album":"campus"}

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

static func effect_kind(effects: Array) -> String:
	for effect in effects:
		var names := {"grant_guard":"shield", "restore_focus":"focus", "restore_health":"health", "deal_physical":"attack", "deal_technique":"attack", "reveal_pattern":"insight", "apply_disruption":"disruption", "knowledge_insight":"insight", "specialization_effect":"specialization"}
		if names.has(String(effect)): return names[String(effect)]
	return "knowledge"

static func apply_icon(button: Button, kind: String, width: int = 22) -> void:
	button.icon = icon(kind)
	button.expand_icon = true
	button.add_theme_constant_override("icon_max_width", width)

static func page_header(label: Label, page: String, picture: String = "") -> void:
	var badge := label.get_node_or_null("SectionIcon") as TextureRect
	if badge == null:
		badge = emblem("info", 0)
		badge.name = "SectionIcon"
		label.add_child(badge)
		badge.position = Vector2(8, 5)
		badge.size = Vector2(28, 28)
	badge.texture = icon(String(PAGE_ICONS.get(page, page)))
	var banner := label.get_node_or_null("SectionPicture") as TextureRect
	if banner == null:
		banner = TextureRect.new()
		banner.name = "SectionPicture"
		banner.mouse_filter = Control.MOUSE_FILTER_IGNORE
		banner.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		banner.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
		banner.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
		banner.show_behind_parent = true
		banner.modulate.a = 0.19
		label.add_child(banner)
		banner.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	label.custom_minimum_size.y = 38
	var key := picture if not picture.is_empty() else String(PAGE_PICTURES.get(page, ""))
	banner.visible = not key.is_empty()
	if banner.visible: banner.texture = load(DIRECTORY + key + "_day_v3.png")

static func paper_button(button: Button) -> void:
	for state in ["normal", "hover", "pressed", "disabled"]:
		var style := StyleBoxFlat.new()
		style.bg_color = Color("f5fbfff2") if state == "normal" else Color("d9edf9f2")
		style.border_color = Color("327cad")
		style.set_border_width_all(1)
		style.set_corner_radius_all(8)
		for side in [SIDE_LEFT, SIDE_TOP, SIDE_RIGHT, SIDE_BOTTOM]: style.set_content_margin(side, 10)
		button.add_theme_stylebox_override(state, style)
	for state in ["font_color", "font_hover_color", "font_pressed_color", "font_focus_color"]: button.add_theme_color_override(state, Color("164568"))
	for state in ["icon_normal_color", "icon_hover_color", "icon_pressed_color", "icon_focus_color"]: button.add_theme_color_override(state, Color("164568"))
	button.add_theme_color_override("font_disabled_color", Color("607988"))

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
