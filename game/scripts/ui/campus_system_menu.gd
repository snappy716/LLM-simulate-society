extends CanvasLayer
## UI02: one title/pause shell, existing settings and authoritative save slots.

const KIT := preload("res://scripts/ui/campus_ui_kit.gd")
const SAVE_PANEL := preload("res://scripts/ui/campus_save_panel.gd")
const TITLE_SCENE := "res://scenes/ui/campus_title.tscn"
var overlay: Control
var body: VBoxContainer
var heading: Label
var subtitle: Label
var back: Button
var feedback: Label
var confirmation: ConfirmationDialog
var buttons: Dictionary = {}
var page := ""
var title_mode := false
var _opened := false
var _pending := ""
var _slots: Array = []
var _confirmation_action := ""
var _confirmation_revision := 0
var _resume_focus: WeakRef
var _previous_pause := false
var _ever_played := false
var _intro := false
var _guide_return := "home"
var _hidden_huds: Array[WeakRef] = []

func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	layer = 35
	_build()
	get_tree().auto_accept_quit = false
	SimulationBridge.campus_persistence_completed.connect(_completed)
	SimulationBridge.connection_state_changed.connect(_connection)
	SimulationBridge.campus_snapshot_updated.connect(func(_snapshot): _update_availability())

func _build() -> void:
	overlay = Control.new()
	overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(overlay)
	var art := TextureRect.new()
	art.texture = load("res://assets/ui/campus_atelier/campus_day_v3.png")
	art.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	art.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	art.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	art.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	art.mouse_filter = Control.MOUSE_FILTER_IGNORE
	art.name = "TitleArt"
	overlay.add_child(art)
	var shade := ColorRect.new()
	shade.name = "MenuShade"
	shade.color = Color("0b2239b8")
	shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	overlay.add_child(shade)
	var margin := MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	for side in ["left", "right"]: margin.add_theme_constant_override("margin_" + side, 48)
	for side in ["top", "bottom"]: margin.add_theme_constant_override("margin_" + side, 24)
	overlay.add_child(margin)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", KIT.GAP)
	margin.add_child(column)
	var eyebrow := KIT.label("C A M P U S   /   青春校园", 13)
	eyebrow.name = "MenuEyebrow"
	eyebrow.add_theme_color_override("font_color", KIT.BLUE)
	column.add_child(eyebrow)
	heading = KIT.label("校园 · DEMO", 30)
	column.add_child(heading)
	subtitle = KIT.label("每个人，都有正在继续的生活。", 14)
	subtitle.add_theme_color_override("font_color", KIT.MUTED)
	column.add_child(subtitle)
	column.add_child(HSeparator.new())
	var scroll := KIT.scroll_body()
	column.add_child(scroll)
	body = VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 8)
	scroll.add_child(body)
	feedback = KIT.status("")
	feedback.add_theme_font_size_override("font_size", 14)
	column.add_child(feedback)
	back = KIT.button("返回 · Esc", _back)
	column.add_child(back)
	confirmation = KIT.confirmation(self, _confirmed)
	confirmation.canceled.connect(func():
		_confirmation_action = ""
		if back.visible: back.grab_focus()
		elif not buttons.is_empty(): buttons.values()[0].grab_focus()
	)
	overlay.hide()

func is_open() -> bool:
	return _opened

func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST:
		if not is_open(): open_pause()
		_confirm("quit")

func _input(event: InputEvent) -> void:
	# CanvasLayer draw order is not input priority. Overnight owns all shortcuts.
	if OvernightTransition.is_active(): return
	if InterfaceSettings.is_open() or confirmation.visible: return
	for dialog in get_tree().get_nodes_in_group("campus_settings_confirmation"):
		if dialog.visible: return
	if event.is_action_pressed("ui_cancel"):
		if _opened:
			_back()
		elif not _other_modal():
			open_pause()
		else:
			return
		get_viewport().set_input_as_handled()
	elif _opened:
		for action in ["toggle_phone", "toggle_map", "toggle_roster", "toggle_trade", "interact_npc", "randomize_outfit"]:
			if event.is_action_pressed(action): get_viewport().set_input_as_handled()

func _other_modal() -> bool:
	for group in ["campus_phone_ui", "campus_map_ui", "campus_npc_inspector_ui"]:
		var node := get_tree().get_first_node_in_group(group)
		if node != null and node.is_open(): return true
	return false

func _open() -> void:
	if not _opened:
		_previous_pause = get_tree().paused
		var focus := get_viewport().gui_get_focus_owner()
		_resume_focus = weakref(focus) if focus != null else null
	_opened = true
	for hud in get_tree().get_nodes_in_group("campus_hud"):
		if hud.visible:
			_hidden_huds.append(weakref(hud))
			hud.hide()
	overlay.show()
	get_tree().paused = true

func open_title() -> void:
	title_mode = true
	_open()
	_home()
	_refresh_slots()

