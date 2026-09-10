"""One deliberation window per day; execution never asks a model to replan.

Plans are intentions, not reservations or future facts. Task ownership, actual
resources, routes and protected commitments remain checked at execution time.
"""
from collections import Counter
from copy import deepcopy

from simulation.domain.entities import PHASES
from simulation.systems.campus_decisions import rank_campus_npc_activities, reserve_decision_destination, _has_capacity
from simulation.systems.campus_schedules import current_schedule_slot
from simulation.systems.transactions import TransactionContext


def make_daily_planner(runtime, graph, definitions, policy, interaction_policy, messaging_policy, outing_handler=None):
    def prepare(context):
        state = context.state
        ledger = state.cognition.get("daily_plans", {})
        if ledger.get("day") == state.clock.day:
            return {"daily_planned_count": 0}
        # A private preview permits future opening-hour checks without changing
        # the real clock, locations, needs, events or long-term goal ledger.
        preview = state.clone()
        preview.processed_commands.clear()
        preview.cognition.pop("daily_plans", None)
        scratch = TransactionContext(preview, context.rng, context.command)
        phases = [phase.value for phase in PHASES]
        plans = {}
        occupancy = {phase: Counter() for phase in phases}
        from simulation.systems.campus_clubs import club_has_activity
        for actor_id in sorted(state.population):
            if actor_id == "player":
                continue
            options = {}
            free_options = {}
            for phase in phases:
                preview.clock.phase = phase
                preview.action_economy["actors"][actor_id]["major_remaining"] = state.action_economy["policy"]["phases"][phase]["major_actions"]
                schedule = current_schedule_slot(preview, actor_id)
                candidates = rank_campus_npc_activities(scratch, actor_id, schedule, graph, definitions, policy, occupancy[phase])
                candidates = [candidate for candidate in candidates if candidate["activity_id"] != "CLUB_ACTIVITY" or any(
                    club_has_activity(preview, club, state.clock.day, phase)
                    for club in preview.population[actor_id].get("club_ids", ()))]
                options[phase] = deepcopy(candidates[:runtime.policy.candidate_limit] or [dict(schedule)])
                if actor_id in state.cognition.get("focused_ids", ()):
                    from simulation.systems.campus_trade import procurement_candidates
                    free_options[phase] = procurement_candidates(preview, actor_id, graph)[:runtime.policy.candidate_limit]
            # Legacy saves/new worlds bootstrap locally. Only a new morning is
            # allowed to send autonomous daily planning requests to a provider.
            social_options = ()
            if state.clock.phase == "morning" and runtime.provider.configured and actor_id in state.cognition.get("focused_ids", ()):
                from simulation.cognition.social_planning import build_social_options
                social_options = build_social_options(preview, actor_id, options, definitions, interaction_policy)
            slots = runtime.plan_day(state, actor_id, options, social_options, free_options) if state.clock.phase == "morning" else None
            planned_source = "llm" if slots is not None else "rule"
            if slots is None:
                slots = {phase: deepcopy(options[phase][0]) for phase in phases}
            for phase, slot in slots.items():
                slot.update(day=state.clock.day, phase=phase, planned_day=state.clock.day)
                slot["planned_source"] = planned_source
                reserve_decision_destination(graph, occupancy[phase], slot.get("location_id", ""))
            plans[actor_id] = slots
        state.cognition["daily_plans"] = {"schema_version": 1, "day": state.clock.day,
            "created_phase": state.clock.phase, "actors": plans}
        from simulation.systems.campus_social_coordination import coordinate_daily_social
        from simulation.systems.campus_life import enroll_chosen_plans
        enroll_chosen_plans(context, plans)
        if outing_handler is not None:
            from simulation.systems.campus_outings import invite_chosen_outings
            invite_chosen_outings(context, plans, outing_handler)
        coordinate_daily_social(context, plans, messaging_policy)
        context.emit("NPC_DAILY_PLANS_PREPARED", "已整理本日安排；日内按计划执行并核对实际条件。",
            visibility="private", knowledge_tags=["schedule", "planning"],
            payload={"day": state.clock.day, "actor_count": len(plans), "bootstrap": state.clock.phase != "morning"})
        return {"daily_planned_count": len(plans)}

    def select(context, actor_id, schedule, occupancy):
        state = context.state
        ledger = state.cognition.get("daily_plans", {})
        plan = ledger.get("actors", {}).get(actor_id, {}).get(state.clock.phase)
        if ledger.get("day") != state.clock.day or not plan:
            return schedule  # Old/missing slots never trigger day-time model work.
        chosen = deepcopy(plan)
        if chosen.get("parameters", {}).get("outing_intent"):
            # Actual confirmed appointments are selected by the shared runtime
            # wrapper. An unaccepted proposal must not become a forced visit.
            chosen = dict(schedule)
        sid = chosen.get("parameters", {}).get("life_session_id")
        if sid:
            from simulation.systems.campus_life import participant
            record = participant(state, actor_id, sid)
            if not record or record.get("status") != "enrolled":
                chosen = dict(schedule)  # Cancelled/failed enrollment never forces a visit or model replan.
        # New duties and lost access invalidate an intention, not reality.
        actor = state.population[actor_id]
        emergency = max(actor.get("needs", {}).get(key, 0) for key in ("rest", "food", "safety"))
        if int(schedule.get("priority", 0)) >= policy.protected_schedule_priority and emergency < policy.emergency_need_threshold:
            if (chosen.get("activity_id"), chosen.get("location_id")) != (schedule.get("activity_id"), schedule.get("location_id")):
                chosen = dict(schedule)
        if chosen.get("personal_goal_id"):
            from simulation.systems.campus_goals import goal_step
            from simulation.systems.campus_vitals import actor_layer
            from simulation.systems.campus_departures import active_departure
            topic = chosen.get("parameters", {}).get("topic_id")
            goal = state.cognition.get("long_term_plans", {}).get("actors", {}).get(actor_id, {}).get(chosen["personal_goal_id"])
            if (actor_layer(state, actor_id) != "surface" or active_departure(state, actor_id)
                    or not goal or (topic and not str(chosen.get("candidate_id", "")).endswith(":" + goal_step(state, actor_id, goal)))):
                chosen = dict(schedule)
        destination = chosen.get("location_id", "")
        if (not _has_capacity(graph, occupancy, destination)
                or graph.shortest_route(actor["current_location_id"], destination, phase=state.clock.phase,
                                        access_tags=actor.get("access_tags", ())) is None):
            chosen = dict(schedule)
        chosen.update(day=state.clock.day, phase=state.clock.phase)
        chosen.setdefault("decision_source", "schedule")
        chosen.setdefault("candidate_count", 1)
        reserve_decision_destination(graph, occupancy, chosen.get("location_id", ""))
        return chosen

    return prepare, select


