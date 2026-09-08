extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	assert(OS.get_environment("CAMPUS_LIVE_API_OPT_IN") == "1", "paid test requires explicit runner")
	create_timer(240).timeout.connect(func(): quit(1))
	var bridge := root.get_node("SimulationBridge")
	for _attempt in range(400):
		if not (bridge.get("campus_snapshot") as Dictionary).is_empty():
			break
		await create_timer(0.05).timeout
	assert(bridge.campus_snapshot.clock.phase == "late_night")
	assert(bridge.campus_snapshot.cognition.provider.thinking_mode == "disabled")
	var transition := root.get_node("OvernightTransition")
	bridge.advance_campus_phase()
	assert(transition.is_active() and paused)
	var reply: Array = await bridge.campus_phase_advanced
	assert(reply[0])
	assert(bridge.campus_snapshot.clock.phase == "morning")
	assert(bridge.campus_snapshot.cognition.provider.last_result.state == "accepted")
	assert(bridge.campus_snapshot.cognition.usage.provider_errors == 0)
	await create_timer(0.55).timeout
	assert(not transition.is_active() and not paused)
	var calls: int = bridge.campus_snapshot.cognition.usage.calls
	bridge.advance_campus_phase()
	var afternoon: Array = await bridge.campus_phase_advanced
	assert(afternoon[0])
	assert(bridge.campus_snapshot.cognition.usage.calls == calls)
	print("CAMPUS_LIVE_API_FLOW_OK real_deepseek production_options overnight_transition intraday_no_requests")
	quit(0)
