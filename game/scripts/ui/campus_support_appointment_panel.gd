extends VBoxContainer
## A real phone decision; no need to first find the sender in person.
var contact_id := ""
var appointment: Dictionary = {}
var pending := false
var detail: Label
var accept_button: Button
var cancel_button: Button


func _ready() -> void:
	detail = Label.new()
	detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	detail.add_theme_font_size_override("font_size", 13)
	add_child(detail)
	var row := HBoxContainer.new()
	add_child(row)
	accept_button = Button.new()
	accept_button.text = "同意支持预约"
	accept_button.pressed.connect(func(): _send("ACCEPT_ANOMALY_MEETING"))
	row.add_child(accept_button)
	cancel_button = Button.new()
	cancel_button.text = "婉拒 / 取消预约"
	cancel_button.pressed.connect(func(): _send("CANCEL_ANOMALY_MEETING"))
	row.add_child(cancel_button)
	SimulationBridge.campus_investigation_operation_completed.connect(_completed)
	refresh_contact("")


func refresh_contact(target: String) -> void:
	contact_id = target
	appointment = {}
	for item in SimulationBridge.campus_snapshot.get("social", {}).get("anomaly_meetings", []):
		if item.subject_id == target and item.status in ["pending", "confirmed"]:
			appointment = item
	visible = not appointment.is_empty()
	if not visible: return
	var place: Dictionary = SimulationBridge.campus_snapshot.get("places", {}).get(appointment.location_id, {})
	detail.text = "支持预约 · %s\n第 %d 天%s · %s（各预留一次主要行动）" % ["等待你的回复" if appointment.status == "pending" else "双方已确认", int(appointment.day), "上午" if appointment.phase == "morning" else "下午", place.get("name", appointment.location_id)]
	accept_button.visible = appointment.status == "pending" and appointment.proposer_id != "player"
	accept_button.disabled = pending
	cancel_button.disabled = pending


func _send(action: String) -> void:
	if pending or appointment.is_empty() or SimulationBridge.is_campus_busy(): return
	pending = true
	var parameters := {"meeting_id": appointment.meeting_id, "expected_revision": appointment.revision}
	refresh_contact(contact_id)
	SimulationBridge.operate_campus_investigation(action, parameters)


func _process(_delta: float) -> void:
	if not visible or accept_button == null: return
	accept_button.disabled = pending or SimulationBridge.is_campus_busy()
	cancel_button.disabled = pending or SimulationBridge.is_campus_busy()


func _completed(success: bool, response: Dictionary) -> void:
	if not pending: return
	pending = false
	refresh_contact(contact_id)
	if not success and visible:
		detail.text += "\n" + String(response.get("result", {}).get("message", response.get("error", "预约未更新，请重试。")))
