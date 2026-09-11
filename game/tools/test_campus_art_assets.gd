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
	var count := 0
	for path in DirAccess.get_files_at(art.DIRECTORY + "icons"):
		if not path.ends_with(".svg"): continue
		var texture := art.icon(path.get_basename())
		assert(texture != null and texture.get_size() == Vector2(64, 64))
		count += 1
	for name in ["campus", "study", "social"]:
		var picture: Texture2D = load(art.DIRECTORY + name + "_day_v3.png")
		assert(picture != null and picture.get_size() == Vector2(1536, 1024))
	assert(art.effect_kind(["grant_guard"]) == "shield")
	assert(art.effect_kind(["restore_health"]) == "health")
	assert(art.effect_kind(["deal_technique"]) == "attack")
	assert(art.effect_kind(["unknown"]) == "knowledge")
	var title := Label.new()
	root.add_child(title)
	art.page_header(title, "courses")
	assert(title.get_node("SectionPicture").visible)
	assert(title.get_node("SectionPicture").mouse_filter == Control.MOUSE_FILTER_IGNORE)
	art.page_header(title, "feed")
	assert(not title.get_node("SectionPicture").visible)
	assert(title.get_child_count() == 2)
	title.queue_free()
	print("CAMPUS_ART_ASSETS_OK %d SVG icons, frames, 3 daylight images, semantic effects, reusable headers" % count)
	quit(0)
