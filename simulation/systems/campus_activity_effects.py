"""Execute real effects for scheduled and player-selected campus activities."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

from simulation.domain.activities import (
    EMOTION_NAMES,
    NEED_NAMES,
    CampusActivityDefinition,
    parse_activity_definition,
)
from simulation.domain.world_state import WorldState
from simulation.systems.content_registry import ContentRegistry
from simulation.systems.time import consume_major_action
from simulation.systems.transactions import TransactionOutcome


PHASE_NEED_DRIFT = {
    "rest": 4,
    "food": 6,
    "safety": 0,
    "social": 3,
    "money": 2,
    "achievement": 5,
    "curiosity": 4,
    "commitment_pressure": 5,
}


def load_campus_activity_definitions(
    registry: ContentRegistry,
) -> Dict[str, CampusActivityDefinition]:
    document = registry.document("actions/campus_activities.json")
    profiles = document.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ValueError("campus activity profiles must be a mapping")
    definitions = {
        activity_id: parse_activity_definition(payload, profiles)
        for activity_id, payload in registry.all("campus_activity").items()
    }
    if not definitions:
        raise ValueError("at least one campus activity definition is required")
    return definitions


def _clamp_meter(value: int) -> int:
    return max(0, min(100, value))


def _apply_meter_deltas(
    actor: Dict[str, Any],
    field_name: str,
    keys: Iterable[str],
    deltas: Mapping[str, int],
) -> Dict[str, Dict[str, int]]:
    meters = actor.setdefault(field_name, {})
    if not isinstance(meters, dict):
        raise ValueError(f"actor {field_name} must be a mapping")
    changes: Dict[str, Dict[str, int]] = {}
    for key in keys:
        before = int(meters.get(key, 0))
        after = _clamp_meter(before + int(deltas.get(key, 0)))
        meters[key] = after
        if before != after:
            changes[key] = {"before": before, "after": after, "delta": after - before}
    return changes


def _aptitude_bonus(actor: Mapping[str, Any], category: str) -> int:
    attributes = actor.get("attributes", {})
    personality = actor.get("personality", {})
    if category in {"study", "research"}:
        total = int(attributes.get("focus", 5)) + int(attributes.get("insight", 5))
        return max(0, total // 5 - 2)
    if category in {"social", "club"}:
        total = int(attributes.get("empathy", 5)) + int(attributes.get("expression", 5))
        return max(0, total // 5 - 2)
    if category == "exploration":
        total = int(attributes.get("insight", 5)) + int(attributes.get("dexterity", 5))
        return max(0, total // 5 - 2)
    if category == "work":
        return max(0, int(personality.get("conscientiousness", 50)) // 25 - 2)
    return 0


def _resolved_knowledge_topic(actor: Mapping[str, Any], topic: str) -> str:
    if topic.startswith("college_"):
        return f"{topic}:{actor.get('college_id') or 'general'}"
    if topic == "professional_practice":
        return f"professional_practice:{actor.get('occupation_id') or 'general'}"
    if topic == "club_practice":
        club_ids = actor.get("club_ids", [])
        return f"club_practice:{club_ids[0] if club_ids else 'general'}"
    return topic


def _apply_knowledge(
    state: WorldState,
    actor_id: str,
    actor: Mapping[str, Any],
    definition: CampusActivityDefinition,
) -> Dict[str, Any]:
    if definition.knowledge_gain <= 0:
        return {"topic": "", "before": 0, "after": 0, "gain": 0}
    topic = _resolved_knowledge_topic(actor, definition.knowledge_topic)
    actors = state.knowledge.setdefault("actors", {})
    actor_knowledge = actors.setdefault(actor_id, {"topics": {}, "total_progress": 0})
    topics = actor_knowledge.setdefault("topics", {})
    before = int(topics.get(topic, 0))
    gain = definition.knowledge_gain + _aptitude_bonus(actor, definition.category)
    after = before + gain
    topics[topic] = after
    actor_knowledge["total_progress"] = int(actor_knowledge.get("total_progress", 0)) + gain
    return {"topic": topic, "before": before, "after": after, "gain": gain}


def advance_campus_phase_upkeep(context) -> Dict[str, int]:
    """Advance needs once, then execute routine free self-care for every actor."""
    summary = {"need_tick_count": 0, "routine_meal_count": 0, "routine_social_count": 0}
    marker = f"{context.state.clock.day}:{context.state.clock.phase}"
    for actor_id, actor in sorted(context.state.population.items()):
        if not isinstance(actor, dict) or actor.get("last_need_tick") == marker:
            continue
        actor["last_need_tick"] = marker
        _apply_meter_deltas(actor, "needs", NEED_NAMES, PHASE_NEED_DRIFT)
        summary["need_tick_count"] += 1
        needs = actor["needs"]
        emotions = actor["emotions"]
        routine_actions: list[str] = []
        wealth_before = int(actor.get("wealth", 0))
        if int(needs.get("food", 0)) >= 65 and wealth_before >= 4:
            needs["food"] = _clamp_meter(int(needs["food"]) - 45)
            actor["wealth"] = wealth_before - 4
            routine_actions.append("EAT_MEAL")
            summary["routine_meal_count"] += 1
        if (
            int(needs.get("social", 0)) >= 80
            and context.state.clock.phase != "late_night"
        ):
            needs["social"] = _clamp_meter(int(needs["social"]) - 20)
            emotions["joy"] = _clamp_meter(int(emotions.get("joy", 0)) + 3)
            routine_actions.append("SHORT_SOCIALIZE")
            summary["routine_social_count"] += 1
        if routine_actions:
            context.emit(
                "NPC_ROUTINE_ACTION_COMPLETED",
                f"{actor.get('display_name', actor_id)} 完成了日常自理。",
                actor_ids=[actor_id],
                scene_id=str(actor.get("current_location_id", "")) or None,
                payload={"actions": routine_actions, "major_action_cost": 0},
                visibility="private",
                knowledge_tags=["campus_activity", "routine"],
            )
    return summary


def make_campus_activity_handler(
    definitions: Mapping[str, CampusActivityDefinition],
    policy,
    activity_settled=None,
):
    def perform(context, command) -> TransactionOutcome:
        actor = context.state.population.get(command.actor_id)
        if not isinstance(actor, dict):
            return TransactionOutcome(False, False, "unknown_actor", "行动者不存在。")
        definition = definitions.get(command.action_id)
        if definition is None:
            return TransactionOutcome(False, False, "unknown_activity", "校园活动不存在。")
        if context.state.clock.phase not in definition.allowed_phases:
            return TransactionOutcome(False, False, "activity_wrong_phase", "当前时段不能进行这项活动。")

        current_location = str(actor.get("current_location_id", ""))
        declared_location = str(command.parameters.get("location_id", current_location))
        if not current_location or declared_location != current_location:
            return TransactionOutcome(False, False, "activity_wrong_location", "必须先到达活动地点。")
        place = context.state.places.get(current_location)
        if not isinstance(place, dict):
            return TransactionOutcome(False, False, "activity_unknown_location", "当前地点不存在。")
        open_phases = place.get("open_phases", [])
        if open_phases and context.state.clock.phase not in open_phases:
            return TransactionOutcome(False, False, "activity_location_closed", "活动地点当前未开放。")

        budget_payload: Dict[str, Any] = {"action_class": definition.action_class}
        if definition.action_class == "major":
            spent = consume_major_action(context.state, policy, command)
            if not spent.success:
                return TransactionOutcome(
                    False,
                    False,
                    spent.code,
                    spent.message,
                    payload=spent.payload,
                )
            budget_payload.update(spent.payload)

        needs = _apply_meter_deltas(actor, "needs", NEED_NAMES, definition.need_deltas)
        emotions = _apply_meter_deltas(
            actor, "emotions", EMOTION_NAMES, definition.emotion_deltas
        )
        wealth_before = int(actor.get("wealth", 0))
        wealth_after = max(0, wealth_before + definition.wealth_delta)
        actor["wealth"] = wealth_after
        knowledge = _apply_knowledge(
            context.state, command.actor_id, actor, definition
        )

        progress = actor.setdefault("activity_progress", {"total": 0, "by_category": {}, "by_activity": {}})
        progress["total"] = int(progress.get("total", 0)) + 1
        categories = progress.setdefault("by_category", {})
        categories[definition.category] = int(categories.get(definition.category, 0)) + 1
        activities = progress.setdefault("by_activity", {})
        activities[definition.activity_id] = int(activities.get(definition.activity_id, 0)) + 1
        effects = {
            "category": definition.category,
            "needs": needs,
            "emotions": emotions,
            "knowledge": knowledge,
            "wealth": {
                "before": wealth_before,
                "after": wealth_after,
                "delta": wealth_after - wealth_before,
            },
            "budget": budget_payload,
        }
        if activity_settled is not None:
            club_effects = activity_settled(context, command, definition)
            if club_effects:
                effects["club"] = club_effects
        actor["last_activity_effects"] = effects
        context.emit(
            "CAMPUS_ACTIVITY_EFFECT_APPLIED",
            f"{actor.get('display_name', command.actor_id)} 完成 {definition.activity_id}。",
            actor_ids=[command.actor_id],
            scene_id=current_location,
            payload={"activity_id": definition.activity_id, "effects": effects},
            visibility="private",
            knowledge_tags=["campus_activity", definition.category],
        )
        return TransactionOutcome(
            True,
            True,
            "success",
            "校园活动完成。",
            commit=True,
            payload={"activity_id": definition.activity_id, "location_id": current_location, "effects": effects},
        )

    return perform


def campus_activity_effect_invariant(state: WorldState) -> Iterable[str]:
    errors: list[str] = []
    for actor_id, actor in state.population.items():
        if not isinstance(actor, dict):
            continue
        for field_name, keys in (("needs", NEED_NAMES), ("emotions", EMOTION_NAMES)):
            meters = actor.get(field_name, {})
            if not isinstance(meters, dict):
                errors.append(f"actor {actor_id} {field_name} must be a mapping")
                continue
            for key in keys:
                value = meters.get(key, 0)
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                    errors.append(f"actor {actor_id} {field_name}.{key} must be between 0 and 100")
        progress = actor.get("activity_progress")
        if progress is not None:
            if not isinstance(progress, dict) or int(progress.get("total", -1)) < 0:
                errors.append(f"actor {actor_id} activity_progress is invalid")
    actors = state.knowledge.get("actors", {})
    if not isinstance(actors, dict):
        errors.append("knowledge.actors must be a mapping")
    else:
        for actor_id, record in actors.items():
            if actor_id not in state.population or not isinstance(record, dict):
                errors.append(f"knowledge references invalid actor {actor_id}")
                continue
            topics = record.get("topics", {})
            if not isinstance(topics, dict) or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in topics.values()
            ):
                errors.append(f"actor {actor_id} knowledge topics are invalid")
            total = record.get("total_progress", 0)
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                errors.append(f"actor {actor_id} knowledge total is invalid")
    return errors


__all__ = [
    "PHASE_NEED_DRIFT",
    "advance_campus_phase_upkeep",
    "campus_activity_effect_invariant",
    "load_campus_activity_definitions",
    "make_campus_activity_handler",
]
