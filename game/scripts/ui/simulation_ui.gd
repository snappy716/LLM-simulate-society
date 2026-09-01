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
@onready var trade_panel: Control = $TradePanel
@onready var trade_summary: Label = $TradePanel/Window/Summary
@onready var shop_list: ItemList = $TradePanel/Window/ShopList
@onready var stock_list: ItemList = $TradePanel/Window/StockList
@onready var inventory_list: ItemList = $TradePanel/Window/InventoryList
@onready var buy_button: Button = $TradePanel/Window/BuyButton
@onready var sell_button: Button = $TradePanel/Window/SellButton
@onready var use_button: Button = $TradePanel/Window/UseButton
@onready var equip_button: Button = $TradePanel/Window/EquipButton
@onready var drop_button: Button = $TradePanel/Window/DropButton
@onready var trade_status: Label = $TradePanel/Window/Status

var roster_ids: Array[String] = []
var selected_npc_id := ""
var shop_ids: Array[String] = []
var stock_item_ids: Array[String] = []
var inventory_item_ids: Array[String] = []
var selected_shop_id := ""
var selected_stock_item_id := ""
var selected_inventory_item_id := ""


func _ready() -> void:
	roster_panel.visible = false
	trade_panel.visible = false
	advance_button.disabled = true
	advance_button.pressed.connect(SimulationBridge.advance_time)
	roster_list.item_selected.connect(_select_npc)
	locate_button.pressed.connect(_locate_selected_npc)
	shop_list.item_selected.connect(_select_shop)
	stock_list.item_selected.connect(_select_stock_item)
	inventory_list.item_selected.connect(_select_inventory_item)
	buy_button.pressed.connect(_buy_selected_item)
	sell_button.pressed.connect(_sell_selected_item)
	use_button.pressed.connect(_use_selected_item)
	equip_button.pressed.connect(_equip_selected_item)
	drop_button.pressed.connect(_drop_selected_item)
	SimulationBridge.snapshot_updated.connect(_apply_snapshot)
	SimulationBridge.connection_state_changed.connect(_connection_changed)
	SimulationBridge.advance_state_changed.connect(_advance_state_changed)
	SimulationBridge.trade_completed.connect(_trade_completed)
	SimulationBridge.item_use_completed.connect(_item_use_completed)
	SimulationBridge.action_completed.connect(_action_completed)
	if not SimulationBridge.snapshot.is_empty():
		_apply_snapshot(SimulationBridge.snapshot)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("toggle_roster"):
		roster_panel.visible = not roster_panel.visible
		if roster_panel.visible:
			trade_panel.visible = false
		get_viewport().set_input_as_handled()
	elif event.is_action_pressed("toggle_trade"):
		trade_panel.visible = not trade_panel.visible
		if trade_panel.visible:
			roster_panel.visible = false
			_rebuild_trade_panel(SimulationBridge.snapshot)
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
	_rebuild_trade_panel(snapshot)
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


func _rebuild_trade_panel(snapshot: Dictionary) -> void:
	if snapshot.is_empty():
		return
	var player: Dictionary = snapshot.get("player", {})
	trade_summary.text = "资金 %d %s　负重 %.1f / %.1f" % [
		int(player.get("wealth", 0)), String(player.get("currency", "便士")),
		float(player.get("inventory_weight", 0.0)), float(player.get("inventory_capacity", 0.0))]
	var previous_shop := selected_shop_id
	shop_list.clear()
	shop_ids.clear()
	var shops: Dictionary = snapshot.get("shops", {})
	var ids: Array = shops.keys()
	ids.sort()
	for shop_id in ids:
		var shop: Dictionary = shops[shop_id]
		shop_ids.append(String(shop_id))
		var state := "营业" if bool(shop.get("is_open", false)) else "打烊"
		shop_list.add_item("%s\n%s · %s" % [shop.get("name", shop_id), _scene_name(String(shop.get("scene_id", ""))), state])
	if not previous_shop.is_empty() and shop_ids.has(previous_shop):
		selected_shop_id = previous_shop
	elif not shop_ids.is_empty():
		selected_shop_id = shop_ids[0]
	if not selected_shop_id.is_empty() and shop_ids.has(selected_shop_id):
		shop_list.select(shop_ids.find(selected_shop_id))
	_rebuild_shop_stock()
	_rebuild_player_inventory(player)


func _rebuild_shop_stock() -> void:
	stock_list.clear()
	stock_item_ids.clear()
	selected_stock_item_id = ""
	var shops: Dictionary = SimulationBridge.snapshot.get("shops", {})
	var shop: Dictionary = shops.get(selected_shop_id, {})
	for raw_entry in shop.get("stock", []):
		var entry: Dictionary = raw_entry
		stock_item_ids.append(String(entry.get("id", "")))
		stock_list.add_item("%s × %d\n买 %d / 卖 %d 便士" % [entry.get("name", ""), int(entry.get("quantity", 0)), int(entry.get("buy_price", 0)), int(entry.get("sell_price", 0))])
	buy_button.disabled = true
	sell_button.disabled = selected_inventory_item_id.is_empty() or not bool(shop.get("is_open", false))
	if not shop.is_empty():
		trade_status.text = "%s　店主：%s" % ["营业中" if bool(shop.get("is_open", false)) else "当前时段未营业", shop.get("keeper_name", "无人值守")]


