extends SceneTree

const MAP_SIZE := 96
const CELL := 20
const MARGIN := 84

enum Kind { WATER, LAND, ROAD, SIDEWALK, PLAZA, BUILDING, GARDEN }

const COLORS := {
	Kind.WATER: "#244957",
	Kind.LAND: "#344f3d",
	Kind.ROAD: "#555c67",
	Kind.SIDEWALK: "#aaa49b",
	Kind.PLAZA: "#cabda4",
	Kind.BUILDING: "#765548",
	Kind.GARDEN: "#4f7548"
}

const ROADS: Array = [
	# Central north-south avenue and main east-west axes (5 tiles).
	{"w": 5.0, "p": [Vector2(48, 5), Vector2(49, 18), Vector2(47, 31), Vector2(49, 44), Vector2(47, 58), Vector2(50, 72), Vector2(55, 91)]},
	{"w": 5.0, "p": [Vector2(12, 42), Vector2(27, 40), Vector2(38, 42), Vector2(49, 44), Vector2(62, 43), Vector2(76, 46), Vector2(91, 48)]},
	{"w": 5.0, "p": [Vector2(13, 20), Vector2(28, 19), Vector2(42, 20), Vector2(55, 18), Vector2(72, 19)]},
	{"w": 4.0, "p": [Vector2(11, 31), Vector2(25, 29), Vector2(38, 31), Vector2(49, 31), Vector2(63, 30), Vector2(73, 33)]},
	{"w": 4.0, "p": [Vector2(12, 55), Vector2(25, 53), Vector2(36, 55), Vector2(47, 58), Vector2(61, 56), Vector2(76, 57)]},
	{"w": 4.0, "p": [Vector2(14, 67), Vector2(27, 65), Vector2(39, 67), Vector2(50, 72), Vector2(66, 69), Vector2(77, 67)]},
	{"w": 4.0, "p": [Vector2(18, 79), Vector2(31, 76), Vector2(43, 78), Vector2(55, 81), Vector2(70, 79)]},

	# Western coastal spine and inner connectors.
	{"w": 4.0, "p": [Vector2(14, 13), Vector2(10, 24), Vector2(9, 39), Vector2(10, 55), Vector2(13, 70), Vector2(20, 84), Vector2(32, 91)]},
	{"w": 3.0, "p": [Vector2(22, 20), Vector2(20, 31), Vector2(19, 42), Vector2(20, 54), Vector2(23, 66), Vector2(28, 77)]},
	{"w": 3.0, "p": [Vector2(32, 20), Vector2(31, 30), Vector2(31, 40)]},
	{"w": 3.0, "p": [Vector2(35, 44), Vector2(33, 55), Vector2(34, 66), Vector2(31, 76)]},

	# Eastern academy garden loop and river connection.
	{"w": 5.0, "p": [Vector2(68, 8), Vector2(74, 15), Vector2(77, 27), Vector2(76, 42), Vector2(76, 57), Vector2(73, 70)]},
	{"w": 4.0, "p": [Vector2(73, 19), Vector2(84, 16), Vector2(90, 23), Vector2(89, 36), Vector2(82, 43), Vector2(76, 46)]},
	{"w": 4.0, "p": [Vector2(76, 46), Vector2(84, 48), Vector2(92, 48)]},
	{"w": 3.0, "p": [Vector2(80, 57), Vector2(89, 57), Vector2(92, 50)]},

	# Southern dense-street connectors.
	{"w": 3.0, "p": [Vector2(29, 55), Vector2(28, 66), Vector2(31, 76), Vector2(37, 88)]},
	{"w": 3.0, "p": [Vector2(40, 58), Vector2(39, 67), Vector2(43, 78), Vector2(47, 91)]},
	{"w": 3.0, "p": [Vector2(59, 57), Vector2(60, 69), Vector2(62, 79), Vector2(66, 90)]}
]

const BUILDINGS: Array[Rect2i] = [
	Rect2i(17, 8, 10, 8), Rect2i(31, 8, 10, 8), Rect2i(52, 7, 11, 8),
	Rect2i(14, 23, 8, 6), Rect2i(24, 22, 7, 6), Rect2i(34, 23, 9, 6), Rect2i(52, 22, 10, 6),
	Rect2i(13, 34, 10, 6), Rect2i(25, 33, 9, 7), Rect2i(55, 33, 9, 7), Rect2i(65, 34, 8, 7),
	Rect2i(13, 46, 9, 6), Rect2i(24, 44, 8, 8), Rect2i(34, 46, 8, 7), Rect2i(57, 46, 9, 7), Rect2i(67, 48, 7, 6),
	Rect2i(15, 58, 8, 6), Rect2i(24, 57, 7, 6), Rect2i(35, 59, 8, 6), Rect2i(53, 59, 8, 7), Rect2i(64, 59, 9, 7),
	Rect2i(18, 70, 8, 6), Rect2i(29, 69, 7, 6), Rect2i(39, 70, 8, 6), Rect2i(54, 72, 8, 6), Rect2i(64, 71, 8, 6),
	Rect2i(25, 82, 9, 6), Rect2i(37, 81, 8, 7), Rect2i(52, 84, 11, 6), Rect2i(66, 82, 8, 7),
	Rect2i(80, 27, 8, 7), Rect2i(81, 61, 9, 8)
]


