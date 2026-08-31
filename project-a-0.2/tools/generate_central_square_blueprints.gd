extends SceneTree

const MAP_SIZE := 64
const CELL := 28
const MARGIN := 112
const TILE_W := 64
const TILE_H := 32

enum Kind { VOID, ROAD, SIDEWALK, PLAZA, BUILDING, GARDEN }

const COLORS := {
	Kind.VOID: "#304b3a",
	Kind.ROAD: "#505762",
	Kind.SIDEWALK: "#aaa39a",
	Kind.PLAZA: "#c9bda5",
	Kind.BUILDING: "#6a4b40",
	Kind.GARDEN: "#426b46"
}

const BUILDINGS: Array[Rect2i] = [
	Rect2i(13, 2, 10, 7), Rect2i(25, 2, 7, 7), Rect2i(35, 2, 10, 7),
	Rect2i(2, 13, 7, 10), Rect2i(13, 13, 9, 8), Rect2i(42, 13, 9, 8), Rect2i(55, 13, 7, 10),
	Rect2i(13, 42, 9, 9), Rect2i(42, 42, 9, 9), Rect2i(2, 42, 7, 10), Rect2i(55, 42, 7, 10),
	Rect2i(13, 55, 10, 7), Rect2i(25, 55, 7, 7), Rect2i(35, 55, 10, 7)
]


func _init() -> void:
	var output_dir := ProjectSettings.globalize_path("res://assets/maps/blueprints")
	DirAccess.make_dir_recursive_absolute(output_dir)
	_write_asset(output_dir + "/central_square_64x64_orthographic", _make_orthographic_svg())
	_write_asset(output_dir + "/central_square_64x64_isometric", _make_isometric_svg())
	quit()


func _kind(cell: Vector2i) -> Kind:
	var delta := cell - Vector2i(32, 32)
	var distance_squared := delta.x * delta.x + delta.y * delta.y
	if distance_squared <= 25:
		return Kind.GARDEN
	if distance_squared <= 144:
		return Kind.PLAZA
	if _is_road(cell):
		return Kind.ROAD
	if _building_at(cell) >= 0:
		return Kind.BUILDING
	if _touches_road_or_plaza(cell):
		return Kind.SIDEWALK
	return Kind.VOID


func _is_road(cell: Vector2i) -> bool:
	if cell.x >= 30 and cell.x <= 34:
		return true
	if cell.y >= 30 and cell.y <= 34:
		return true
	if cell.y >= 9 and cell.y <= 11 and cell.x >= 1 and cell.x <= 62:
		return true
	if cell.y >= 52 and cell.y <= 54 and cell.x >= 1 and cell.x <= 62:
		return true
	if cell.x >= 9 and cell.x <= 11 and cell.y >= 9 and cell.y <= 54:
		return true
	if cell.x >= 52 and cell.x <= 54 and cell.y >= 9 and cell.y <= 54:
		return true
	if cell.y >= 22 and cell.y <= 24 and ((cell.x >= 10 and cell.x <= 30) or (cell.x >= 34 and cell.x <= 53)):
		return true
	if cell.y >= 40 and cell.y <= 42 and ((cell.x >= 10 and cell.x <= 30) or (cell.x >= 34 and cell.x <= 53)):
		return true
	return false


func _building_at(cell: Vector2i) -> int:
	for index in range(BUILDINGS.size()):
		if BUILDINGS[index].has_point(cell):
			return index
	return -1


func _touches_road_or_plaza(cell: Vector2i) -> bool:
	for offset: Vector2i in [Vector2i.LEFT, Vector2i.RIGHT, Vector2i.UP, Vector2i.DOWN]:
		var neighbor := cell + offset
		if neighbor.x < 0 or neighbor.y < 0 or neighbor.x >= MAP_SIZE or neighbor.y >= MAP_SIZE:
			continue
		var delta := neighbor - Vector2i(32, 32)
		if delta.x * delta.x + delta.y * delta.y <= 144 or _is_road(neighbor):
			return true
	return false


func _make_orthographic_svg() -> String:
	var width := MARGIN * 2 + MAP_SIZE * CELL
	var height := MARGIN * 2 + MAP_SIZE * CELL
	var svg := _svg_header(width, height, "Central Square 64x64 Orthographic Blueprint")
	svg += '<rect width="100%" height="100%" fill="#171d22"/>'

	for y in range(MAP_SIZE):
		for x in range(MAP_SIZE):
			var px := MARGIN + x * CELL
			var py := MARGIN + y * CELL
			svg += '<rect x="%d" y="%d" width="%d" height="%d" fill="%s" stroke="#20262b" stroke-width="1"/>' % [px, py, CELL, CELL, COLORS[_kind(Vector2i(x, y))]]

	for coordinate in range(0, MAP_SIZE + 1, 4):
		var position := MARGIN + coordinate * CELL
		svg += '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#e8dfc8" stroke-opacity="0.38" stroke-width="2"/>' % [position, MARGIN, position, MARGIN + MAP_SIZE * CELL]
		svg += '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#e8dfc8" stroke-opacity="0.38" stroke-width="2"/>' % [MARGIN, position, MARGIN + MAP_SIZE * CELL, position]
		if coordinate < MAP_SIZE:
			svg += _text(position + 4, MARGIN - 14, str(coordinate), 17, "#f4ecd8")
			svg += _text(MARGIN - 42, position + 20, str(coordinate), 17, "#f4ecd8")

	var chunk_position := MARGIN + 32 * CELL
	svg += '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#ffd166" stroke-width="6"/>' % [chunk_position, MARGIN, chunk_position, MARGIN + MAP_SIZE * CELL]
	svg += '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#ffd166" stroke-width="6"/>' % [MARGIN, chunk_position, MARGIN + MAP_SIZE * CELL, chunk_position]
	svg += _text(MARGIN, 42, "CENTRAL SQUARE - 64 x 64 TILE BLUEPRINT", 26, "#ffffff")
	svg += _text(MARGIN, 72, "Coordinates mark every 4 tiles. Yellow lines are 32 x 32 chunk boundaries.", 18, "#d8d2c4")
	svg += _legend(MARGIN, height - 66)
	return svg + "</svg>"


