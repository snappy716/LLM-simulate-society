extends SceneTree
## Asset inspection only. This grid is not a gameplay screen or world-state claim.
func _initialize() -> void: call_deferred("_run")

func _run() -> void:
	root.content_scale_size = Vector2i(1280, 720)
	var art := preload("res://scripts/ui/campus_ui_art.gd")
	var names := {"album":"生活相册","anomaly":"异常","agenda":"日程","attack":"攻击","back":"返回","cards":"卡牌库","character":"人物","check":"确认","close":"关闭","clubs":"社团","combat":"战斗","courses":"课程","disruption":"干扰","empty":"暂无","energy":"指令点","feed":"校园动态","filter":"筛选","focus":"专注","friendship":"友情","health":"健康","info":"提示","insight":"洞察","item_document":"文档","item_equipment":"装备","item_food":"食品","item_medicine":"药品","item_misc":"其他物品","item_tool":"工具","knowledge":"知识","map":"地图","market":"商城","messages":"通讯","notes":"笔记","offline":"离线","party":"小队","pending":"处理中","phase_afternoon":"下午","phase_evening":"晚上","phase_late_night":"凌晨","phase_morning":"上午","place_bridge":"校园桥","place_dorm":"宿舍","place_gate":"校门","place_library":"图书馆","place_living":"生活区","place_sport":"运动场","relationships":"关系","romance":"恋爱","saves":"存档","search":"搜索","settings":"设置","shield":"护盾","specialization":"专业效果","support":"支援","time":"时间","warning":"注意","college_math_physics":"数理学院","college_biochemistry":"生化学院","college_earth_space":"天地学院","college_artificial_intelligence":"AI 学院","college_psychology":"心理学院","college_humanities":"人文学院","college_medicine":"医学院","college_sports":"体育学院"}
	names.merge({"assistance":"互助", "forums":"论坛", "trade":"交易", "wallet":"钱包"})
	var canvas := CanvasLayer.new()
	canvas.layer = 100
	root.add_child(canvas)
	var background := ColorRect.new()
	background.color = Color("174766")
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	canvas.add_child(background)
	var margin := MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	for side in ["left", "right", "top", "bottom"]: margin.add_theme_constant_override("margin_" + side, 24)
	background.add_child(margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 12)
	margin.add_child(column)
	var title := Label.new()
	title.text = "青春校园 · 统一图标资源预览"
	title.add_theme_font_size_override("font_size", 23)
	column.add_child(title)
	var hint := Label.new()
	hint.text = "资源目录，不代表游戏中的状态；人物采用通用标识，未制作最终立绘。"
	hint.add_theme_font_size_override("font_size", 13)
	column.add_child(hint)
	var grid := GridContainer.new()
	grid.columns = 10
	grid.size_flags_vertical = Control.SIZE_EXPAND_FILL
	grid.add_theme_constant_override("v_separation", 10)
	column.add_child(grid)
	var count := 0
	for file in DirAccess.get_files_at(art.DIRECTORY + "icons"):
		if not file.ends_with(".svg"): continue
		var id := file.get_basename()
		var tile := VBoxContainer.new()
		tile.custom_minimum_size = Vector2(112, 71)
		grid.add_child(tile)
		tile.add_child(art.emblem(id, 38))
		var label := Label.new()
		label.text = names.get(id, id)
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		label.add_theme_font_size_override("font_size", 13)
		tile.add_child(label)
		count += 1
	for _i in range(12): await process_frame
	assert(Rect2(Vector2.ZERO, Vector2(root.content_scale_size)).encloses(grid.get_global_rect()))
	RenderingServer.force_draw()
	assert(root.get_texture().get_image().save_png(OS.get_cmdline_user_args()[0]) == OK)
	print("CAMPUS_ART_GALLERY_OK %d icons rendered" % count)
	quit(0)
