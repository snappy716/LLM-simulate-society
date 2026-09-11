extends CanvasLayer
## Presentation only: the bridge owns the clock, request and authoritative result.

const UI_TEXT = preload("res://scripts/ui/campus_ui_text.gd")
const TIPS := [
	"有人休息，有人仍在忙碌。校园的故事还在继续。",
	"新的日程将在清晨准备好，白天按既定安排展开。",
	"你没有接下的委托，也可能迎来其他人的回应。",
]

class NightSky extends Control:
	var elapsed := 0.0
	var dawn := 0.0
	var moving := true

	func _process(delta: float) -> void:
		if not is_visible_in_tree():
			return
		if moving:
			elapsed += delta
		queue_redraw()

	func _draw() -> void:
		var night := Color("101a2c").lerp(Color("506776"), dawn)
		draw_rect(Rect2(Vector2.ZERO, size), night)
		# A handful of vector shapes; no textures, video decoding or extra model calls.
		for i in range(36):
			var star := Vector2(fmod(float(i * 137 + 31), 953.0) / 953.0 * size.x, fmod(float(i * 79 + 17), 227.0) / 540.0 * size.y)
			var alpha := (0.22 + 0.16 * sin(elapsed * 0.7 + i)) * (1.0 - dawn)
			draw_circle(star, 1.0, Color(0.83, 0.89, 0.94, alpha))
		var moon := Vector2(size.x * 0.5, size.y * 0.235)
		draw_circle(moon, 47.0 + sin(elapsed * 0.8) * 2.0, Color(0.83, 0.87, 0.91, 0.035))
		draw_circle(moon, 35.0, Color("d5d7ce"))
		draw_circle(moon + Vector2(14, -7), 32.0, night)
		for i in range(5):
			var glow := 0.25 + 0.65 * maxf(0.0, sin(elapsed * 2.0 - i * 0.65))
			draw_circle(Vector2(size.x * 0.5 + (i - 2) * 14, size.y * 0.36), 2.0, Color(0.78, 0.69, 0.49, glow))
		var ground := size.y * 0.92
		var ink := Color("0a1220").lerp(Color("243849"), dawn)
		for i in range(12):
			var width := size.x / 12.0
			var height := 24.0 + float((i * 29) % 49)
			var origin := Vector2(i * width, ground - height)
			draw_rect(Rect2(origin, Vector2(width - 4, height)), ink)
			for j in range(3):
				if (i + j) % 3 == 0:
					draw_rect(Rect2(origin + Vector2(12 + j * 15, 12), Vector2(5, 8)), Color(0.63, 0.52, 0.31, 0.38))
		draw_rect(Rect2(Vector2(0, ground), Vector2(size.x, size.y - ground)), ink)
		draw_line(Vector2(0, ground), Vector2(size.x, ground), Color(0.6, 0.66, 0.7, 0.16))

var _bridge: Node
var _sky: NightSky
var _content: VBoxContainer
var _date: Label
var _title: Label
var _detail: Label
var _tip: Label
var _dismiss: Button
var _active := false
var _waiting := false
var _paused_before := false
var _focus_before: WeakRef
var _from_day := 1
var _started_at := 0
var _fade: Tween


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	layer = 100
	_build()
	_bridge = get_node("/root/SimulationBridge")
	_bridge.campus_phase_started.connect(_on_started)
	_bridge.campus_phase_advanced.connect(_on_finished)


func _build() -> void:
	_sky = NightSky.new()
	_sky.theme = preload("res://ui/themes/campus_theme.tres")
	_sky.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_sky.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(_sky)
	_content = VBoxContainer.new()
	_content.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_content.anchor_left = 0.12
	_content.anchor_right = 0.88
	_content.anchor_top = 0.41
	_content.anchor_bottom = 0.84
	_content.add_theme_constant_override("separation", 12)
	_sky.add_child(_content)
	_date = _label(14, Color("8cddff"))
	_title = _label(30, Color("eef0ee"))
	_detail = _label(16, Color("c4cdd5"))
	_tip = _label(14, Color("bdcedb"))
	_dismiss = Button.new()
	_dismiss.text = "返回校园界面"
	_dismiss.custom_minimum_size = Vector2(180, 40)
	_dismiss.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_dismiss.pressed.connect(_close)
	_content.add_child(_dismiss)
	_sky.hide()


