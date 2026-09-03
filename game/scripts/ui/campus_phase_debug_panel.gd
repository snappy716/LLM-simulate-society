extends PanelContainer

@onready var phase_label: Label = $Margin/VBox/Phase
@onready var budget_label: Label = $Margin/VBox/Budget
@onready var status_label: Label = $Margin/VBox/Status
@onready var advance_button: Button = $Margin/VBox/Advance

var _bridge: Node


func _ready() -> void:
	_bridge = get_node("/root/SimulationBridge")
	_bridge.campus_snapshot_updated.connect(_render_snapshot)
	_bridge.campus_phase_advanced.connect(_on_phase_advanced)
	advance_button.pressed.connect(_on_advance_pressed)
	var current: Dictionary = _bridge.get("campus_snapshot")
	if not current.is_empty():
		_render_snapshot(current)


func _render_snapshot(snapshot: Dictionary) -> void:
	var clock: Dictionary = snapshot.get("clock", {})
	var phase := String(clock.get("phase", "morning"))
	var day := int(clock.get("day", 1))
	var player: Dictionary = snapshot.get("player", {})
	var budget: Dictionary = player.get("action_budget", {})
	var plan: Dictionary = player.get("current_plan", {})
	phase_label.text = "第 %d 天 · %s" % [day, _bridge.call("phase_display_name", phase)]
	budget_label.text = "主要行动剩余：%d" % int(budget.get("major_remaining", 0))
	status_label.text = "计划：%s @ %s\n聊天 / 购物 / 吃饭 / 普通移动：免费" % [
		String(plan.get("activity_id", "自由安排")),
		String(plan.get("location_id", "未指定")),
	]


func _on_advance_pressed() -> void:
	advance_button.disabled = true
	status_label.text = "正在推进时段……"
	_bridge.call("advance_campus_phase")


func _on_phase_advanced(success: bool, result: Dictionary) -> void:
	advance_button.disabled = false
	if success:
		_render_snapshot(_bridge.get("campus_snapshot"))
		return
	status_label.text = String(result.get("error", "时段推进失败"))
