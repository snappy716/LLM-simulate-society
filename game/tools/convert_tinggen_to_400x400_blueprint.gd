extends Node

const GRID_SIZE := 400
const PREVIEW_SCALE := 4
const SOURCE_PATH := "res://assets/maps/blueprints/tinggen_no_icons.png"
const OUTPUT_DIR := "res://assets/maps/blueprints"

enum Kind { WATER, LAND, ROAD, BUILDING, GARDEN }

const COLORS := {
	Kind.WATER: Color("#244957"),
	Kind.LAND: Color("#344f3d"),
	Kind.ROAD: Color("#aaa49b"),
	Kind.BUILDING: Color("#765548"),
	Kind.GARDEN: Color("#4f7548")
}


func _ready() -> void:
	var source := Image.load_from_file(SOURCE_PATH)
	if source == null or source.is_empty():
		push_error("Cannot load " + SOURCE_PATH)
		get_tree().quit()
		return

	var logical := Image.create(GRID_SIZE, GRID_SIZE, false, Image.FORMAT_RGBA8)
	logical.fill(COLORS[Kind.WATER])

	var sample_width := float(source.get_width()) / GRID_SIZE
	var sample_height := float(source.get_height()) / GRID_SIZE
	var used_rows := GRID_SIZE
	for grid_y in range(GRID_SIZE):
		for grid_x in range(GRID_SIZE):
			var counts := [0, 0, 0, 0, 0]
			var source_x0 := floori(grid_x * sample_width)
			var source_x1 := mini(source.get_width(), ceili((grid_x + 1) * sample_width))
			var source_y0 := floori(grid_y * sample_height)
			var source_y1 := mini(source.get_height(), ceili((grid_y + 1) * sample_height))
			for source_y in range(source_y0, source_y1):
				for source_x in range(source_x0, source_x1):
					counts[_classify(source.get_pixel(source_x, source_y))] += 1
			var majority := 0
			for kind in range(1, counts.size()):
				if counts[kind] > counts[majority]:
					majority = kind
			logical.set_pixel(grid_x, grid_y, COLORS[majority])

	_cleanup_isolated_cells(logical, used_rows)
	_retain_connected_road_network(logical)
	_normalize_road_width(logical)
	var logical_path := OUTPUT_DIR + "/tinggen_no_icons_400x400_logical_blueprint_v2.png"
	var error := logical.save_png(logical_path)
	if error != OK:
		push_error("Cannot save logical blueprint: " + error_string(error))
		get_tree().quit()
		return

	var preview_size := GRID_SIZE * PREVIEW_SCALE
	var preview := Image.create(preview_size, preview_size, false, Image.FORMAT_RGBA8)
	preview.fill(Color("#171d22"))
	for y in range(GRID_SIZE):
		for x in range(GRID_SIZE):
			var color := logical.get_pixel(x, y)
			var origin := Vector2i(x * PREVIEW_SCALE, y * PREVIEW_SCALE)
			for py in range(PREVIEW_SCALE):
				for px in range(PREVIEW_SCALE):
					var pixel_color := color
					if px == PREVIEW_SCALE - 1 or py == PREVIEW_SCALE - 1:
						pixel_color = color.darkened(0.22)
					preview.set_pixel(origin.x + px, origin.y + py, pixel_color)

	# 32x32 Chunk boundaries are yellow; 100-cell guides are pale blue.
	for boundary in range(32, GRID_SIZE, 32):
		_draw_guide(preview, boundary * PREVIEW_SCALE, Color("#ffd166"), 2)
	for boundary in range(100, GRID_SIZE, 100):
		_draw_guide(preview, boundary * PREVIEW_SCALE, Color("#8ecae6"), 3)

	error = preview.save_png(OUTPUT_DIR + "/tinggen_no_icons_400x400_grid_preview_v2.png")
	if error != OK:
		push_error("Cannot save preview: " + error_string(error))
	get_tree().quit()


func _classify(color: Color) -> Kind:
	var value := color.v
	var saturation := color.s
	var hue := color.h

	# Water is dark teal/blue-green.
	if hue >= 0.43 and hue <= 0.62 and saturation >= 0.12 and value <= 0.58:
		return Kind.WATER

	# Roads and plazas are the brightest, least saturated surfaces.
	if value >= 0.52 and saturation <= 0.23:
		return Kind.ROAD
	if hue <= 0.14 and value >= 0.48 and saturation <= 0.30:
		return Kind.ROAD

	# Roofs and building footprints are mostly dark warm brown/gray.
	if value <= 0.43 and (hue <= 0.16 or saturation <= 0.20):
		return Kind.BUILDING
	if hue <= 0.12 and saturation >= 0.12 and value <= 0.56:
		return Kind.BUILDING

	# Vegetation is yellow-green to green.
	if hue >= 0.16 and hue <= 0.44 and saturation >= 0.12:
		return Kind.GARDEN
	return Kind.LAND


