extends SceneTree
## Visual sample sheet only, not a new game menu or state projection.
const IDS := ["phone", "map", "party", "character", "cards", "relationships"]
const LABELS := ["手机", "地图", "队友", "人物与物品", "卡牌库", "关系"]

func _initialize() -> void: call_deferred("_run")

func _run() -> void:
	root.content_scale_size = Vector2i(1280, 720)
	var layer := CanvasLayer.new()
	layer.layer = 100
	root.add_child(layer)
	var background := ColorRect.new()
	background.color = Color("183f5c")
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	layer.add_child(background)
	var margin := MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	for side in ["left", "right", "top", "bottom"]: margin.add_theme_constant_override("margin_" + side, 30)
	background.add_child(margin)
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 20)
	margin.add_child(body)
	body.add_child(_label("青春校园 / 纸质剪影 · 六枚入口试稿", 28))
	body.add_child(_label("原创 SVG · 块面、叠放、负形 · 不增加 HUD 底框，不改变点击范围", 16))
	var grid := GridContainer.new()
	grid.columns = 6
	grid.add_theme_constant_override("h_separation", 10)
	body.add_child(grid)
	for i in range(IDS.size()):
		var column := VBoxContainer.new()
		column.custom_minimum_size.x = 195
		column.add_theme_constant_override("separation", 12)
		grid.add_child(column)
		column.add_child(_label(LABELS[i], 20))
		column.add_child(_label("新版放大展示", 13))
		column.add_child(_glyph("campus_paper", IDS[i], 96))
		column.add_child(_label("旧版 HUD · 30px", 13))
		column.add_child(_glyph("campus_moon", IDS[i], 30))
		column.add_child(_label("新版 · 30px / 深底", 13))
		column.add_child(_glyph("campus_paper", IDS[i], 30))
		column.add_child(_label("新版 · 30px / 浅底", 13))
		var light := ColorRect.new()
		light.color = Color("edf3e9")
		light.custom_minimum_size.y = 62
		column.add_child(light)
		var glyph := _glyph("campus_paper", IDS[i], 30)
		light.add_child(glyph)
		glyph.position = Vector2(82, 16)
	body.add_child(_label("仅六枚常驻入口试稿；手机内部的 65 枚资源尚未按此方向扩展。", 16))
	for _i in range(12): await process_frame
	assert(Rect2(Vector2.ZERO, Vector2(root.content_scale_size)).encloses(body.get_global_rect()))
	RenderingServer.force_draw()
	assert(root.get_texture().get_image().save_png(OS.get_cmdline_user_args()[0]) == OK)
	print("CAMPUS_PAPER_ICONS_CAPTURE_OK six_originals old_new large_actual_size dark_light")
	quit(0)

func _label(value: String, size: int) -> Label:
	var label := Label.new()
	label.text = value
	label.add_theme_font_size_override("font_size", size)
	return label

func _glyph(directory: String, id: String, size: int) -> TextureRect:
	var glyph := TextureRect.new()
	glyph.texture = load("res://assets/ui/" + directory + "/" + id + ".svg")
	glyph.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	glyph.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	glyph.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	glyph.custom_minimum_size = Vector2(size, size)
	glyph.size = Vector2(size, size)
	glyph.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var ink := ShaderMaterial.new()
	ink.shader = load("res://assets/ui/campus_moon/scene_ink.gdshader")
	glyph.material = ink
	return glyph
