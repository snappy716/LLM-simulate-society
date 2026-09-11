extends RefCounted
## Shared UI01 vocabulary. Business state is supplied by the caller, never invented here.

const INK := Color("f5fbff")
const BLUE := Color("48c2ff")
const MUTED := Color("bdcedb")
const DANGER := Color("ffb5bc")
const GAP := 12
const ART = preload("res://scripts/ui/campus_ui_art.gd")

static func label(text: String, size: int = 16) -> Label:
	var control := Label.new()
	control.text = text
	control.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	control.add_theme_font_size_override("font_size", size)
	return control

static func button(text: String, callback: Callable, role: String = "secondary") -> Button:
	var control := Button.new()
	control.text = text
	control.custom_minimum_size.y = 42
	control.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	control.theme_type_variation = &"CampusPrimary" if role == "primary" else (&"CampusDanger" if role == "danger" else &"Button")
	control.pressed.connect(callback)
	if text.begins_with("返回") or text == "上一页": ART.apply_icon(control, "back")
	elif text.begins_with("关闭") or text == "取消": ART.apply_icon(control, "close")
	elif text.begins_with("保存"): ART.apply_icon(control, "saves")
	elif text == "确认": ART.apply_icon(control, "check")
	return control

static func availability(control: Button, allowed: bool, reason: String = "") -> void:
	control.disabled = not allowed
	control.tooltip_text = reason

static func status(text: String, state: String = "info") -> Label:
	var control := label(text)
	var prefixes := {"loading": "处理中 · ", "empty": "暂无内容 · ", "disabled": "暂不可用 · ", "error": "未完成 · ", "unconfirmed": "结果待确认 · ", "success": "已完成 · "}
	control.text = String(prefixes.get(state, "")) + text
	control.add_theme_color_override("font_color", DANGER if state in ["error", "unconfirmed"] else (BLUE if state == "success" else INK))
	return control

static func scroll_body() -> ScrollContainer:
	var control := ScrollContainer.new()
	control.size_flags_vertical = Control.SIZE_EXPAND_FILL
	control.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	control.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	control.follow_focus = true
	return control

static func search(placeholder: String, callback: Callable) -> LineEdit:
	var control := LineEdit.new()
	control.placeholder_text = placeholder
	control.clear_button_enabled = true
	control.custom_minimum_size.y = 42
	control.text_changed.connect(callback)
	return control

static func filter(labels: Array, callback: Callable) -> OptionButton:
	var control := OptionButton.new()
	control.custom_minimum_size.y = 42
	control.fit_to_longest_item = false
	for text in labels: control.add_item(String(text))
	control.item_selected.connect(callback)
	return control

static func confirmation(parent: Node, callback: Callable) -> ConfirmationDialog:
	var dialog := ConfirmationDialog.new()
	dialog.title = "请确认"
	dialog.dialog_autowrap = true
	dialog.get_ok_button().text = "确认"
	dialog.get_cancel_button().text = "取消"
	for control in [dialog.get_ok_button(), dialog.get_cancel_button()]:
		control.custom_minimum_size = Vector2(104, 42)
	dialog.get_label().add_theme_constant_override("line_spacing", 5)
	dialog.confirmed.connect(callback)
	parent.add_child(dialog)
	return dialog

static func tabs(labels: Array, callback: Callable) -> TabBar:
	var control := TabBar.new()
	control.focus_mode = Control.FOCUS_ALL
	for text in labels: control.add_tab(String(text))
	control.tab_changed.connect(callback)
	return control

static func pagination(index: int, count: int, callback: Callable) -> HBoxContainer:
	var row := HBoxContainer.new()
	var previous := button("上一页", callback.bind(index - 1))
	availability(previous, index > 0, "已是第一页。" if index == 0 else "")
	row.add_child(previous)
	row.add_child(label("%d / %d" % [index + 1 if count > 0 else 0, count]))
	var next := button("下一页", callback.bind(index + 1))
	availability(next, index + 1 < count, "没有更多内容。" if index + 1 >= count else "")
	row.add_child(next)
	return row

static func ask(dialog: ConfirmationDialog, text: String) -> void:
	dialog.dialog_text = text
	dialog.popup_centered(Vector2i(430, 180))
	# Destructive transitions must never be the default Enter target.
	dialog.get_cancel_button().grab_focus()