func _make_isometric_svg() -> String:
	var width := 4352
	var height := 2304
	var origin := Vector2(width * 0.5, 112)
	var svg := _svg_header(width, height, "Central Square 64x64 Isometric Projection")
	svg += '<rect width="100%" height="100%" fill="#17231d"/>'

	for sum in range(0, MAP_SIZE * 2 - 1):
		for x in range(MAP_SIZE):
			var y := sum - x
			if y < 0 or y >= MAP_SIZE:
				continue
			var center := origin + Vector2((x - y) * TILE_W * 0.5, (x + y) * TILE_H * 0.5)
			var points := "%d,%d %d,%d %d,%d %d,%d" % [center.x, center.y - 16, center.x + 32, center.y, center.x, center.y + 16, center.x - 32, center.y]
			svg += '<polygon points="%s" fill="%s" stroke="#252c2c" stroke-width="1"/>' % [points, COLORS[_kind(Vector2i(x, y))]]

	for index in range(BUILDINGS.size()):
		svg += _iso_building(BUILDINGS[index], origin, 88 + (index % 3) * 16)

	var fountain_center := origin + Vector2(0, 32 * TILE_H)
	var fountain_points := "%d,%d %d,%d %d,%d %d,%d" % [fountain_center.x, fountain_center.y - 120, fountain_center.x + 240, fountain_center.y, fountain_center.x, fountain_center.y + 120, fountain_center.x - 240, fountain_center.y]
	svg += '<polygon points="%s" fill="#3885a0" stroke="#c1bbb0" stroke-width="14"/>' % fountain_points
	svg += _text(70, 54, "CENTRAL SQUARE - EXACT 64x32 ISOMETRIC PROJECTION", 28, "#ffffff")
	svg += _text(70, 86, "Generated from the same 64x64 tile data as the orthographic blueprint.", 19, "#d8d2c4")
	return svg + "</svg>"


func _iso_building(area: Rect2i, origin: Vector2, height: int) -> String:
	var first := area.position
	var last := area.position + area.size - Vector2i.ONE
	var footprint := PackedVector2Array([
		_iso_center(first, origin) + Vector2(0, -16),
		_iso_center(Vector2i(last.x, first.y), origin) + Vector2(32, 0),
		_iso_center(last, origin) + Vector2(0, 16),
		_iso_center(Vector2i(first.x, last.y), origin) + Vector2(-32, 0)
	])
	var roof := PackedVector2Array()
	for point in footprint:
		roof.append(point - Vector2(0, height))
	var result := '<polygon points="%s" fill="#493b43"/>' % _points([roof[1], roof[2], footprint[2], footprint[1]])
	result += '<polygon points="%s" fill="#6b5148"/>' % _points([roof[2], roof[3], footprint[3], footprint[2]])
	result += '<polygon points="%s" fill="%s" stroke="#a39590" stroke-width="3"/>' % [_points(roof), "#81716f"]
	return result


func _iso_center(cell: Vector2i, origin: Vector2) -> Vector2:
	return origin + Vector2((cell.x - cell.y) * TILE_W * 0.5, (cell.x + cell.y) * TILE_H * 0.5)


func _points(values: Array) -> String:
	var result := ""
	for value: Vector2 in values:
		result += (" " if not result.is_empty() else "") + "%d,%d" % [value.x, value.y]
	return result


func _legend(x: int, y: int) -> String:
	var labels := ["Blocked", "Road", "Sidewalk", "Plaza", "Building", "Garden/Fountain"]
	var kinds := [Kind.VOID, Kind.ROAD, Kind.SIDEWALK, Kind.PLAZA, Kind.BUILDING, Kind.GARDEN]
	var result := ""
	for index in range(labels.size()):
		var px := x + index * 275
		result += '<rect x="%d" y="%d" width="25" height="25" fill="%s"/>' % [px, y, COLORS[kinds[index]]]
		result += _text(px + 34, y + 20, labels[index], 17, "#f3ecdc")
	return result


func _svg_header(width: int, height: int, title: String) -> String:
	return '<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d"><title>%s</title>' % [width, height, width, height, title]


func _text(x: int, y: int, value: String, size: int, color: String) -> String:
	return '<text x="%d" y="%d" font-family="Arial, sans-serif" font-size="%d" fill="%s">%s</text>' % [x, y, size, color, value]


func _write_asset(base_path: String, svg: String) -> void:
	var svg_file := FileAccess.open(base_path + ".svg", FileAccess.WRITE)
	if svg_file == null:
		push_error("Cannot create " + base_path + ".svg")
		return
	svg_file.store_string(svg)
	svg_file.close()

	var image := Image.new()
	var error := image.load_svg_from_string(svg, 1.0)
	if error != OK:
		push_error("Cannot rasterize " + base_path + ".svg: " + error_string(error))
		return
	error = image.save_png(base_path + ".png")
	if error != OK:
		push_error("Cannot save " + base_path + ".png: " + error_string(error))
