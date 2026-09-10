extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(100).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty(): break
		await create_timer(0.05).timeout
	change_scene_to_file("res://scenes/campus/campus_collab_test.tscn")
	await process_frame
	await process_frame
	var layer: Node = current_scene.get_node("NpcMovementLayer")
	assert(layer.playback_speed == 90.0)
	assert(current_scene.get_node("Player").move_speed == 150.0)
	var speeds: Dictionary = {}
	for index in range(30):
		var who := "campus_student_%03d" % index
		var style: Dictionary = layer._walking_style(who)
		assert(style == layer._walking_style(who))
		assert(style.speed >= 73.0 and style.speed <= 107.0)
		speeds[style.speed] = true
	assert(speeds.size() > 8)
	# Actual bridge command still owns the phase; visual replay never advances it.
	bridge.advance_campus_phase()
	var advanced = await bridge.campus_phase_advanced
	assert(advanced[0])
	var authority: Dictionary = bridge.campus_snapshot.duplicate(true)
	# Explicit rendering-only crowd: no fixture data is submitted to the server.
	var places := {"zone": {"node_type": "region", "map_cell": [0, 0]},
		"start": {"region_id": "zone", "map_cell": [100, 200]},
		"finish": {"region_id": "zone", "map_cell": [500, 200]}}
	var population: Dictionary = {}
	var events: Array = []
	for index in range(14):
		var who := "pacing_%02d" % index
		population[who] = {"display_name": who, "appearance_seed": index,
			"current_location_id": "finish", "current_activity": {"location_id": "finish"}}
		if index < 10:
			events.append({"event_type": "ACTOR_LOCATION_CHANGED", "actor_ids": [who],
				"payload": {"from_id": "start", "to_id": "finish"}})
	layer._clear_replay()
	layer.use_scene_route_anchors = false
	layer.map_origin_cell = Vector2.ZERO
	layer.map_origin_world = Vector2.ZERO
	layer.map_scale = Vector2.ONE
	layer.visibility_margin = 10000.0
	layer._current_map_entry = {"visible_region_ids": ["zone"], "walk_rect": [0,0,1774,887]}
	layer._places = places
	layer._population = population
	layer._replay_movement_events(events, {"population": population})
	await process_frame
	assert(layer.visible_resident_count() == 14)
	assert(layer._running_routes == 4 and layer._pending_routes.size() == 6)
	var still_actor: Node2D = layer._visible_actors.pacing_12
	var still_position := still_actor.global_position
	var initial_positions: Dictionary = {}
	for who in layer._visible_actors:
		initial_positions[who] = layer._visible_actors[who].global_position
	var first_delay := 4.5
	for index in range(4):
		first_delay = minf(first_delay, layer._walking_style("pacing_%02d" % index).delay)
	var sample_time := first_delay + 0.5
	await create_timer(sample_time).timeout
	var moved := 0
	for who in layer._visible_actors:
		var actor: Node2D = layer._visible_actors[who]
		var distance: float = actor.global_position.distance_to(initial_positions[who])
		assert(distance <= 107.0 * (sample_time + 0.1))
		if distance > 0.1: moved += 1
	assert(moved > 0 and moved <= 4)
	assert(still_actor.global_position == still_position)
	assert(still_actor.current_animation == &"idle")
	var paused_positions: Dictionary = {}
	for who in layer._visible_actors:
		paused_positions[who] = layer._visible_actors[who].global_position
	paused = true
	await create_timer(0.3).timeout
	for who in layer._visible_actors:
		assert(layer._visible_actors[who].global_position == paused_positions[who])
	paused = false
	# Wait for normal-speed routes, retaining stopped arrivals while others walk.
	for _attempt in range(600):
		if layer._active_routes == 0: break
		assert(layer._running_routes <= 4)
		await create_timer(0.05).timeout
	assert(layer._active_routes == 0 and layer._pending_routes.is_empty())
	assert(still_actor.global_position == still_position)
	var arrived: Node2D = layer._visible_actors.pacing_00
	var arrived_position := arrived.global_position
	layer._refresh_residents()
	assert(arrived.global_position == arrived_position)
	assert(authority == bridge.campus_snapshot)
	# Map/phase replacement invalidates old callbacks and queued departures.
	layer._replay_movement_events(events, {"population": population})
	var old_generation: int = layer._replay_generation
	layer._clear_replay()
	layer._on_route_finished("old", null, "finish", old_generation)
	assert(layer._active_routes == 0 and layer._running_routes == 0 and layer._pending_routes.is_empty())
	# Controller waypoint pause, exact endpoint and slower animation cadence.
	var npc = load("res://scenes/characters/npc.tscn").instantiate()
	npc.simulation_controlled = true
	root.add_child(npc)
	npc.set_physics_process(false)
	npc.play_simulation_route(PackedVector2Array([Vector2.ZERO, Vector2(1,0), Vector2(2,0)]), 80.0, 0.0, 0.5)
	npc._follow_simulation_route(0.1)
	assert(npc.global_position == Vector2(1,0) and npc.current_animation == &"idle")
	npc._follow_simulation_route(0.2)
	assert(npc.global_position == Vector2(1,0))
	npc._follow_simulation_route(0.4)
	npc._follow_simulation_route(0.1)
	assert(npc.global_position == Vector2(2,0) and npc.velocity == Vector2.ZERO)
	assert(npc.movement_animation_speed < 1.0)
	print("CAMPUS_MOVEMENT_PACING_OK actual_phase_http stable_individual_speed staggered_four_walkers real_stationary_residents pause_waypoints pause_ui no_refresh_snap cancel_old_routes unchanged_authority no_api")
	quit(0)
