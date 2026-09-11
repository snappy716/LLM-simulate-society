extends SceneTree

func _initialize() -> void: call_deferred("_run")

func _run() -> void:
	var art := preload("res://scripts/ui/campus_ui_art.gd")
	var catalog := preload("res://scripts/ui/campus_phone_catalog.gd")
	for group in catalog.GROUPS:
		for entry in group.entries:
			var texture := art.icon(String(entry.id))
			assert(texture != null and texture.get_size() == Vector2(64, 64))
	assert(art.card_kind(["restore_health"]) == "support")
	assert(art.card_kind(["deal_technique"]) == "combat")
	assert(art.card_kind(["knowledge_insight"]) == "knowledge")
	assert(art.frame() == art.frame())
	assert(art.frame(true) != art.frame())
	var button := Button.new()
	root.add_child(button)
	art.decorate_card(button, "knowledge", false)
	assert(button.texture_filter == CanvasItem.TEXTURE_FILTER_LINEAR)
	assert(button.icon != null and button.get_theme_stylebox("normal") == art.frame())
	var badge := art.emblem("character")
	assert(badge.mouse_filter == Control.MOUSE_FILTER_IGNORE)
	badge.free()
	button.queue_free()
	var moon: Texture2D = load("res://assets/ui/campus_atelier/moon_lake_v1.png")
	assert(moon != null and moon.get_width() == 1536 and moon.get_height() == 1024)
	print("CAMPUS_ART_ASSETS_OK 20 SVG icons, cached nine-patch frames, title texture")
	quit(0)
