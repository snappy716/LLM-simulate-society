extends VBoxContainer
## Personal information only; server owns facts, costs and disclosure decisions.

var evidence: OptionButton
var related: OptionButton
var target: OptionButton
var hypothesis: LineEdit
var detail: RichTextLabel
var feedback: Label
var observe: Button
var search: Button
var record: Button
var privacy: Button
var ask: Button
var share: Button
var link: Button
var _pending := false
var _data: Dictionary = {}


func _ready() -> void:
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	var row := HBoxContainer.new()
	add_child(row)
	observe = _button(row, "查看公告 · 免费", func(): _send("OBSERVE_SCENE"))
	search = _button(row, "深入搜查 · 1 行动", func(): _send("SEARCH_SCENE"))
	evidence = _picker(self)
	evidence.item_selected.connect(func(_index): _update_detail())
	detail = RichTextLabel.new()
	detail.size_flags_vertical = Control.SIZE_EXPAND_FILL
	detail.custom_minimum_size.y = 220
	detail.bbcode_enabled = false
	add_child(detail)
	row = HBoxContainer.new()
	add_child(row)
	record = _button(row, "写入笔记本", func(): _send("RECORD_EVIDENCE", {"claim_id": _selected(evidence)}))
	privacy = _button(row, "设为保密", func(): _send("SET_EVIDENCE_DISCLOSURE", {"claim_id": _selected(evidence), "withheld": not bool(_entry().get("withheld", false))}))
	target = _picker(self)
	row = HBoxContainer.new()
	add_child(row)
	ask = _button(row, "当面询问相关线索", func(): _send("ASK_ABOUT_EVIDENCE", {"claim_id": _selected(evidence), "target_id": _selected(target)}))
	share = _button(row, "向对方分享", func(): _send("SHARE_EVIDENCE", {"claim_id": _selected(evidence), "target_id": _selected(target)}))
	related = _picker(self)
	related.item_selected.connect(func(_index): _update_detail())
	hypothesis = LineEdit.new()
	hypothesis.placeholder_text = "我的推测（须与上方两条记录关联，尚未证实）"
	hypothesis.max_length = 200
	hypothesis.text_changed.connect(func(_value): _update_detail())
	add_child(hypothesis)
	link = _button(self, "关联为待验证推测 · 免费", func(): _send("LINK_EVIDENCE", {"claim_ids": [_selected(evidence), _selected(related)], "summary": hypothesis.text}))
	feedback = Label.new()
	feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(feedback)
	SimulationBridge.campus_snapshot_updated.connect(func(_snapshot):
		if visible:
			refresh()
	)
	SimulationBridge.campus_investigation_operation_completed.connect(_completed)
	refresh()


func _button(parent: Node, title: String, callback: Callable) -> Button:
	var button := Button.new()
	button.text = title
	button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	button.pressed.connect(callback)
	parent.add_child(button)
	return button


func _picker(parent: Node) -> OptionButton:
	var picker := OptionButton.new()
	picker.fit_to_longest_item = false
	parent.add_child(picker)
	return picker


func _selected(picker: OptionButton) -> String:
	return String(picker.get_item_metadata(picker.selected)) if picker.selected >= 0 else ""


func _entry() -> Dictionary:
	for entry in _data.get("entries", []):
		if String(entry.claim.claim_id) == _selected(evidence):
			return entry
	return {}


func refresh() -> void:
	_data = SimulationBridge.campus_snapshot.get("investigation", {})
	for picker in [evidence, related]:
		var previous := _selected(picker)
		picker.clear()
		for entry in _data.get("entries", []):
			var index: int = picker.item_count
			picker.add_item(("关联：" if picker == related else "记录：") + String(entry.claim.summary).left(52))
			picker.set_item_metadata(index, entry.claim.claim_id)
			if String(entry.claim.claim_id) == previous:
				picker.select(index)
	var previous_target := _selected(target)
	target.clear()
	for person in _data.get("nearby", []):
		var index := target.item_count
		target.add_item("在场：" + String(person.name))
		target.set_item_metadata(index, person.actor_id)
		if String(person.actor_id) == previous_target:
			target.select(index)
	_update_detail()


func _update_detail() -> void:
	if detail == null or link == null:
		return
	var entry := _entry()
	var lines := PackedStringArray([String(_data.get("rule_note", "正在连接校园模拟……")), ""])
	if not entry.is_empty():
		var belief: Dictionary = entry.belief
		var claim: Dictionary = entry.claim
		lines.append(String(claim.summary))
		var kind_names := {"profile": "人物资料", "self": "自身经历", "event": "亲历事件", "notice": "公告", "archive": "公开处理记录", "inspection": "现场检查", "statement": "转述", "share": "转述", "interaction": "交谈"}
		var phases := {"morning": "上午", "afternoon": "下午", "evening": "晚上", "late_night": "凌晨"}
		lines.append("来源：%s · %s · 第 %s 天 %s" % [entry.source_name, kind_names.get(belief.source_kind, "既有信息"), belief.learned_day, phases.get(belief.learned_phase, belief.learned_phase)])
		lines.append("个人可信度：%d%% · 转述偏差：%d%%（不是系统判定的真相）" % [roundi(float(belief.confidence) * 100), roundi(float(belief.distortion) * 100)])
		lines.append("已固定在笔记本中" if entry.noted else "尚未固定记录；携带笔记本后可整理")
		var note: Dictionary = _data.get("notes", {}).get(claim.claim_id, {})
		if not note.is_empty():
			lines.append("笔记快照：%s\n记录时可信度：%d%%" % [note.claim.summary, roundi(float(note.belief.confidence) * 100)])
	lines.append("\n现场可调查项目：%d" % _data.get("scene_sources", []).size())
	for source in _data.get("scene_sources", []):
		lines.append("· " + String(source.label))
	lines.append("\n我的推测（均未验证）：")
	for item in _data.get("hypotheses", []):
		lines.append("· " + String(item.summary))
	detail.text = "\n".join(lines)
	var busy := _pending or bool(_data.get("battle_locked", false))
	for picker in [evidence, related, target]:
		picker.disabled = busy or picker.item_count == 0
	hypothesis.editable = not busy
	observe.disabled = busy or not _data.get("can_observe", false)
	search.disabled = busy or not _data.get("can_search", false)
	record.disabled = busy or entry.is_empty() or not _data.get("can_record", false)
	privacy.disabled = busy or entry.is_empty()
	privacy.text = "允许分享" if entry.get("withheld", false) else "设为保密"
	ask.disabled = busy or entry.is_empty() or target.item_count == 0
	share.disabled = ask.disabled or entry.get("withheld", false)
	link.disabled = busy or entry.is_empty() or _selected(evidence) == _selected(related) or hypothesis.text.strip_edges().is_empty()


func _send(action: String, parameters: Dictionary = {}) -> void:
	if _pending:
		return
	_pending = true
	feedback.text = "正在核对现场与证据……"
	_update_detail()
	SimulationBridge.operate_campus_investigation(action, parameters)


func _completed(success: bool, result: Dictionary) -> void:
	if not _pending:
		return
	_pending = false
	var outcome: Dictionary = result.get("result", {})
	var prefix := "完成：" if success else ("结果尚未确认：" if outcome.is_empty() else "未执行：")
	feedback.text = prefix + String(outcome.get("message", result.get("error", "请刷新查看最新状态，勿重复提交同一行动。")))
	if success and outcome.get("payload", {}).has("hypothesis"):
		hypothesis.clear()
	refresh()