func _rebuild_player_inventory(player: Dictionary) -> void:
	inventory_list.clear()
	inventory_item_ids.clear()
	selected_inventory_item_id = ""
	for raw_entry in player.get("inventory", []):
		var entry: Dictionary = raw_entry
		inventory_item_ids.append(String(entry.get("id", "")))
		inventory_list.add_item("%s × %d\n%s" % [entry.get("name", ""), int(entry.get("quantity", 0)), entry.get("category", "")])
	sell_button.disabled = true
	use_button.disabled = true
	equip_button.disabled = true
	drop_button.disabled = true
	equip_button.text = "装备所选物品"


func _select_shop(index: int) -> void:
	if index < 0 or index >= shop_ids.size():
		return
	selected_shop_id = shop_ids[index]
	_rebuild_shop_stock()


func _select_stock_item(index: int) -> void:
	if index < 0 or index >= stock_item_ids.size():
		return
	selected_stock_item_id = stock_item_ids[index]
	var shop: Dictionary = (SimulationBridge.snapshot.get("shops", {}) as Dictionary).get(selected_shop_id, {})
	buy_button.disabled = not bool(shop.get("is_open", false))


func _select_inventory_item(index: int) -> void:
	if index < 0 or index >= inventory_item_ids.size():
		return
	selected_inventory_item_id = inventory_item_ids[index]
	var shop: Dictionary = (SimulationBridge.snapshot.get("shops", {}) as Dictionary).get(selected_shop_id, {})
	sell_button.disabled = not bool(shop.get("is_open", false))
	var uses: Dictionary = SimulationBridge.snapshot.get("item_uses", {})
	var use_definition: Dictionary = uses.get(selected_inventory_item_id, {})
	var equipped: Array = (SimulationBridge.snapshot.get("player", {}) as Dictionary).get("equipped_item_ids", [])
	var is_equipped := equipped.has(selected_inventory_item_id)
	use_button.disabled = String(use_definition.get("mode", "")) == "equip"
	equip_button.disabled = not is_equipped and String(use_definition.get("mode", "")) != "equip"
	equip_button.text = "卸下所选装备" if is_equipped else "装备所选物品"
	drop_button.disabled = is_equipped


func _buy_selected_item() -> void:
	if selected_shop_id.is_empty() or selected_stock_item_id.is_empty():
		return
	trade_status.text = "正在结算购买……"
	buy_button.disabled = true
	sell_button.disabled = true
	use_button.disabled = true
	equip_button.disabled = true
	drop_button.disabled = true
	SimulationBridge.trade(selected_shop_id, selected_stock_item_id, "buy", 1)


func _sell_selected_item() -> void:
	if selected_shop_id.is_empty() or selected_inventory_item_id.is_empty():
		return
	trade_status.text = "正在结算出售……"
	buy_button.disabled = true
	sell_button.disabled = true
	use_button.disabled = true
	equip_button.disabled = true
	drop_button.disabled = true
	SimulationBridge.trade(selected_shop_id, selected_inventory_item_id, "sell", 1)


func _use_selected_item() -> void:
	if selected_inventory_item_id.is_empty():
		return
	trade_status.text = "正在使用物品……"
	buy_button.disabled = true
	sell_button.disabled = true
	use_button.disabled = true
	equip_button.disabled = true
	drop_button.disabled = true
	SimulationBridge.use_item(selected_inventory_item_id)


func _equip_selected_item() -> void:
	if selected_inventory_item_id.is_empty():
		return
	var equipped: Array = (SimulationBridge.snapshot.get("player", {}) as Dictionary).get("equipped_item_ids", [])
	var action_id := "UNEQUIP_ITEM" if equipped.has(selected_inventory_item_id) else "EQUIP_ITEM"
	trade_status.text = "正在结算装备行动……"
	equip_button.disabled = true
	drop_button.disabled = true
	use_button.disabled = true
	SimulationBridge.perform_action(action_id, {"item_id": selected_inventory_item_id})


func _drop_selected_item() -> void:
	if selected_inventory_item_id.is_empty():
		return
	trade_status.text = "正在把物品放到当前场景……"
	equip_button.disabled = true
	drop_button.disabled = true
	use_button.disabled = true
	SimulationBridge.perform_action("DROP_ITEM", {
		"item_id": selected_inventory_item_id,
		"quantity": 1,
	})


func _trade_completed(success: bool, result: Dictionary) -> void:
	var trade: Dictionary = result.get("trade", {})
	trade_status.text = ("成功：" if success else "失败：") + String(trade.get("message", "未知交易结果"))


func _item_use_completed(success: bool, result: Dictionary) -> void:
	var item_use: Dictionary = result.get("item_use", {})
	trade_status.text = ("成功：" if success else "失败：") + String(item_use.get("message", "未知使用结果"))


func _action_completed(success: bool, result: Dictionary) -> void:
	var action: Dictionary = result.get("action", {})
	var prefix := "成功：" if success else ("已执行但未成功：" if bool(result.get("performed", false)) else "失败：")
	trade_status.text = prefix + String(action.get("message", "未知行动结果"))