func open_pause() -> void:
	if OvernightTransition.is_active(): return
	if _opened or _other_modal() or InterfaceSettings.is_open(): return
	title_mode = false
	_ever_played = true
	_open()
	_home()

func close_menu() -> void:
	_opened = false
	overlay.hide()
	for reference in _hidden_huds:
		if is_instance_valid(reference.get_ref()): reference.get_ref().show()
	_hidden_huds.clear()
	get_tree().paused = _previous_pause if not title_mode else false
	if _resume_focus != null and is_instance_valid(_resume_focus.get_ref()):
		_resume_focus.get_ref().grab_focus()

func _clear(title: String, description: String, id: String) -> void:
	page = id
	var cover := title_mode and id == "home"
	overlay.get_node("TitleArt").visible = cover
	overlay.get_node("MenuShade").color = Color("f4faff30") if cover else Color("12344eed")
	for label in [heading, subtitle, feedback, overlay.find_child("MenuEyebrow", true, false)]:
		label.add_theme_color_override("font_color", Color("164568") if cover else KIT.INK)
	heading.text = title
	subtitle.text = description
	feedback.text = ""
	for child in body.get_children():
		body.remove_child(child)
		child.queue_free()
	buttons.clear()
	back.visible = id != "home" or not title_mode

func _button(id: String, text: String, callback: Callable, role: String = "secondary") -> Button:
	var control := KIT.button(text, callback, role)
	if title_mode and page == "home":
		preload("res://scripts/ui/campus_ui_art.gd").paper_button(control)
		if role == "danger": control.add_theme_color_override("font_color", Color("963b53"))
	if page == "home":
		control.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		control.custom_minimum_size.x = 300
		control.alignment = HORIZONTAL_ALIGNMENT_LEFT
	body.add_child(control)
	buttons[id] = control
	return control

func _home() -> void:
	_clear("校园 · DEMO" if title_mode else "暂歇片刻", "每个人，都有正在继续的生活。" if title_mode else "世界已暂停 · 浏览菜单不消耗行动", "home")
	if title_mode:
		_button("continue", "继续游戏", _continue, "primary")
		_button("new", "新游戏", _new_page)
		_button("load", "读取存档", _save_page)
	else:
		_button("resume", "继续校园生活", close_menu, "primary")
		_button("save", "保存 / 读取存档", _save_page)
		_button("guide", "操作说明", _guide)
	_button("settings", "设置", _settings)
	if not title_mode: _button("title", "返回标题", _confirm.bind("title"))
	_button("quit", "退出游戏", _confirm.bind("quit"), "danger")
	_update_availability()
	_focus_home()

func _focus_home() -> void:
	for id in (["continue", "new", "settings"] if title_mode else ["resume"]):
		if buttons.has(id) and not buttons[id].disabled:
			buttons[id].grab_focus()
			return

func _update_availability() -> void:
	if page != "home": return
	var ready := SimulationBridge.connected and not SimulationBridge.is_campus_busy() and not SimulationBridge.busy and _pending.is_empty()
	for id in ["new", "load", "save"]:
		if buttons.has(id): KIT.availability(buttons[id], ready, "请等待模拟服务连接或当前操作完成。" if not ready else "")
	if title_mode:
		var can_resume := _ever_played or not _latest().is_empty()
		KIT.availability(buttons.continue, ready and can_resume, "无可继续的进度，请选择新游戏或读取存档。" if not can_resume else "继续本次会话，或读取最近的兼容存档。")
	feedback.text = "正在连接本地模拟服务，可先查看设置……" if not SimulationBridge.connected else ("正在处理，请等待结果……" if not ready else ("没有兼容存档，可以开始新游戏。" if title_mode and not _ever_played and _latest().is_empty() else ""))
	var focus := get_viewport().gui_get_focus_owner()
	if focus is Button and focus.disabled: _focus_home()

func _connection(_connected: bool, _message: String) -> void:
	if _opened and title_mode and _connected and _slots.is_empty() and _pending.is_empty(): _refresh_slots()
	_update_availability()

func _refresh_slots() -> void:
	if not SimulationBridge.connected or SimulationBridge.is_campus_busy(): return
	_pending = "list"
	SimulationBridge.campus_persistence({"operation": "list"})
	_update_availability()

func _latest() -> Dictionary:
	var latest: Dictionary = {}
	for slot in _slots:
		if slot.current.get("compatible", false) and (latest.is_empty() or slot.current.saved_at_unix > latest.current.saved_at_unix): latest = slot
	return latest

func _continue() -> void:
	if _ever_played:
		_enter_world()
		return
	var slot := _latest()
	if slot.is_empty(): return
	_pending = "load"
	SimulationBridge.campus_persistence({"operation": "load", "confirmed": true, "backup": false, "slot_id": slot.slot_id, "expected_token": slot.current.token, "expected_world_revision": int(SimulationBridge.campus_snapshot.revision)})
	_update_availability()

