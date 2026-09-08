extends PanelContainer

@onready var phase_label: Label = $Margin/VBox/Phase
@onready var budget_label: Label = $Margin/VBox/Budget
@onready var status_label: Label = $Margin/VBox/Status
@onready var advance_button: Button = $Margin/VBox/Advance
@onready var night_world_button: Button = $Margin/VBox/NightWorld

var _bridge: Node
var _availability_key := ""


func _ready() -> void:
	_bridge = get_node("/root/SimulationBridge")
	_bridge.campus_snapshot_updated.connect(_render_snapshot)
	_bridge.campus_phase_advanced.connect(_on_phase_advanced)
	_bridge.connection_state_changed.connect(_on_connection_changed)
	advance_button.pressed.connect(_on_advance_pressed)
	night_world_button.pressed.connect(_on_night_world_pressed)
	_bridge.campus_night_world_operation_completed.connect(_on_night_world_completed)
	var current: Dictionary = _bridge.get("campus_snapshot")
	if not current.is_empty():
		_render_snapshot(current)
	_refresh_availability()


func _process(_delta: float) -> void:
	# Poll the small lifecycle flags, but don't rewrite controls every frame.
	if _bridge != null:
		var key := "%s:%s:%s" % [_bridge.get("connected"), _bridge.call("is_campus_busy"), (_bridge.get("campus_snapshot") as Dictionary).get("revision", 0)]
		if key != _availability_key:
			_availability_key = key
			_refresh_availability()


func _refresh_availability() -> void:
	if _bridge == null:
		return
	var snapshot: Dictionary = _bridge.get("campus_snapshot")
	var blocked := ""
	if not bool(_bridge.get("connected")):
		blocked = "本地模拟未连接，正在重新连接；尚不能执行行动。"
	elif snapshot.is_empty():
		blocked = "正在同步校园状态。"
	elif bool(_bridge.call("is_campus_busy")):
		blocked = "正在处理行动，请等待结果，勿重复提交。"
	else:
		var active_battle: Variant = (snapshot.get("combat", {}) as Dictionary).get("active_battle")
		if active_battle is Dictionary and String(active_battle.get("phase", "")) not in ["", "setup", "ready", "resolved"]:
			blocked = "正式战斗中不能结束时段；请继续战斗或在手机战斗页主动撤退。"
	advance_button.disabled = not blocked.is_empty()
	advance_button.tooltip_text = blocked if not blocked.is_empty() else "结束当前时段，执行 NPC 已定安排；跨到次日时才完整规划新一天。不能撤销。"
	var night: Dictionary = snapshot.get("night_world", {})
	night_world_button.disabled = not blocked.is_empty() or not (bool(night.get("can_enter", false)) or bool(night.get("can_exit", false)))
	night_world_button.tooltip_text = blocked if not blocked.is_empty() else ("当前时段、资格或战斗状态不允许切换。" if night_world_button.disabled else "切换表里世界不恢复生命，也不消耗主要行动。")


func _on_connection_changed(connected: bool, _message: String) -> void:
	if connected:
		_render_snapshot(_bridge.get("campus_snapshot"))
	else:
		status_label.text = "模拟连接中断，正在重连。\n操作结果尚未确认，请重连后检查；不会自动重复执行。"
	_refresh_availability()


func _render_snapshot(snapshot: Dictionary) -> void:
	var clock: Dictionary = snapshot.get("clock", {})
	var phase := String(clock.get("phase", "morning"))
	var day := int(clock.get("day", 1))
	var player: Dictionary = snapshot.get("player", {})
	var budget: Dictionary = player.get("action_budget", {})
	var place: Dictionary = (snapshot.get("places", {}) as Dictionary).get(String(player.get("current_location_id", "")), {})
	var vitals: Dictionary = player.get("vitals", {})
	var night_world: Dictionary = snapshot.get("night_world", {})
	var moon: Dictionary = night_world.get("moon", {})
	phase_label.text = "第 %d 天 · %s" % [day, _bridge.call("phase_display_name", phase)]
	budget_label.text = "主要行动剩余：%d" % int(budget.get("major_remaining", 0))
	status_label.text = "生命 %d/%d · 专注 %d/%d\n%s · 污染 %d%%" % [
		int(vitals.get("health", 0)), int(vitals.get("max_health", 0)),
		int(vitals.get("focus", 0)), int(vitals.get("max_focus", 0)),
		String(moon.get("name", "月相未知")),
		int(night_world.get("pollution", 0)),
	]
	status_label.tooltip_text = "%s\n聊天 / 购物 / 吃饭 / 普通移动：免费（不消耗时间或主要行动）。\n在表世界休息可完全恢复；夜间连续战斗保留消耗。" % place.get("name", "地点待同步")
	if bool(night_world.get("can_exit", false)):
		var holds_night_task := false
		for task in snapshot.get("tasks", {}).values():
			if task.get("forum") == "night" and task.get("owned_by_player", false) and task.get("state") in ["locked", "in_progress"]:
				holds_night_task = true
		night_world_button.text = "返回表世界并放弃夜间任务" if holds_night_task else "返回表世界（免费）"
		night_world_button.disabled = false
	else:
		night_world_button.text = "进入夜相（免费）" if bool(night_world.get("can_enter", false)) else "夜相当前不可进入"
		night_world_button.disabled = not bool(night_world.get("can_enter", false))
	_refresh_availability()


func _on_advance_pressed() -> void:
	advance_button.disabled = true
	var phase := String((_bridge.get("campus_snapshot") as Dictionary).get("clock", {}).get("phase", ""))
	status_label.text = "正在结算夜晚、规划新一天……" if phase == "late_night" else "正在执行本时段的既定安排……"
	_bridge.call("advance_campus_phase")


func _on_phase_advanced(success: bool, result: Dictionary) -> void:
	advance_button.disabled = false
	if success:
		_render_snapshot(_bridge.get("campus_snapshot"))
		return
	status_label.text = String(result.get("error", "时段推进失败"))


func _on_night_world_pressed() -> void:
	var night_world: Dictionary = (_bridge.get("campus_snapshot") as Dictionary).get("night_world", {})
	var action_id := "EXIT_NIGHT_WORLD" if bool(night_world.get("can_exit", false)) else "ENTER_NIGHT_WORLD"
	night_world_button.disabled = true
	status_label.text = "正在切换世界层……"
	_bridge.call("operate_campus_night_world", action_id)


func _on_night_world_completed(success: bool, result: Dictionary, _action_id: String) -> void:
	if success:
		_render_snapshot(_bridge.get("campus_snapshot"))
		return
	var command_result: Dictionary = result.get("result", {})
	_render_snapshot(_bridge.get("campus_snapshot"))
	status_label.text = String(command_result.get("message", result.get("error", "夜相切换失败")))