def valid_free_errand(state, errand):
    if not isinstance(errand, dict) or errand.get("activity_id") != "BUY_ITEM" or errand.get("action_class") != "free":
        return False
    params = errand.get("parameters")
    if not isinstance(params, dict):
        return False
    shop_id, item_id = params.get("shop_id"), params.get("item_id")
    if not isinstance(shop_id, str) or not isinstance(item_id, str):
        return False
    shop = state.inventories.get("shops", {}).get(shop_id, {})
    return (bool(shop) and item_id in shop.get("accepted_item_ids", ())
        and errand.get("location_id") == shop.get("location_id")
        and type(params.get("quantity")) is int and params["quantity"] > 0
        and type(errand.get("max_unit_price")) is int and errand["max_unit_price"] > 0)


def daily_plans_invariant(state):
    ledger = state.cognition.get("daily_plans")
    if ledger is None:
        return
    if ledger.get("schema_version") != 1 or type(ledger.get("day")) is not int or not 1 <= ledger["day"] <= state.clock.day:
        yield "invalid daily planning ledger"
        return
    phases = {phase.value for phase in PHASES}
    for actor_id, slots in ledger.get("actors", {}).items():
        if actor_id == "player" or actor_id not in state.population or set(slots) != phases:
            yield "invalid daily plan actor/slots"
            continue
        for phase, plan in slots.items():
            if plan.get("day") != ledger["day"] or plan.get("phase") != phase or plan.get("location_id") not in state.places:
                yield "invalid daily plan clock/location"
            errands = plan.get("free_errands", [])
            if not isinstance(errands, list):
                yield "invalid daily free errands"
                continue
            for errand in errands:
                if not valid_free_errand(state, errand):
                    yield "invalid daily free errand"
            social = plan.get("social_intent")
            if social is not None and (not isinstance(social, dict)
                    or social.get("target_id") not in state.population
                    or social.get("target_id") in ("player", actor_id)
                    or social.get("phase") != phase or social.get("location_id") != plan.get("location_id")
                    or not isinstance(social.get("intent_id"), str)
                    or not isinstance(social.get("reason"), str)
                    or not isinstance(social.get("target_name"), str)
                    or not isinstance(social.get("model_reason"), str)
                    or not isinstance(social.get("candidate_id"), str)
                    or social.get("fallback") != "wait_next_day"):
                yield "invalid daily social intention"
    receipts = state.cognition.get("social_agenda_receipts")
    if receipts is not None:
        if not isinstance(receipts, dict) or type(receipts.get("day")) is not int or not 1 <= receipts["day"] <= state.clock.day or not isinstance(receipts.get("actors"), dict):
            yield "invalid social agenda receipts"
            return
        for actor_id, receipt in receipts["actors"].items():
            if (actor_id not in state.population or actor_id == "player" or not isinstance(receipt, dict)
                    or receipt.get("target_id") not in state.population or receipt.get("target_id") in (actor_id, "player")
                    or receipt.get("phase") not in phases
                    or receipt.get("status") not in {"accepted", "rejected", "not_met", "busy", "cooldown", "conditions_changed", "declined"}):
                yield "invalid social agenda receipt"