func _cleanup_isolated_cells(image: Image, used_rows: int) -> void:
	var copy := image.duplicate()
	for y in range(1, used_rows - 1):
		for x in range(1, GRID_SIZE - 1):
			var center: Color = copy.get_pixel(x, y)
			var neighbors := [
				copy.get_pixel(x - 1, y), copy.get_pixel(x + 1, y),
				copy.get_pixel(x, y - 1), copy.get_pixel(x, y + 1)
			]
			var matching := 0
			for neighbor in neighbors:
				if neighbor.is_equal_approx(center):
					matching += 1
			if matching == 0:
				var best: Color = neighbors[0]
				var best_count := 0
				for candidate in neighbors:
					var candidate_count := 0
					for neighbor in neighbors:
						if neighbor.is_equal_approx(candidate):
							candidate_count += 1
					if candidate_count > best_count:
						best = candidate
						best_count = candidate_count
				image.set_pixel(x, y, best)


func _retain_connected_road_network(image: Image) -> void:
	var visited := PackedByteArray()
	visited.resize(GRID_SIZE * GRID_SIZE)
	var queue: Array[Vector2i] = []
	var road_color: Color = COLORS[Kind.ROAD]

	# Any pale road candidate touching the image edge is a city/world exit.
	for coordinate in range(GRID_SIZE):
		_try_seed_road(image, visited, queue, Vector2i(coordinate, 0), road_color)
		_try_seed_road(image, visited, queue, Vector2i(coordinate, GRID_SIZE - 1), road_color)
		_try_seed_road(image, visited, queue, Vector2i(0, coordinate), road_color)
		_try_seed_road(image, visited, queue, Vector2i(GRID_SIZE - 1, coordinate), road_color)

	# Stable fallback seeds at the south bridge, central square, and east bridge.
	for approximate_seed in [Vector2i(76, 390), Vector2i(150, 198), Vector2i(278, 218)]:
		_seed_nearest_road(image, visited, queue, approximate_seed, road_color, 20)

	var directions := [
		Vector2i(-1, -1), Vector2i(0, -1), Vector2i(1, -1),
		Vector2i(-1, 0), Vector2i(1, 0),
		Vector2i(-1, 1), Vector2i(0, 1), Vector2i(1, 1)
	]
	var read_index := 0
	while read_index < queue.size():
		var cell := queue[read_index]
		read_index += 1
		for direction: Vector2i in directions:
			var neighbor := cell + direction
			if neighbor.x < 0 or neighbor.y < 0 or neighbor.x >= GRID_SIZE or neighbor.y >= GRID_SIZE:
				continue
			var neighbor_index := neighbor.y * GRID_SIZE + neighbor.x
			if visited[neighbor_index] != 0:
				continue
			if image.get_pixelv(neighbor).is_equal_approx(road_color):
				visited[neighbor_index] = 1
				queue.append(neighbor)

	# Pale areas enclosed inside buildings are not part of the street network.
	var copy := image.duplicate()
	for y in range(GRID_SIZE):
		for x in range(GRID_SIZE):
			var cell := Vector2i(x, y)
			if not copy.get_pixelv(cell).is_equal_approx(road_color):
				continue
			if visited[y * GRID_SIZE + x] != 0:
				continue
			image.set_pixelv(cell, _replacement_for_enclosed_light_area(copy, cell))


func _try_seed_road(image: Image, visited: PackedByteArray, queue: Array[Vector2i], cell: Vector2i, road_color: Color) -> void:
	var index := cell.y * GRID_SIZE + cell.x
	if visited[index] == 0 and image.get_pixelv(cell).is_equal_approx(road_color):
		visited[index] = 1
		queue.append(cell)


func _seed_nearest_road(image: Image, visited: PackedByteArray, queue: Array[Vector2i], center: Vector2i, road_color: Color, radius: int) -> void:
	var nearest := Vector2i(-1, -1)
	var nearest_distance := INF
	for y in range(maxi(0, center.y - radius), mini(GRID_SIZE, center.y + radius + 1)):
		for x in range(maxi(0, center.x - radius), mini(GRID_SIZE, center.x + radius + 1)):
			var cell := Vector2i(x, y)
			if not image.get_pixelv(cell).is_equal_approx(road_color):
				continue
			var distance := Vector2(cell).distance_squared_to(Vector2(center))
			if distance < nearest_distance:
				nearest_distance = distance
				nearest = cell
	if nearest.x >= 0:
		_try_seed_road(image, visited, queue, nearest, road_color)


