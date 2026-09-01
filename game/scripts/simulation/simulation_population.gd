extends Node2D

@export var npc_scene: PackedScene
@export var max_visible_npcs := 220

var regions: Dictionary = {}
var map_model: Node
var spawned: Dictionary = {}
var npc_data: Dictionary = {}


func _ready() -> void:
	add_to_group("simulation_population")
	regions = _load_json("res://data/simulation/scene_regions.json")
	SimulationBridge.snapshot_updated.connect(_apply_snapshot)
	call_deferred("_find_map")
	if not SimulationBridge.snapshot.is_empty():
		call_deferred("_apply_snapshot", SimulationBridge.snapshot)


func get_npc_world_position(npc_id: String) -> Variant:
	var npc: Node2D = spawned.get(npc_id)
	return npc.global_position if npc != null else null


func get_region_world_position(scene_id: String) -> Variant:
	if map_model == null:
		_find_map()
	var region: Dictionary = _region_for_scene(scene_id)
	if map_model == null or region.is_empty():
		return null
	var cell_data: Array = region.get("cell", [140, 190])
	var cell: Vector2i = map_model.find_nearest_road_cell(Vector2i(int(cell_data[0]), int(cell_data[1])), 24)
	return map_model.cell_to_world(cell)


func _find_map() -> void:
	var layer := get_tree().get_first_node_in_group("city_tile_map") as TileMapLayer
	if layer != null:
		map_model = layer.get_parent()


func _apply_snapshot(snapshot: Dictionary) -> void:
	if map_model == null:
		_find_map()
	if map_model == null or npc_scene == null:
		return
	for child in get_children():
		child.queue_free()
	spawned.clear()
	npc_data = snapshot.get("npcs", {})
	var scene_counts := {}
	var reserved := {}
	var ids: Array = npc_data.keys()
	ids.sort()
	var created := 0
	for npc_id in ids:
		if created >= max_visible_npcs:
			break
		var data: Dictionary = npc_data[npc_id]
		if not bool(data.get("alive", true)) or String(data.get("disposition_status", "active")) in ["dead", "missing", "fled"]:
			continue
		var scene_id := String(data.get("display_scene", data.get("current_scene", "home_quarter")))
		var region: Dictionary = _region_for_scene(scene_id)
		var base_data: Array = region.get("cell", [140, 190])
		var count: int = int(scene_counts.get(scene_id, 0))
		scene_counts[scene_id] = count + 1
		var offset: Vector2i = _distribution_offset(count)
		var desired: Vector2i = Vector2i(int(base_data[0]), int(base_data[1])) + offset
		var cell: Vector2i = map_model.find_nearest_road_cell(desired, 24, reserved)
		reserved[cell] = true
		var npc = npc_scene.instantiate()
		npc.npc_id = String(npc_id)
		var appearance: Dictionary = data.get("appearance", {})
		npc.body_type = String(appearance.get("body_type", "male"))
		npc.world_seed = int(appearance.get("seed", 42))
		npc.simulation_controlled = true
		npc.name = String(npc_id)
		add_child(npc)
		npc.global_position = map_model.cell_to_world(cell)
		npc.name_label.text = String(data.get("name", npc_id))
		npc.set_meta("simulation_data", data)
		npc.add_to_group("simulated_npc")
		spawned[npc_id] = npc
		created += 1


func _region_for_scene(scene_id: String) -> Dictionary:
	if scene_id.begins_with("home_"):
		scene_id = "home_quarter"
	return regions.get(scene_id, regions.get("home_quarter", {}))


func _distribution_offset(index: int) -> Vector2i:
	if index == 0:
		return Vector2i.ZERO
	var radius := int(ceil(sqrt(float(index))))
	var side := radius * 2 + 1
	return Vector2i((index % side) - radius, int(index / side) - radius)


func _load_json(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("无法读取场景区域映射：" + path)
		return {}
	var parsed = JSON.parse_string(file.get_as_text())
	return parsed if parsed is Dictionary else {}
