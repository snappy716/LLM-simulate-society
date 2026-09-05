extends VBoxContainer
## Three server-owned slots. No client filesystem paths or second world state.

var picker: OptionButton
var detail: RichTextLabel
var save_button: Button
var load_button: Button
var backup_button: Button
var refresh_button: Button
var confirmation: ConfirmationDialog
var _slots: Array = []
var _pending := false
var _confirmed_payload: Dictionary = {}


func _ready() -> void:
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	picker = OptionButton.new()
	for index in range(3):
		picker.add_item("手动存档 %d" % (index + 1))
	picker.item_selected.connect(func(_index): _render())
	add_child(picker)
	detail = RichTextLabel.new()
	detail.size_flags_vertical = Control.SIZE_EXPAND_FILL
	add_child(detail)
	save_button = _button("保存当前世界", _prepare.bind("save", false))
	load_button = _button("读取所选存档", _prepare.bind("load", false))
	backup_button = _button("读取上一份备份", _prepare.bind("load", true))
	refresh_button = _button("刷新存档槽", refresh)
	confirmation = ConfirmationDialog.new()
	confirmation.title = "确认存档操作"
	confirmation.dialog_autowrap = true
	confirmation.get_ok_button().text = "确认"
	confirmation.get_cancel_button().text = "取消"
	confirmation.confirmed.connect(_confirm)
	add_child(confirmation)
	SimulationBridge.campus_persistence_completed.connect(_on_completed)
	_render()


func _button(text_value: String, callback: Callable) -> Button:
	var button := Button.new()
	button.text = text_value
	button.pressed.connect(callback)
	add_child(button)
	return button


func refresh() -> void:
	_pending = true
	_render()
	SimulationBridge.campus_persistence({"operation": "list"})


func _render() -> void:
	if picker == null:
		return
	var selected: Dictionary = _slots[picker.selected] if _slots.size() == 3 else {}
	var current: Dictionary = selected.get("current", {})
	var backup: Dictionary = selected.get("backup", {})
	detail.text = "" if not _pending else "正在处理，请稍候……\n"
	for pair in [["当前存档", current], ["上一份备份", backup]]:
		var record: Dictionary = pair[1]
		var description := "空"
		if record.get("status") == "present":
			var place: Dictionary = SimulationBridge.campus_snapshot.get("places", {}).get(String(record.location_id), {})
			description = "第 %d 天 · %s\n%s" % [int(record.day), SimulationBridge.phase_display_name(String(record.phase)), String(place.get("name", record.location_id))]
		elif bool(record.get("exists", false)):
			description = "文件异常；可尝试上一份备份，原文件保留。"
		detail.text += "%s：%s\n\n" % [pair[0], description]
	detail.text += "保存整个校园状态，不含 API 密钥。读档返回所属区域安全落点；尚不保存精确站位。"
	save_button.disabled = _pending or selected.is_empty()
	load_button.disabled = _pending or not bool(current.get("exists", false))
	backup_button.disabled = _pending or not bool(backup.get("exists", false))
	refresh_button.disabled = _pending


func _prepare(operation: String, backup: bool) -> void:
	if _pending or _slots.size() != 3:
		return
	var selected: Dictionary = _slots[picker.selected]
	var version: Dictionary = selected.backup if backup else selected.current
	_confirmed_payload = {"operation": operation, "slot_id": selected.slot_id, "backup": backup,
		"expected_token": version.token, "confirmed": true,
		"expected_world_revision": int(SimulationBridge.campus_snapshot.revision)}
	if operation == "save":
		_confirmed_payload["presentation_map_id"] = CampusPresentation.current_map_id
	confirmation.dialog_text = "读取将放弃当前未保存进度，恢复整个校园世界。是否继续？" if operation == "load" else "保存当前世界；已有存档会成为上一份备份。是否继续？"
	confirmation.popup_centered(Vector2i(360, 160))


func _confirm() -> void:
	_pending = true
	_render()
	SimulationBridge.campus_persistence(_confirmed_payload.duplicate(true))


func _on_completed(success: bool, result: Dictionary) -> void:
	_pending = false
	if success:
		_slots = result.get("slots", [])
	_render()
	if not success:
		detail.text = String(result.get("error", "操作未完成，请刷新确认。")) + "\n\n" + detail.text
	elif result.get("operation") == "save":
		detail.text = ("保存成功；原异常文件已另外保留，未覆盖有效备份。\n\n" if bool(result.get("preserved_invalid", false)) else "保存成功。\n\n") + detail.text
