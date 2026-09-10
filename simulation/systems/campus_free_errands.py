"""Execute optional errands without replacing a person's primary arrangement."""
from copy import deepcopy

from simulation.actions.commands import CommandSource, SimulationCommand
from simulation.systems.campus_daily_plans import valid_free_errand
from simulation.systems.campus_trade import procurement_candidates
from simulation.systems.campus_medical import ACTION as CLINIC_ACTION, optional_errand_candidates, clinic_candidates, make_medical_handler


def make_free_errand_executor(graph, traverse, inventory_handler, protected_priority):
    def execute(context, actor_id, schedule, phase_command):
        state, actor = context.state, context.state.population[actor_id]
        counts = {"free_errand_count": 0, "free_errand_failed_count": 0, "free_errand_route_steps": 0}
        from simulation.systems.campus_anomaly_meetings import reserved_meeting
        from simulation.systems.campus_departures import active_departure
        if reserved_meeting(state, actor_id) or active_departure(state, actor_id):
            return counts
        ledger = state.cognition.get("daily_plans", {})
        slot = ledger.get("actors", {}).get(actor_id, {}).get(state.clock.phase, {})
        if ledger.get("day") == state.clock.day and slot.get("planned_source") == "llm":
            # Missing/empty choices are an opt-out, including legacy model plans.
            errands = deepcopy(slot.get("free_errands", []))
        else:
            if int(schedule.get("priority", 0)) >= protected_priority or actor.get("active_forum_task_id"):
                return counts
            errands = optional_errand_candidates(state, actor_id, graph, rule_choice=True)[:1]

        def command(index, suffix, action, params):
            return SimulationCommand(
                command_id=f"{phase_command.command_id}:{actor_id}:errand:{index}:{suffix}",
                actor_id=actor_id, action_id=action, expected_world_revision=state.revision,
                parameters=params, issued_day=state.clock.day, issued_phase=state.clock.phase,
                issued_minute=state.clock.minute, source=CommandSource.RULE.value)

        def receipt(index, errand, success, code, message, steps=0):
            counts["free_errand_count" if success else "free_errand_failed_count"] += 1
            context.emit("NPC_FREE_ERRAND_COMPLETED" if success else "NPC_FREE_ERRAND_BLOCKED",
                message, actor_ids=[actor_id], scene_id=actor["current_location_id"],
                payload={"activity_id": errand.get("activity_id", "BUY_ITEM"), "activity_role": "optional_errand", "errand_index": index,
                    "code": code, "parameters": deepcopy(errand.get("parameters", {})), "route_step_count": steps},
                visibility="private", knowledge_tags=["trade", "activity"])

        for index, errand in enumerate(errands):
            if not valid_free_errand(state, errand):
                receipt(index, errand if isinstance(errand, dict) else {}, False, "invalid_errand", "采购安排无效；继续核对主体安排。")
                continue
            wanted = errand["parameters"]
            is_clinic = errand["activity_id"] == CLINIC_ACTION
            if is_clinic:
                current = next(iter(clinic_candidates(state, actor_id, graph)), None)
            else:
                current = next((c for c in procurement_candidates(state, actor_id, graph)
                    if c["parameters"]["shop_id"] == wanted["shop_id"] and c["parameters"]["item_id"] == wanted["item_id"]), None)
            if current is None or current["max_unit_price"] > errand["max_unit_price"]:
                receipt(index, errand, False, "conditions_changed", "可选办事条件已变化，未执行；继续核对主体安排。")
                continue
            params = {} if is_clinic else dict(wanted, quantity=min(wanted["quantity"], current["parameters"]["quantity"]))
            route = graph.shortest_route(actor["current_location_id"], current["location_id"],
                phase=state.clock.phase, access_tags=actor.get("access_tags", ()))
            steps = 0
            if route is None:
                receipt(index, errand, False, "route_unavailable", "目前无法沿开放道路到达；继续核对主体安排。")
                continue
            for step_index, step in enumerate(route.steps):
                outcome = traverse(context, command(index, f"move:{step_index}", "TRAVERSE_LOCATION_PASSAGE", {"passage_id": step.passage_id}))
                if not outcome.success:
                    break
                steps += 1
            counts["free_errand_route_steps"] += steps
            if steps != len(route.steps):
                receipt(index, errand, False, "route_unavailable", "采购途中无法继续通行；从实际位置核对主体安排。", steps)
                continue
            handler = make_medical_handler() if is_clinic else inventory_handler
            outcome = handler(context, command(index, "service" if is_clinic else "buy", errand["activity_id"], params))
            receipt(index, dict(errand, parameters=params), outcome.success, outcome.code, outcome.message, steps)
        return counts
    return execute