func _init() -> void:
	print("Generating 96x96 city blueprint...")
	var directory := ProjectSettings.globalize_path("res://assets/maps/blueprints")
	DirAccess.make_dir_recursive_absolute(directory)
	var svg := _make_svg()
	var base := directory + "/yanhen_full_city_96x96_orthographic"
	var file := FileAccess.open(base + ".svg", FileAccess.WRITE)
	if file == null:
		push_error("Cannot create blueprint SVG")
		quit()
		return
	file.store_string(svg)
	file.close()
	print("Saved SVG: " + base + ".svg")
	var image := Image.new()
	var error := image.load_svg_from_string(svg, 1.0)
	if error == OK:
		image.save_png(base + ".png")
	quit()


func _kind(cell: Vector2i) -> Kind:
	if not _is_land(cell):
		return Kind.WATER

	var plaza_delta := Vector2(cell) - Vector2(49, 45)
	if plaza_delta.length_squared() <= 20.0:
		return Kind.GARDEN
	if plaza_delta.length_squared() <= 56.0:
		return Kind.PLAZA

	var road_distance := _nearest_road_distance(Vector2(cell))
	if road_distance.x <= road_distance.y * 0.5:
		return Kind.ROAD
	if road_distance.x <= road_distance.y * 0.5 + 1.25:
		return Kind.SIDEWALK

	for building in BUILDINGS:
		if building.has_point(cell):
			return Kind.BUILDING

	if _in_east_garden(cell) or _in_north_park(cell):
		return Kind.GARDEN
	return Kind.LAND


func _is_land(cell: Vector2i) -> bool:
	var point := Vector2(cell)
	var city := pow((point.x - 42.0) / 37.0, 2.0) + pow((point.y - 49.0) / 47.0, 2.0) <= 1.0
	var north := Rect2(22, 2, 54, 25).has_point(point)
	var east_campus := pow((point.x - 86.0) / 11.0, 2.0) + pow((point.y - 49.0) / 23.0, 2.0) <= 1.0
	var south_port := Rect2(31, 82, 43, 13).has_point(point)
	return city or north or east_campus or south_port


func _in_east_garden(cell: Vector2i) -> bool:
	return Rect2i(79, 35, 10, 19).has_point(cell)


func _in_north_park(cell: Vector2i) -> bool:
	return Rect2i(63, 10, 9, 8).has_point(cell)


func _nearest_road_distance(point: Vector2) -> Vector2:
	var nearest := INF
	var width := 3.0
	for road in ROADS:
		var points: Array = road["p"]
		for index in range(points.size() - 1):
			var distance := _distance_to_segment(point, points[index], points[index + 1])
			if distance < nearest:
				nearest = distance
				width = road["w"]
	return Vector2(nearest, width)


func _distance_to_segment(point: Vector2, start: Vector2, end: Vector2) -> float:
	var segment := end - start
	var length_squared := segment.length_squared()
	if length_squared == 0.0:
		return point.distance_to(start)
	var t := clampf((point - start).dot(segment) / length_squared, 0.0, 1.0)
	return point.distance_to(start + segment * t)


func _make_svg() -> String:
	var size := MARGIN * 2 + MAP_SIZE * CELL
	var svg := '<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % [size, size, size, size]
	svg += '<rect width="100%" height="100%" fill="#171d22"/>'
	for y in range(MAP_SIZE):
		for x in range(MAP_SIZE):
			var px := MARGIN + x * CELL
			var py := MARGIN + y * CELL
			svg += '<rect x="%d" y="%d" width="%d" height="%d" fill="%s" stroke="#20262b" stroke-width="0.8"/>' % [px, py, CELL, CELL, COLORS[_kind(Vector2i(x, y))]]

	for coordinate in range(0, MAP_SIZE + 1, 4):
		var position := MARGIN + coordinate * CELL
		svg += '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#eee4ce" stroke-opacity="0.28" stroke-width="1.5"/>' % [position, MARGIN, position, MARGIN + MAP_SIZE * CELL]
		svg += '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#eee4ce" stroke-opacity="0.28" stroke-width="1.5"/>' % [MARGIN, position, MARGIN + MAP_SIZE * CELL, position]
		if coordinate < MAP_SIZE:
			svg += _text(position + 3, MARGIN - 11, str(coordinate), 14)
			svg += _text(MARGIN - 35, position + 15, str(coordinate), 14)

	for boundary in [32, 64]:
		var position := MARGIN + boundary * CELL
		svg += '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#ffd166" stroke-width="5"/>' % [position, MARGIN, position, MARGIN + MAP_SIZE * CELL]
		svg += '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#ffd166" stroke-width="5"/>' % [MARGIN, position, MARGIN + MAP_SIZE * CELL, position]

	svg += _text(MARGIN, 34, "YANHEN CITY - 96 x 96 ORTHOGRAPHIC TILE BLUEPRINT", 23)
	svg += _text(MARGIN, 60, "Street widths: major 5 tiles, normal 3-4 tiles. Coordinates every 4 tiles; yellow = 32 tile chunk boundaries.", 15)
	var labels := ["Water", "Land/Blocked", "Road", "Sidewalk", "Plaza", "Building", "Garden"]
	var kinds := [Kind.WATER, Kind.LAND, Kind.ROAD, Kind.SIDEWALK, Kind.PLAZA, Kind.BUILDING, Kind.GARDEN]
	for index in range(labels.size()):
		var x := MARGIN + index * 255
		var y := size - 45
		svg += '<rect x="%d" y="%d" width="20" height="20" fill="%s"/>' % [x, y, COLORS[kinds[index]]]
		svg += _text(x + 28, y + 16, labels[index], 14)
	return svg + "</svg>"


func _text(x: int, y: int, value: String, size: int) -> String:
	return '<text x="%d" y="%d" font-family="Arial, sans-serif" font-size="%d" fill="#f3ecdc">%s</text>' % [x, y, size, value]
