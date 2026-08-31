extends Node2D

signal layout_changed(cell: Vector2i, kind: int)
signal layout_saved(path: String)

const MAP_SIZE := Vector2i(400, 400)
const TILE_SIZE := Vector2i(64, 32)
const MAP_ORIGIN := Vector2(12800, 64)
const LAYOUT_PATH := "res://data/maps/tinggen_city_layout.png"
const OVERRIDES_PATH := "res://data/maps/tinggen_city_overrides.json"
const TILE_TEXTURE_PATH := "res://assets/maps/tilesets/blueprint_tiles_64x32.svg"
const GROUND_TEXTURE_PATH := "res://assets/maps/tilesets/temporary_ground_64x32.svg"

enum TileKind { WATER, LAND, ROAD, BUILDING, GARDEN }

const TYPE_NAMES := {"water": TileKind.WATER, "land": TileKind.LAND, "road": TileKind.ROAD, "building": TileKind.BUILDING, "garden": TileKind.GARDEN}
const PALETTE := {
	TileKind.WATER: Color("#244957"), TileKind.LAND: Color("#344f3d"),
	TileKind.ROAD: Color("#aaa49b"), TileKind.BUILDING: Color("#765548"),
	TileKind.GARDEN: Color("#4f7548")
}

var tile_layer: TileMapLayer
var ground_layer: TileMapLayer
var layout_image: Image
var layout_texture: ImageTexture


func _ready() -> void:
	var imported_layout_texture := load(LAYOUT_PATH) as Texture2D
	if imported_layout_texture == null:
		push_error("Cannot load imported city layout texture: " + LAYOUT_PATH)
		return
	layout_image = imported_layout_texture.get_image()
	if layout_image == null or layout_image.is_empty():
		push_error("Cannot load editable city layout: " + LAYOUT_PATH)
		return
	if layout_image.get_size() != MAP_SIZE:
		push_error("City layout must be exactly 400x400 pixels, got %s" % layout_image.get_size())
		return
	layout_texture = ImageTexture.create_from_image(layout_image)

	var manual_overrides := _load_manual_overrides()
	ground_layer = TileMapLayer.new()
	ground_layer.name = "TemporaryGroundTerrain"
	ground_layer.position = MAP_ORIGIN
	ground_layer.tile_set = _create_ground_tileset()
	ground_layer.rendering_quadrant_size = 32
	add_child(ground_layer)

	tile_layer = TileMapLayer.new()
	tile_layer.name = "TinggenCityTiles_400x400"
	tile_layer.add_to_group("city_tile_map")
	tile_layer.position = MAP_ORIGIN
	tile_layer.tile_set = _create_runtime_tileset()
	tile_layer.rendering_quadrant_size = 32
	tile_layer.physics_quadrant_size = 32
	tile_layer.visible = false
	add_child(tile_layer)

	for y in range(MAP_SIZE.y):
		for x in range(MAP_SIZE.x):
			var cell := Vector2i(x, y)
			var kind: TileKind = _classify_color(layout_image.get_pixelv(cell))
			if manual_overrides.has(cell):
				kind = manual_overrides[cell]
			ground_layer.set_cell(cell, 0, Vector2i(kind, 0), 0)
			tile_layer.set_cell(cell, 0, Vector2i(kind, 0), 0)
	ground_layer.update_internals()
	tile_layer.update_internals()
	print("Tinggen city map loaded: %d tiles, world rect=%s" % [MAP_SIZE.x * MAP_SIZE.y, tile_layer.get_used_rect()])
	_create_semantic_anchors()


func tile_to_world(cell: Vector2i) -> Vector2:
	return MAP_ORIGIN + Vector2((cell.x - cell.y) * 32.0, (cell.x + cell.y) * 16.0)


func cell_to_world(cell: Vector2i) -> Vector2:
	return tile_layer.to_global(tile_layer.map_to_local(cell))


func find_nearest_road_cell(origin: Vector2i, max_radius := 20, reserved := {}) -> Vector2i:
	if _is_valid_cell(origin) and get_cell_kind(origin) == TileKind.ROAD and not reserved.has(origin):
		return origin
	for radius in range(1, max_radius + 1):
		for y in range(origin.y - radius, origin.y + radius + 1):
			for x in range(origin.x - radius, origin.x + radius + 1):
				if abs(x - origin.x) != radius and abs(y - origin.y) != radius:
					continue
				var cell := Vector2i(x, y)
				if _is_valid_cell(cell) and get_cell_kind(cell) == TileKind.ROAD and not reserved.has(cell):
					return cell
	return origin


func get_layout_texture() -> ImageTexture:
	return layout_texture


func get_cell_kind(cell: Vector2i) -> int:
	if not _is_valid_cell(cell):
		return -1
	return _classify_color(layout_image.get_pixelv(cell))


func set_cell_kind(cell: Vector2i, kind: int) -> bool:
	if not _is_valid_cell(cell) or not PALETTE.has(kind):
		return false
	layout_image.set_pixelv(cell, PALETTE[kind])
	layout_texture.update(layout_image)
	ground_layer.set_cell(cell, 0, Vector2i(kind, 0), 0)
	tile_layer.set_cell(cell, 0, Vector2i(kind, 0), 0)
	layout_changed.emit(cell, kind)
	return true


func save_layout() -> Error:
	var absolute_path := ProjectSettings.globalize_path(LAYOUT_PATH)
	var error := layout_image.save_png(absolute_path)
	if error == OK:
		layout_saved.emit(absolute_path)
	else:
		push_error("Failed to save corrected city layout: %s" % error)
	return error


