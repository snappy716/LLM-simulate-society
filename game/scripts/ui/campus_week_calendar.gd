extends VBoxContainer
signal manage(app_id: String, app_name: String)
const KIT = preload("res://scripts/ui/campus_ui_kit.gd")
const PHASES := {"morning": "上午", "afternoon": "下午", "evening": "晚上", "late_night": "凌晨"}
var offset := 0
var day_tabs: TabBar
var grid: GridContainer

func _ready() -> void:
	add_child(KIT.label("我的一周 · 四时段安排", 21))
	day_tabs = KIT.tabs(["今天", "+1天", "+2天", "+3天", "+4天", "+5天", "+6天"], func(index): offset = index; refresh())
	add_child(day_tabs)
	grid = GridContainer.new()
	grid.columns = 2
	add_child(grid)
	refresh()

func refresh() -> void:
	if grid == null: return
	for child in grid.get_children():
		grid.remove_child(child)
		child.queue_free()
	var snapshot := SimulationBridge.campus_snapshot
	var today := int(snapshot.get("clock", {}).get("day", 1))
	var date := today + offset
	var rows: Array = snapshot.get("agenda", {}).get("commitments", [])
	for phase in PHASES:
		var card := PanelContainer.new()
		card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		grid.add_child(card)
		var margin := MarginContainer.new()
		for side in ["left", "right", "top", "bottom"]: margin.add_theme_constant_override("margin_" + side, 10)
		card.add_child(margin)
		var column := VBoxContainer.new()
		margin.add_child(column)
		column.add_child(KIT.label("第 %d 天 · %s%s" % [date, PHASES[phase], " · 当前" if offset == 0 and snapshot.get("clock", {}).get("phase") == phase else ""], 17))
		var count := 0
		for row in rows:
			if int(row.get("day", 0)) != date or row.get("phase") != phase: continue
			count += 1
			column.add_child(KIT.label("%s\n%s · %s" % [row.get("label", "约定"), row.get("location_name", ""), "不扣主要行动" if int(row.get("major_action_cost", 0)) == 0 else "%d 主要行动（到场结算）" % int(row.major_action_cost)], 14))
			column.add_child(KIT.button("管理这项约定 ›", func(): manage.emit(row.get("management_app", "agenda"), "日程与约定")))
		if count == 0: column.add_child(KIT.label("暂无已确认约定\n可自由安排，不代表没有课程或任务。", 14))
		if count > 1: column.add_child(KIT.label("有多项约定，执行前请核对地点与剩余行动。", 14))
