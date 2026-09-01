extends CanvasLayer

@export var npc_scene: PackedScene

@onready var time_label: Label = $TimePanel/TimeLabel
@onready var service_label: Label = $TimePanel/ServiceLabel
@onready var advance_button: Button = $TimePanel/AdvanceButton
@onready var roster_panel: Control = $RosterPanel
@onready var roster_list: ItemList = $RosterPanel/Window/RosterList
@onready var detail_title: Label = $RosterPanel/Window/DetailTitle
@onready var detail_text: RichTextLabel = $RosterPanel/Window/DetailText
@onready var locate_button: Button = $RosterPanel/Window/LocateButton
@onready var preview_viewport: SubViewport = $RosterPanel/Window/PreviewContainer/PreviewViewport

var roster_ids: Array[String] = []
var selected_npc_id := ""


func _ready() -> void:
	roster_panel.visible = false
	advance_button.disabled = true
	advance_button.pressed.connect(SimulationBridge.advance_time)
	roster_list.item_selected.connect(_select_npc)
	locate_button.pressed.connect(_locate_selected_npc)
	SimulationBridge.snapshot_updated.connect(_apply_snapshot)
	SimulationBridge.connection_state_changed.connect(_connection_changed)
	SimulationBridge.advance_state_changed.connect(_advance_state_changed)
	if not SimulationBridge.snapshot.is_empty():
		_apply_snapshot(SimulationBridge.snapshot)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("toggle_roster"):
		roster_panel.visible = not roster_panel.visible
		get_viewport().set_input_as_handled()


func _connection_changed(is_connected: bool, message: String) -> void:
	service_label.text = message
	advance_button.disabled = not is_connected


func _advance_state_changed(is_busy: bool) -> void:
	advance_button.disabled = is_busy
	advance_button.text = "正在推进世界……" if is_busy else "下一时间段"


func _apply_snapshot(snapshot: Dictionary) -> void:
	var day := int(snapshot.get("day", 1))
	var weekday := SimulationBridge.weekday_display_name(int(snapshot.get("weekday", 0)))
	var phase := SimulationBridge.phase_display_name(String(snapshot.get("phase", "morning")))
	time_label.text = "第 %d 天 · %s · %s" % [day, weekday, phase]
	service_label.text = "世界版本 %d · NPC %d 人" % [int(snapshot.get("revision", 0)), (snapshot.get("npcs", {}) as Dictionary).size()]
	advance_button.disabled = false
	_rebuild_roster(snapshot.get("npcs", {}))
	if not selected_npc_id.is_empty() and (snapshot.get("npcs", {}) as Dictionary).has(selected_npc_id):
		_show_npc(selected_npc_id)


func _rebuild_roster(npcs: Dictionary) -> void:
	var previous := selected_npc_id
	roster_list.clear()
	roster_ids.clear()
	var ids: Array = npcs.keys()
	ids.sort()
	for npc_id in ids:
		var data: Dictionary = npcs[npc_id]
		roster_ids.append(String(npc_id))
		var status := String(data.get("disposition_status", "active"))
		var scene_name := _scene_name(String(data.get("display_scene", "")))
		roster_list.add_item("%s  ·  %s\n%s  [%s]" % [data.get("name", npc_id), data.get("occupation", ""), scene_name, status])
	if not previous.is_empty() and roster_ids.has(previous):
		var index := roster_ids.find(previous)
		roster_list.select(index)


func _select_npc(index: int) -> void:
	if index < 0 or index >= roster_ids.size():
		return
	selected_npc_id = roster_ids[index]
	_show_npc(selected_npc_id)