func _new_page() -> void:
	_clear("新的学期", "沿用当前 Demo 已支持的初始角色与校园规则", "new")
	body.add_child(KIT.label("从第一天上午，开始你的校园生活。\n\n初始角色与校园规则使用 Demo 预设。\n200 名校园人物各自生活，其中基础 20 名支持深度交互。\n可使用本机配置的模型，也可在离线模式下开始。\n\n已有存档将保留；本次未保存的进度会被替换。"))
	_button("begin", "开始新游戏", _confirm.bind("new"), "primary").grab_focus()

func _save_page() -> void:
	_clear("读取存档" if title_mode else "保存与读取", "三个手动存档槽 · 上一份备份保留 · API 密钥不入存档", "saves")
	var saves := SAVE_PANEL.new()
	saves.read_only = title_mode
	saves.custom_minimum_size.y = 340
	body.add_child(saves)
	saves.detail.fit_content = true
	saves.detail.scroll_active = false
	saves.refresh()
	saves.picker.grab_focus()

func _settings() -> void:
	_clear("设置", "当前已支持的设置 · 不展示无效开关", "settings")
	_button("api", "LLM / API 接口管理", InterfaceSettings.open_settings, "primary").grab_focus()
	_button("controls", "查看键盘操作", _guide)
	body.add_child(preload("res://scripts/ui/campus_preferences_panel.gd").new())

func _guide() -> void:
	_guide_return = page
	_clear("校园生活，从这里开始", "随时可从暂停菜单再次打开", "guide")
	body.add_child(KIT.label("W A S D / 方向键　移动\nE　与附近人物交流\nT　打开手机；M　查看地图\n右上图标　队友、人物与物品、卡牌、关系\nEsc　逐层返回；探索时打开暂停菜单\nTab / Shift+Tab　切换焦点；Enter / 空格　确认\n\n聊天、购物、吃饭和普通移动不消耗主要行动。\n在手机“时间与镜头”中结束时段；过夜时 NPC 规划下一天。\n请在暂停菜单或手机中手动保存，退出前未保存的进度不会自动写入。"))
	_button("understood", "知道了", _back, "primary").grab_focus()

func _back() -> void:
	if not _pending.is_empty():
		feedback.text = "正在处理，请等待结果；不要重复提交。"
		return
	if page == "guide" and _intro:
		_intro = false
		close_menu()
	elif page == "guide" and _guide_return == "settings": _settings()
	elif page != "home": _home()
	elif not title_mode: close_menu()

func _confirm(action: String) -> void:
	if SimulationBridge.is_campus_busy() or SimulationBridge.busy or not _pending.is_empty():
		feedback.text = "当前操作尚未完成，请等待结果后再退出或切换世界。"
		return
	_confirmation_action = action
	_confirmation_revision = int(SimulationBridge.campus_snapshot.get("revision", 0))
	var messages := {"new": "开始新游戏会替换当前未保存进度。已有存档不会删除。是否继续？", "title": "返回标题前建议先手动保存。本次会话暂时保留，关闭游戏后未保存进度会丢失。是否返回？", "quit": "退出游戏将丢失未保存的进度。确认现在退出？"}
	KIT.ask(confirmation, messages[action])

func _confirmed() -> void:
	var action := _confirmation_action
	_confirmation_action = ""
	if SimulationBridge.is_campus_busy() or SimulationBridge.busy:
		feedback.text = "世界正在处理操作，请稍后重新确认。"
		return
	match action:
		"quit": get_tree().quit()
		"title":
			close_menu()
			get_tree().change_scene_to_file(TITLE_SCENE)
		"new":
			_pending = "new"
			feedback.text = "正在创建校园，请稍候……"
			if buttons.has("begin"): buttons.begin.disabled = true
			SimulationBridge.campus_persistence({"operation": "new", "confirmed": true, "expected_world_revision": _confirmation_revision})

func _completed(success: bool, result: Dictionary) -> void:
	var owned := not _pending.is_empty()
	_pending = ""
	if success: _slots = result.get("slots", _slots)
	if not _opened: return
	if success and result.get("operation") in ["load", "new"]:
		_ever_played = true
		close_menu()
		title_mode = false
		if result.operation == "new": call_deferred("_first_guide")
		return
	_update_availability()
	if owned and not success:
		feedback.text = String(result.get("error", "结果尚未确认，请检查状态后再试。"))
		if buttons.has("begin"): buttons.begin.disabled = false

func _first_guide() -> void:
	for _i in range(4): await get_tree().process_frame
	_previous_pause = false
	_open()
	_intro = true
	_guide()

func _enter_world() -> void:
	close_menu()
	title_mode = false
	get_tree().paused = false
	CampusNavigation.restore_saved_location(SimulationBridge.campus_snapshot, CampusPresentation.current_map_id)
