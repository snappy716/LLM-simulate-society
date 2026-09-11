extends VBoxContainer
## Read-only projection of already disclosed facts. Never reads population plans.
signal navigate(app_id: String, target_id: String)
const KIT = preload("res://scripts/ui/campus_ui_kit.gd")
const PHASES := {"morning": "上午", "afternoon": "下午", "evening": "晚上", "late_night": "凌晨"}
const PUBLIC_EVENTS := {"published": "发布", "claimed": "接取", "completed": "完成", "failed": "失败", "expired": "到期", "abandoned": "释放"}
var mode := 0
var query := ""
var page := 0
var rows: Array = []
var cards: VBoxContainer
var pager: HBoxContainer

func _ready() -> void:
	add_child(KIT.label("校园动态 · 有据可查", 22))
	add_child(KIT.label("只汇总公开委托、本人消息与约定。不代表校园发生的全部事情。", 14))
	add_child(KIT.tabs(["今天", "通知与约定", "历史记录"], func(index): mode = index; page = 0; refresh()))
	add_child(KIT.search("搜索已公开的事项", func(text): query = text; page = 0; refresh()))
	cards = VBoxContainer.new()
	add_child(cards)
	refresh()

static func project(snapshot: Dictionary, notifications: bool = false) -> Array:
	var result: Array = []
	var today := int(snapshot.get("clock", {}).get("day", 1))
	if notifications:
		for contact in snapshot.get("messaging", {}).get("contacts", []):
			if int(contact.get("unread_count", 0)) > 0:
				result.append({"day": today, "phase": "", "title": "%s · %d 条未读" % [contact.get("display_name", "联系人"), int(contact.unread_count)], "source": "本人通讯", "app": "messages", "target": contact.get("actor_id", "")})
		for proposal in snapshot.get("social", {}).get("incoming_proposals", []):
			if proposal.get("status") == "pending":
				result.append({"day": today, "phase": "", "title": "%s 发来的请求待回应" % proposal.get("initiator_name", "联系人"), "source": "正式请求 · 尚未接受", "app": "messages", "target": proposal.get("initiator_id", "")})
		for row in snapshot.get("agenda", {}).get("commitments", []):
			result.append({"day": int(row.get("day", today)), "phase": row.get("phase", ""), "title": row.get("label", "已确认约定"), "source": "本人已确认约定 · " + String(row.get("location_name", "")), "app": row.get("management_app", "agenda"), "target": ""})
		return result
	for id in snapshot.get("tasks", {}):
		var task: Dictionary = snapshot.tasks[id]
		for entry in task.get("history", []):
			var kind := String(entry.get("kind", ""))
			if not PUBLIC_EVENTS.has(kind): continue
			# Construct labels from public state transitions, not private motive prose.
			result.append({"day": int(entry.get("day", 1)), "phase": entry.get("phase", ""), "title": "%s · %s" % [PUBLIC_EVENTS[kind], task.get("title", "委托")], "source": ("里世界论坛" if task.get("forum") == "night" else "校园论坛") + " · 正式任务记录", "app": "forums", "target": id})
	result.sort_custom(func(a, b):
		if a.day != b.day: return a.day > b.day
		return PHASES.keys().find(a.phase) > PHASES.keys().find(b.phase)
	)
	return result

func refresh() -> void:
	if cards == null: return
	for child in cards.get_children():
		cards.remove_child(child)
		child.queue_free()
	if pager != null:
		remove_child(pager)
		pager.queue_free()
	rows = project(SimulationBridge.campus_snapshot, mode == 1).filter(func(row):
		return (mode != 0 or row.day == int(SimulationBridge.campus_snapshot.get("clock", {}).get("day", 1))) and (query.is_empty() or String(row.title).containsn(query) or String(row.source).containsn(query))
	)
	var count := ceili(rows.size() / 8.0)
	page = clampi(page, 0, maxi(0, count - 1))
	if rows.is_empty(): cards.add_child(KIT.status("当前筛选下没有可见记录。", "empty"))
	for row in rows.slice(page * 8, (page + 1) * 8):
		var card := PanelContainer.new()
		cards.add_child(card)
		var margin := MarginContainer.new()
		for side in ["left", "top", "right", "bottom"]: margin.add_theme_constant_override("margin_" + side, 10)
		card.add_child(margin)
		var body := VBoxContainer.new()
		margin.add_child(body)
		body.add_child(KIT.label("第 %d 天 %s · %s" % [row.day, PHASES.get(row.phase, ""), row.source], 14))
		body.add_child(KIT.label(row.title))
		body.add_child(KIT.button("查看原始事项 ›", func(): navigate.emit(row.app, row.target)))
	pager = KIT.pagination(page, count, func(index): page = index; refresh())
	add_child(pager)