func _show_npc(npc_id: String) -> void:
	var npcs: Dictionary = SimulationBridge.snapshot.get("npcs", {})
	if not npcs.has(npc_id):
		return
	var data: Dictionary = npcs[npc_id]
	detail_title.text = "%s　%s" % [data.get("name", npc_id), npc_id]
	var lines: Array[String] = []
	lines.append("身份　%s / %s" % [data.get("occupation", ""), _layer_name(String(data.get("layer", "ordinary")))])
	if data.get("sequence_pathway") != null:
		lines.append("非凡　%s · 序列 %d" % [data.get("sequence_pathway"), int(data.get("sequence_rank", 0))])
	lines.append("地点　%s" % _scene_name(String(data.get("display_scene", ""))))
	lines.append("状态　健康 %d　理智 %d　财富 %d　%s" % [data.get("health", 0), data.get("sanity", 0), data.get("wealth", 0), data.get("disposition_status", "active")])
	var states: Dictionary = data.get("states", {})
	lines.append("精力 %d　饱食 %d　压力 %d　恐惧 %d　警觉 %d" % [states.get("energy", 0), states.get("satiety", 0), states.get("stress", 0), states.get("fear", 0), states.get("alertness", 0)])
	lines.append("\n当前欲望")
	for desire in (data.get("dominant_desires", []) as Array).slice(0, 3):
		lines.append("• %s（%.0f）%s" % [desire.get("id", ""), desire.get("strength", 0.0), "；".join(desire.get("reasons", []))])
	lines.append("\n四时段计划")
	var plans: Dictionary = data.get("daily_plan", {})
	for phase_id in ["morning", "afternoon", "evening", "late_night"]:
		var plan: Dictionary = plans.get(phase_id, {})
		lines.append("• %s：%s @ %s" % [SimulationBridge.phase_display_name(phase_id), plan.get("intent", "无"), _scene_name(String(plan.get("scene_id", "")))])
	lines.append("\n最近记忆")
	var memories: Array = data.get("memories", [])
	for memory in memories.slice(maxi(0, memories.size() - 6)):
		lines.append("• Day %s %s：%s" % [memory.get("day", ""), SimulationBridge.phase_display_name(String(memory.get("phase", ""))), memory.get("summary", "")])
	detail_text.text = "\n".join(lines)
	locate_button.disabled = String(data.get("disposition_status", "active")) in ["dead", "missing", "fled"]
	_build_idle_preview(data)


func _build_idle_preview(data: Dictionary) -> void:
	for child in preview_viewport.get_children():
		child.queue_free()
	if npc_scene == null:
		return
	var preview = npc_scene.instantiate()
	var appearance: Dictionary = data.get("appearance", {})
	preview.npc_id = String(data.get("id", "npc_000"))
	preview.body_type = String(appearance.get("body_type", "male"))
	preview.world_seed = int(appearance.get("seed", 42))
	preview.simulation_controlled = true
	preview.position = Vector2(110, 132)
	preview.scale = Vector2(2.0, 2.0)
	preview_viewport.add_child(preview)
	preview.name_label.visible = false
	preview.current_frame_index = 0
	preview._apply_frame()
	preview.set_process(false)
	preview.set_physics_process(false)


func _locate_selected_npc() -> void:
	if selected_npc_id.is_empty():
		return
	var population = get_tree().get_first_node_in_group("simulation_population")
	var player := get_tree().get_first_node_in_group("player") as Node2D
	if population == null or player == null:
		return
	var position = population.get_npc_world_position(selected_npc_id)
	if position == null:
		var data: Dictionary = (SimulationBridge.snapshot.get("npcs", {}) as Dictionary).get(selected_npc_id, {})
		position = population.get_region_world_position(String(data.get("display_scene", "home_quarter")))
	if position != null:
		player.global_position = position + Vector2(48, 16)
		roster_panel.visible = false


func _scene_name(scene_id: String) -> String:
	if scene_id.begins_with("home_"):
		return "住宅区"
	var scenes: Dictionary = SimulationBridge.snapshot.get("scenes", {})
	return String((scenes.get(scene_id, {}) as Dictionary).get("name", scene_id))


func _layer_name(layer: String) -> String:
	return {"ordinary": "普通人", "official_beyonder": "官方非凡者", "wild_beyonder": "野生非凡者", "hostile_beyonder": "敌对非凡者"}.get(layer, layer)
