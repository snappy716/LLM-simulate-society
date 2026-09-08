"""Finite social intentions, chosen overnight, never guaranteed encounters."""
from copy import deepcopy
from simulation.systems.campus_messaging import are_phone_contacts
from simulation.systems.campus_schedules import current_schedule_slot


def build_social_options(preview, actor_id, daily_options, definitions, policy):
    from simulation.systems.campus_interactions import _legal_intents
    actor = preview.population[actor_id]
    known = [target for target in preview.population if target not in (actor_id, "player") and (
        preview.relationships.get(actor_id, {}).get(target, {}).get("familiarity", 0) > 0
        or preview.relationships.get(actor_id, {}).get(target, {}).get("closeness", 0) > 0
        or are_phone_contacts(preview, actor_id, target))]
    known.sort(key=lambda target: (-preview.relationships.get(actor_id, {}).get(target, {}).get("familiarity", 0), target))
    original_phase = preview.clock.phase
    by_phase = {}
    recent = preview.cognition.get("interactions", {}).get("recent", [])[-48:]
    try:
        for phase, choices in daily_options.items():
            preview.clock.phase = phase
            candidates = []
            for target_id in known[:12]:
                target = preview.population[target_id]
                target_slot = current_schedule_slot(preview, target_id)
                for slot in choices:
                    if slot["location_id"] != target_slot["location_id"]:
                        continue
                    saved = [(person, deepcopy(person.get("current_activity")), person.get("current_location_id")) for person in (actor, target)]
                    try:
                        for person, schedule in ((actor, slot), (target, target_slot)):
                            definition = definitions.get(schedule["activity_id"])
                            person["current_activity"] = {"activity_id": schedule["activity_id"], "effects": {"category": definition.category if definition else ""}}
                            person["current_location_id"] = schedule["location_id"]
                        intents = _legal_intents(preview, actor_id, target_id, policy)
                    finally:
                        for person, activity, location in saved:
                            if activity is None:
                                person.pop("current_activity", None)
                            else:
                                person["current_activity"] = activity
                            person["current_location_id"] = location
                    for intent in intents[:2]:
                        repeats = sum(r.get("actor_id") == actor_id and r.get("target_id") == target_id
                                      and r.get("intent_id") == intent["intent_id"] for r in recent)
                        candidates.append({"candidate_id": f"social:{phase}:{target_id}:{intent['intent_id']}",
                            "target_id": target_id, "target_name": target.get("display_name", target_id),
                            "phase": phase, "location_id": slot["location_id"], "intent_id": intent["intent_id"],
                            "reason": intent["reason"], "fallback": "wait_next_day",
                            "score": intent["rule_score"] - repeats * 10})
            unique = {r["candidate_id"]: r for r in candidates}
            by_phase[phase] = sorted(unique.values(), key=lambda row: (-row["score"], row["candidate_id"]))[:2]
    finally:
        preview.clock.phase = original_phase
    # Multiple phases remain available; not all five candidates are morning.
    return [entry for index in range(2) for rows in by_phase.values() for entry in rows[index:index + 1]][:5]