func _replacement_for_enclosed_light_area(image: Image, cell: Vector2i) -> Color:
	var building_color: Color = COLORS[Kind.BUILDING]
	var building_neighbors := 0
	var garden_neighbors := 0
	for y in range(maxi(0, cell.y - 2), mini(GRID_SIZE, cell.y + 3)):
		for x in range(maxi(0, cell.x - 2), mini(GRID_SIZE, cell.x + 3)):
			var neighbor_color := image.get_pixel(x, y)
			if neighbor_color.is_equal_approx(building_color):
				building_neighbors += 1
			elif neighbor_color.is_equal_approx(COLORS[Kind.GARDEN]):
				garden_neighbors += 1
	if building_neighbors >= garden_neighbors and building_neighbors >= 2:
		return building_color
	if garden_neighbors >= 2:
		return COLORS[Kind.GARDEN]
	return COLORS[Kind.LAND]


func _normalize_road_width(image: Image) -> void:
	var road_color: Color = COLORS[Kind.ROAD]
	var original := PackedByteArray()
	original.resize(GRID_SIZE * GRID_SIZE)
	for y in range(GRID_SIZE):
		for x in range(GRID_SIZE):
			if image.get_pixel(x, y).is_equal_approx(road_color):
				original[y * GRID_SIZE + x] = 1

	var skeleton := original.duplicate()
	_thin_binary_mask(skeleton)
	var original_image := image.duplicate()
	var plaza_center := Vector2i(139, 190)
	var plaza_radius_squared := 18 * 18

	for y in range(GRID_SIZE):
		for x in range(GRID_SIZE):
			var index := y * GRID_SIZE + x
			if original[index] == 0:
				continue
			var cell := Vector2i(x, y)
			if cell.distance_squared_to(plaza_center) <= plaza_radius_squared:
				continue
			var near_centerline := false
			for check_y in range(maxi(0, y - 2), mini(GRID_SIZE, y + 3)):
				for check_x in range(maxi(0, x - 2), mini(GRID_SIZE, x + 3)):
					if skeleton[check_y * GRID_SIZE + check_x] != 0:
						near_centerline = true
						break
				if near_centerline:
					break
			if not near_centerline:
				image.set_pixelv(cell, _replacement_for_enclosed_light_area(original_image, cell))


func _thin_binary_mask(mask: PackedByteArray) -> void:
	var changed := true
	var iteration := 0
	while changed and iteration < 80:
		changed = false
		iteration += 1
		for phase in range(2):
			var removals: Array[int] = []
			for y in range(1, GRID_SIZE - 1):
				for x in range(1, GRID_SIZE - 1):
					var index := y * GRID_SIZE + x
					if mask[index] == 0:
						continue
					var p2 := mask[(y - 1) * GRID_SIZE + x]
					var p3 := mask[(y - 1) * GRID_SIZE + x + 1]
					var p4 := mask[y * GRID_SIZE + x + 1]
					var p5 := mask[(y + 1) * GRID_SIZE + x + 1]
					var p6 := mask[(y + 1) * GRID_SIZE + x]
					var p7 := mask[(y + 1) * GRID_SIZE + x - 1]
					var p8 := mask[y * GRID_SIZE + x - 1]
					var p9 := mask[(y - 1) * GRID_SIZE + x - 1]
					var neighbor_count := p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
					if neighbor_count < 2 or neighbor_count > 6:
						continue
					var transitions := 0
					var ring := [p2, p3, p4, p5, p6, p7, p8, p9, p2]
					for ring_index in range(8):
						if ring[ring_index] == 0 and ring[ring_index + 1] != 0:
							transitions += 1
					if transitions != 1:
						continue
					if phase == 0:
						if p2 * p4 * p6 != 0 or p4 * p6 * p8 != 0:
							continue
					else:
						if p2 * p4 * p8 != 0 or p2 * p6 * p8 != 0:
							continue
					removals.append(index)
			if not removals.is_empty():
				changed = true
				for index in removals:
					mask[index] = 0


func _draw_guide(image: Image, coordinate: int, color: Color, width: int) -> void:
	for offset in range(width):
		var position := coordinate + offset
		if position >= image.get_width():
			continue
		for index in range(image.get_width()):
			image.set_pixel(position, index, color)
			image.set_pixel(index, position, color)
