extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	create_timer(90).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	var transition := root.get_node("OvernightTransition")
	for _attempt in range(200):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	var initial: Dictionary = bridge.get("campus_snapshot")
	assert(initial.clock.phase == "late_night" and initial.clock.day == 1)
	assert(initial.cognition.provider.configured)
	assert(initial.cognition.provider.model == "loopback-only")
	var counter := int(bridge.get("_campus_command_counter"))
	var started := Time.get_ticks_msec()
	bridge.advance_campus_phase()
	assert(transition.is_active() and paused)
	bridge.advance_campus_phase()
	assert(int(bridge.get("_campus_command_counter")) == counter + 1)
	var reply: Array = await bridge.campus_phase_advanced
	assert(reply[0], JSON.stringify(reply))
	var elapsed := Time.get_ticks_msec() - started
	await create_timer(0.55).timeout
	assert(not transition.is_active() and not paused)
	var snapshot: Dictionary = bridge.get("campus_snapshot")
	assert(snapshot.clock.day == 2 and snapshot.clock.phase == "morning")
	assert(snapshot.cognition.focused_count == 20)
	assert(snapshot.cognition.usage.calls >= 20)
	assert(snapshot.cognition.usage.fallbacks == 0)
	assert(snapshot.cognition.usage.prompt_tokens == snapshot.cognition.usage.calls * 31)
	assert(snapshot.cognition.usage.completion_tokens == snapshot.cognition.usage.calls * 13)
	var usage: Dictionary = snapshot.cognition.usage.duplicate(true)
	bridge.advance_campus_phase()
	reply = await bridge.campus_phase_advanced
	assert(reply[0])
	assert(bridge.get("campus_snapshot").cognition.usage == usage)
	print("CAMPUS_PARALLEL_FLOW_OK real_game_http real_loopback_model_http all20 four_slots no_fallback exact_billing duplicate_guard intraday_no_requests elapsed_ms=%s no_paid_api" % elapsed)
	quit(0)
