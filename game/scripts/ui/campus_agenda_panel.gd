extends VBoxContainer
## Read-only projection. Existing phone/squad commands remain the only authority.

signal open_management(app_id: String, app_name: String)

const PHASES := {"morning": "上午", "afternoon": "下午", "evening": "晚上", "late_night": "凌晨"}
var detail: RichTextLabel
var note: Label


func _ready() -> void:
	detail = RichTextLabel.new()
	detail.bbcode_enabled = false
	detail.fit_content = true
	detail.scroll_active = false
	detail.custom_minimum_size.y = 140
	add_child(detail)
	note = Label.new()
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(note)
	for entry in [["party", "行动小队"], ["messages", "校园通讯"]]:
		var button := Button.new()
		button.text = "前往%s管理约定" % entry[1]
		button.pressed.connect(func(): open_management.emit(entry[0], entry[1]))
		add_child(button)
	SimulationBridge.campus_snapshot_updated.connect(func(_snapshot):
		if visible:
			refresh()
	)
	refresh()


func refresh() -> void:
	var data: Dictionary = SimulationBridge.campus_snapshot.get("agenda", {})
	var lines := PackedStringArray(["我已确认的约定"])
	var rows: Array = data.get("commitments", [])
	if rows.is_empty():
		lines.append("目前没有待履行的已确认约定。\n这不代表没有课程、委托或其他可选活动。")
	for row in rows:
		var cost := "短暂见面 · 不扣主要行动" if int(row.major_action_cost) == 0 else "实际执行时核验主要行动"
		lines.append("第 %d 天 · %s\n%s\n%s\n%s" % [int(row.day), PHASES.get(row.phase, row.phase), row.label, row.location_name, cost])
	detail.text = "\n\n".join(lines)
	note.text = String(data.get("note", "正在读取本人约定…"))