func _label(font_size: int, color: Color) -> Label:
	var label := Label.new()
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	_content.add_child(label)
	return label


func is_active() -> bool:
	return _active


func _on_started(clock: Dictionary) -> void:
	# A later valid request can supersede a finishing visual, never the HTTP job.
	if _active:
		_close()
	if clock.get("phase") != "late_night":
		return
	_active = true
	_waiting = true
	_from_day = int(clock.get("day", 1))
	_started_at = Time.get_ticks_msec()
	_paused_before = get_tree().paused
	var focus := get_viewport().gui_get_focus_owner()
	_focus_before = weakref(focus) if focus != null else null
	if focus != null:
		focus.release_focus()
	get_tree().paused = true
	_sky.elapsed = 0.0
	_sky.dawn = 0.0
	_sky.moving = not CampusPreferences.values.reduced_motion
	_sky.modulate.a = 1.0
	_sky.show()
	_date.text = "第 %d 天 · 深夜  /  第 %d 天 · 清晨" % [_from_day, _from_day + 1]
	_title.text = "夜色渐深，新的一天将至"
	_detail.text = "正在结算夜晚，准备明日的日程……"
	_tip.text = TIPS[0]
	_dismiss.hide()


func _process(_delta: float) -> void:
	if not _waiting:
		return
	var seconds := int((Time.get_ticks_msec() - _started_at) / 1000)
	_tip.text = TIPS[(seconds / 6) % TIPS.size()] if seconds < 18 else "仍在等待模拟完成 · 已等待 %d 秒\n不会自动重复推进，也不会按动画时长跳过结算。" % seconds


func _input(event: InputEvent) -> void:
	if not _active:
		return
	# Stop gameplay/modal shortcuts before their _unhandled_input handlers. Mouse
	# input goes to the full-screen blocker, with one accessible error-dismiss button.
	if event is InputEventKey or event is InputEventJoypadButton or event is InputEventJoypadMotion:
		if not _waiting and (_fade == null or not _fade.is_running()) and event.is_action_pressed("ui_cancel"):
			_close()
			get_viewport().set_input_as_handled()
		elif not _dismiss.visible or not (event.is_action("ui_accept") or event.is_action("ui_focus_next") or event.is_action("ui_focus_prev")):
			get_viewport().set_input_as_handled()


func _on_finished(success: bool, result: Dictionary) -> void:
	if not _waiting or _bridge.is_campus_busy():
		return # A rejected duplicate click is not the pending request's result.
	_waiting = false
	var clock: Dictionary = _bridge.campus_snapshot.get("clock", {})
	if success and int(clock.get("day", 0)) == _from_day + 1 and clock.get("phase") == "morning":
		_date.text = "第 %d 天 · 清晨" % int(clock.day)
		_title.text = "天亮了，校园再次醒来"
		_detail.text = "新一天的日程已准备好。"
		_tip.text = ""
		_fade = create_tween().set_parallel(true)
		_fade.tween_property(_sky, "dawn", 1.0, 0.45)
		_fade.tween_property(_sky, "modulate:a", 0.0, 0.45)
		_fade.chain().tween_callback(_close)
	else:
		_sky.moving = false
		_title.text = "新一天的结果尚未确认"
		_detail.text = UI_TEXT.operation_feedback(false, result) if not success else "返回的日期与预期不一致，请刷新状态后确认。"
		_tip.text = "不会自动重试或再次扣除行动。请返回界面检查连接与当前日期。"
		_dismiss.show()
		_dismiss.grab_focus()


func _close() -> void:
	if not _active:
		return
	if _fade != null and _fade.is_running():
		_fade.kill()
	_fade = null
	_active = false
	_waiting = false
	_sky.hide()
	get_tree().paused = _paused_before
	var focus = _focus_before.get_ref() if _focus_before != null else null
	if is_instance_valid(focus) and focus.is_inside_tree() and focus.is_visible_in_tree():
		focus.grab_focus()
	_focus_before = null


func _exit_tree() -> void:
	_close()