func _is_valid_cell(cell: Vector2i) -> bool:
	return cell.x >= 0 and cell.y >= 0 and cell.x < MAP_SIZE.x and cell.y < MAP_SIZE.y


func _create_runtime_tileset() -> TileSet:
	var tile_set := TileSet.new()
	tile_set.tile_shape = TileSet.TILE_SHAPE_ISOMETRIC
	tile_set.tile_layout = TileSet.TILE_LAYOUT_DIAMOND_DOWN
	tile_set.tile_offset_axis = TileSet.TILE_OFFSET_AXIS_HORIZONTAL
	tile_set.tile_size = TILE_SIZE
	tile_set.add_physics_layer()
	tile_set.set_physics_layer_collision_layer(0, 1)
	tile_set.set_physics_layer_collision_mask(0, 0)
	tile_set.add_navigation_layer()

	var atlas := TileSetAtlasSource.new()
	var tile_texture := load(TILE_TEXTURE_PATH) as Texture2D
	if tile_texture == null:
		push_error("Cannot load imported tile atlas texture: " + TILE_TEXTURE_PATH)
		return tile_set
	atlas.texture = tile_texture
	atlas.texture_region_size = TILE_SIZE
	for kind in range(TileKind.size()):
		var coords := Vector2i(kind, 0)
		atlas.create_tile(coords)
	tile_set.add_source(atlas, 0)
	for kind in range(TileKind.size()):
		var coords := Vector2i(kind, 0)
		var tile_data := atlas.get_tile_data(coords, 0)
		if kind == TileKind.ROAD:
			tile_data.set_navigation_polygon(0, _create_tile_navigation())
		else:
			tile_data.set_collision_polygons_count(0, 1)
			tile_data.set_collision_polygon_points(0, 0, _diamond())
	return tile_set


func _create_ground_tileset() -> TileSet:
	var tile_set := TileSet.new()
	tile_set.tile_shape = TileSet.TILE_SHAPE_ISOMETRIC
	tile_set.tile_layout = TileSet.TILE_LAYOUT_DIAMOND_DOWN
	tile_set.tile_offset_axis = TileSet.TILE_OFFSET_AXIS_HORIZONTAL
	tile_set.tile_size = TILE_SIZE
	var atlas := TileSetAtlasSource.new()
	var ground_texture := load(GROUND_TEXTURE_PATH) as Texture2D
	if ground_texture == null:
		push_error("Cannot load temporary ground terrain: " + GROUND_TEXTURE_PATH)
		return tile_set
	atlas.texture = ground_texture
	atlas.texture_region_size = TILE_SIZE
	for kind in range(TileKind.size()):
		atlas.create_tile(Vector2i(kind, 0))
	tile_set.add_source(atlas, 0)
	return tile_set


func _create_tile_navigation() -> NavigationPolygon:
	var navigation := NavigationPolygon.new()
	navigation.vertices = _diamond()
	navigation.add_polygon(PackedInt32Array([0, 1, 2, 3]))
	return navigation


func _diamond() -> PackedVector2Array:
	return PackedVector2Array([Vector2(0, -16), Vector2(32, 0), Vector2(0, 16), Vector2(-32, 0)])


func _classify_color(color: Color) -> TileKind:
	var nearest_kind: TileKind = TileKind.LAND
	var nearest_distance := INF
	for kind in PALETTE:
		var target: Color = PALETTE[kind]
		var distance := Vector3(color.r - target.r, color.g - target.g, color.b - target.b).length_squared()
		if distance < nearest_distance:
			nearest_distance = distance
			nearest_kind = kind
	return nearest_kind


func _load_manual_overrides() -> Dictionary:
	var result := {}
	if not FileAccess.file_exists(OVERRIDES_PATH):
		return result
	var file := FileAccess.open(OVERRIDES_PATH, FileAccess.READ)
	if file == null:
		return result
	var parsed = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		push_warning("Manual overrides JSON is invalid")
		return result
	var cells = parsed.get("cells", [])
	if not cells is Array:
		return result
	for entry in cells:
		if not entry is Dictionary:
			continue
		var cell := Vector2i(int(entry.get("x", -1)), int(entry.get("y", -1)))
		var type_name := str(entry.get("type", ""))
		if cell.x >= 0 and cell.y >= 0 and cell.x < MAP_SIZE.x and cell.y < MAP_SIZE.y and TYPE_NAMES.has(type_name):
			result[cell] = TYPE_NAMES[type_name]
	return result


func _create_semantic_anchors() -> void:
	var anchors := Node2D.new()
	anchors.name = "SemanticAnchors"
	add_child(anchors)
	var definitions := {
		"central_square_north": Vector2i(139, 172), "central_square_south": Vector2i(139, 208),
		"central_square_west": Vector2i(121, 190), "central_square_east": Vector2i(157, 190),
		"north_district": Vector2i(145, 83), "east_garden": Vector2i(245, 155),
		"east_bridge": Vector2i(278, 218), "south_district": Vector2i(142, 312),
		"waterfront_west": Vector2i(45, 220), "south_exit": Vector2i(76, 385),
		"academy_entrance": Vector2i(315, 218), "market_street": Vector2i(105, 244)
	}
	for anchor_name in definitions:
		var marker := Marker2D.new()
		marker.name = anchor_name
		marker.position = tile_to_world(definitions[anchor_name])
		marker.add_to_group("semantic_anchor")
		marker.add_to_group("npc_spawn_anchor")
		anchors.add_child(marker)
