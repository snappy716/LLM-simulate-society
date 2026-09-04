"""Explainable rule decisions for ordinary campus NPC phase activities."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from simulation.domain.activities import CampusActivityDefinition
from simulation.domain.campus import PersonalityTraits
from simulation.domain.entities import PHASES
from simulation.domain.locations import CampusLocationGraph, CampusRoute
from simulation.domain.world_state import WorldState
from simulation.systems.content_registry import ContentRegistry
from simulation.systems.decision_scoring import DecisionFactors, score_action


DECISION_LOCATION_TOKENS = {"home", "primary", "library"}
ROLE_KINDS = {"student", "staff"}


@dataclass(frozen=True)
class CampusDecisionAlternative:
    alternative_id: str
    activity_id: str
    location: str
    allowed_phases: Tuple[str, ...]
    reason: str
    priority: int
    role_kinds: Tuple[str, ...] = ()
    required_club: bool = False

    def __post_init__(self) -> None:
        valid_phases = {phase.value for phase in PHASES}
        if not self.alternative_id or not self.activity_id or not self.location or not self.reason:
            raise ValueError("campus decision alternatives require id, activity, location, and reason")
        if not self.allowed_phases or not set(self.allowed_phases).issubset(valid_phases):
            raise ValueError(f"invalid decision phases for {self.alternative_id}")
        if len(set(self.allowed_phases)) != len(self.allowed_phases):
            raise ValueError(f"duplicate decision phase for {self.alternative_id}")
        if not set(self.role_kinds).issubset(ROLE_KINDS):
            raise ValueError(f"invalid role kind for {self.alternative_id}")
        if isinstance(self.priority, bool) or not 0 <= self.priority <= 100:
            raise ValueError(f"invalid priority for {self.alternative_id}")


@dataclass(frozen=True)
class CampusDecisionPolicy:
    score_jitter: float
    route_minutes_for_max_cost: int
    protected_schedule_priority: int
    emergency_need_threshold: int
    alternatives: Tuple[CampusDecisionAlternative, ...]

    def __post_init__(self) -> None:
        if not 0 <= self.score_jitter <= 20:
            raise ValueError("campus decision score jitter must be between 0 and 20")
        if self.route_minutes_for_max_cost <= 0:
            raise ValueError("route_minutes_for_max_cost must be positive")
        for name, value in (
            ("protected_schedule_priority", self.protected_schedule_priority),
            ("emergency_need_threshold", self.emergency_need_threshold),
        ):
            if isinstance(value, bool) or not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        ids = [item.alternative_id for item in self.alternatives]
        if len(ids) != len(set(ids)):
            raise ValueError("campus decision alternative ids must be unique")


@dataclass(frozen=True)
class _DecisionCandidate:
    candidate_id: str
    activity_id: str
    action_class: str
    category: str
    location_id: str
    source: str
    reason: str
    priority: int
    route: CampusRoute
    definition: CampusActivityDefinition


def load_campus_decision_policy(
    registry: ContentRegistry,
    definitions: Mapping[str, CampusActivityDefinition],
    graph: CampusLocationGraph,
) -> CampusDecisionPolicy:
    payload = registry.get("configuration", "campus_decisions")
    raw_alternatives = payload.get("alternatives")
    if not isinstance(raw_alternatives, list) or not raw_alternatives:
        raise ValueError("campus decision policy requires alternatives")
    alternatives = tuple(
        CampusDecisionAlternative(
            alternative_id=str(item.get("id", "")),
            activity_id=str(item.get("activity_id", "")),
            location=str(item.get("location", "")),
            allowed_phases=tuple(str(value) for value in item.get("allowed_phases", ())),
            reason=str(item.get("reason", "")),
            priority=int(item.get("priority", -1)),
            role_kinds=tuple(str(value) for value in item.get("role_kinds", ())),
            required_club=bool(item.get("required_club", False)),
        )
        for item in raw_alternatives
        if isinstance(item, dict)
    )
    if len(alternatives) != len(raw_alternatives):
        raise ValueError("campus decision alternatives must be mappings")
    policy = CampusDecisionPolicy(
        score_jitter=float(payload.get("score_jitter", 0)),
        route_minutes_for_max_cost=int(payload.get("route_minutes_for_max_cost", 90)),
        protected_schedule_priority=int(payload.get("protected_schedule_priority", 90)),
        emergency_need_threshold=int(payload.get("emergency_need_threshold", 90)),
        alternatives=alternatives,
    )
    errors: list[str] = []
    for alternative in policy.alternatives:
        definition = definitions.get(alternative.activity_id)
        if definition is None:
            errors.append(f"{alternative.alternative_id} references unknown activity")
            continue
        if not set(alternative.allowed_phases).issubset(set(definition.allowed_phases)):
            errors.append(f"{alternative.alternative_id} uses activity in a forbidden phase")
        if (
            alternative.location not in DECISION_LOCATION_TOKENS
            and alternative.location not in graph.node_ids
        ):
            errors.append(f"{alternative.alternative_id} references unknown location")
    if errors:
        raise ValueError("invalid campus decision policy: " + "; ".join(errors))
    return policy


def _resolve_location(actor: Mapping[str, Any], token: str) -> str:
    if token == "home":
        return str(actor.get("home_location_id", ""))
    if token == "primary":
        return str(actor.get("primary_location_id") or actor.get("home_location_id", ""))
    if token == "library":
        return "library_reading_hall"
    return token


def _destination_is_open_and_accessible(
    graph: CampusLocationGraph,
    actor: Mapping[str, Any],
    location_id: str,
    phase: str,
) -> bool:
    if location_id not in graph.node_ids or not graph.is_open(location_id, phase):
        return False
    location = graph.locations.get(location_id)
    if location is None:
        return True
    return set(location.access_tags).issubset(set(actor.get("access_tags", ())))


def _lineage(graph: CampusLocationGraph, location_id: str) -> Tuple[str, ...]:
    result: list[str] = []
    cursor = location_id
    seen: set[str] = set()
    while cursor in graph.locations and cursor not in seen:
        seen.add(cursor)
        result.append(cursor)
        cursor = graph.locations[cursor].parent_id
    return tuple(result)


def _has_capacity(
    graph: CampusLocationGraph,
    occupancy: Counter[str],
    location_id: str,
) -> bool:
    return all(
        occupancy[node_id] < graph.locations[node_id].capacity
        for node_id in _lineage(graph, location_id)
    )


def reserve_decision_destination(
    graph: CampusLocationGraph,
    occupancy: Counter[str],
    location_id: str,
) -> None:
    for node_id in _lineage(graph, location_id):
        occupancy[node_id] += 1


def _relationship_pull(state: WorldState, actor_id: str) -> float:
    owner = state.relationships.get(actor_id, {})
    if not isinstance(owner, dict):
        return 0.0
    edges = owner.get("edges", owner)
    if not isinstance(edges, dict):
        return 0.0
    pulls: list[float] = []
    for relation in edges.values():
        if not isinstance(relation, dict):
            continue
        pulls.append(
            0.45 * float(relation.get("closeness", 0))
            + 0.35 * float(relation.get("trust", 0))
            + 0.20 * float(relation.get("obligation", 0))
        )
    return max(pulls, default=0.0)


def _value_alignment(actor: Mapping[str, Any], category: str, source: str) -> float:
    category_values = {
        "study": {"achievement", "curiosity", "recognition", "truth"},
        "research": {"achievement", "curiosity", "truth"},
        "social": {"belonging", "care", "recognition"},
        "club": {"belonging", "achievement", "recognition"},
        "exploration": {"curiosity", "freedom", "truth"},
        "personal": {"freedom", "security"},
        "work": {"achievement", "order", "care", "security"},
        "rest": {"security", "freedom"},
    }
    values = [str(value) for value in actor.get("core_values", ())]
    matches = sum(value in category_values.get(category, set()) for value in values)
    result = min(100.0, matches * 30.0)
    if source == "schedule" and "order" in values:
        result = min(100.0, result + 30.0)
    return result


def _need_satisfaction(
    actor: Mapping[str, Any],
    definition: CampusActivityDefinition,
) -> float:
    needs = actor.get("needs", {})
    relief = {
        name: max(0, -int(delta))
        for name, delta in definition.need_deltas.items()
    }
    total_relief = sum(relief.values())
    if total_relief <= 0 or not isinstance(needs, dict):
        return 0.0
    return min(
        100.0,
        sum(float(needs.get(name, 0)) * amount for name, amount in relief.items())
        / total_relief,
    )


def _goal_progress(actor: Mapping[str, Any], category: str, priority: int) -> float:
    needs = actor.get("needs", {})
    if not isinstance(needs, dict):
        needs = {}
    achievement = float(needs.get("achievement", 0))
    curiosity = float(needs.get("curiosity", 0))
    if category in {"study", "research"}:
        return min(100.0, 0.65 * achievement + 0.35 * curiosity)
    if category == "work":
        return min(100.0, 0.7 * float(needs.get("money", 0)) + 0.3 * achievement)
    if category in {"social", "club"}:
        return float(needs.get("social", 0))
    if category == "exploration":
        return curiosity
    if category == "rest":
        return float(needs.get("rest", 0))
    if category == "personal":
        emotions = actor.get("emotions", {})
        distress = max(
            (float(emotions.get(name, 0)) for name in ("fear", "anger", "sadness", "shame")),
            default=0.0,
        ) if isinstance(emotions, dict) else 0.0
        return min(100.0, 0.6 * float(needs.get("rest", 0)) + 0.4 * distress)
    return float(priority)


def _decision_factors(
    state: WorldState,
    actor_id: str,
    actor: Mapping[str, Any],
    candidate: _DecisionCandidate,
    scheduled_priority: int,
    route_minutes_for_max_cost: int,
) -> DecisionFactors:
    needs = actor.get("needs", {})
    emotions = actor.get("emotions", {})
    personality = actor.get("personality", {})
    previous = actor.get("current_activity", {})
    same_as_previous = (
        isinstance(previous, dict)
        and previous.get("activity_id") == candidate.activity_id
    )
    relationship = _relationship_pull(state, actor_id)
    if candidate.category in {"social", "club"}:
        relationship = max(
            relationship,
            0.7 * float(needs.get("social", 0))
            + 0.3 * float(personality.get("extraversion", 50)),
        )
    commitment = float(candidate.priority if candidate.source == "schedule" else 0)
    if candidate.category == "club" and actor.get("club_ids"):
        commitment = max(commitment, 55.0)
    risk = (
        18.0
        if candidate.category == "exploration"
        else 5.0
        if candidate.category in {"social", "club"}
        else 0.0
    )
    money_cost = 0.0
    if candidate.category in {"personal", "social", "club"}:
        money_cost = 0.3 * float(needs.get("money", 0))
    route_cost = min(
        100.0,
        candidate.route.total_minutes * 100.0 / route_minutes_for_max_cost,
    )
    return DecisionFactors(
        goal_progress=_goal_progress(actor, candidate.category, candidate.priority),
        need_satisfaction=_need_satisfaction(actor, candidate.definition),
        value_alignment=_value_alignment(actor, candidate.category, candidate.source),
        relationship_pull=relationship,
        commitment_pull=commitment,
        habit_pull=100.0 if same_as_previous else 70.0 if candidate.source == "schedule" else 0.0,
        curiosity=(
            float(needs.get("curiosity", 0))
            if candidate.category in {"study", "research", "exploration"}
            else 0.0
        ),
        prosocial_value=(
            float(personality.get("altruism", 50))
            if candidate.category in {"social", "club", "work"}
            else 0.0
        ),
        risk=risk,
        money_cost=money_cost,
        time_cost=route_cost,
        opportunity_cost=(
            max(0.0, float(scheduled_priority - candidate.priority))
            if candidate.source != "schedule"
            else 0.0
        ),
        fear_pressure=float(emotions.get("fear", 0)) if risk else 0.0,
        anger_pressure=float(emotions.get("anger", 0)) if risk else 0.0,
    )


def _build_candidates(
    state: WorldState,
    actor_id: str,
    actor: Mapping[str, Any],
    schedule_plan: Mapping[str, Any],
    graph: CampusLocationGraph,
    definitions: Mapping[str, CampusActivityDefinition],
    policy: CampusDecisionPolicy,
    occupancy: Counter[str],
) -> Sequence[_DecisionCandidate]:
    phase = state.clock.phase
    raw: list[tuple[str, str, str, str, str, int]] = []
    schedule_activity = str(schedule_plan.get("activity_id", ""))
    if schedule_activity:
        raw.append((
            "scheduled_plan",
            schedule_activity,
            str(schedule_plan.get("location_id", "")),
            "schedule",
            "schedule_commitment",
            int(schedule_plan.get("priority", 0)),
        ))
    emergency_need = max(
        (
            int(actor.get("needs", {}).get(name, 0))
            for name in ("rest", "food", "safety")
        ),
        default=0,
    )
    protected = (
        int(schedule_plan.get("priority", 0)) >= policy.protected_schedule_priority
        and emergency_need < policy.emergency_need_threshold
    )
    for alternative in policy.alternatives:
        if protected:
            continue
        if phase not in alternative.allowed_phases:
            continue
        if alternative.role_kinds and actor.get("role_kind") not in alternative.role_kinds:
            continue
        if alternative.required_club and not actor.get("club_ids"):
            continue
        raw.append((
            alternative.alternative_id,
            alternative.activity_id,
            _resolve_location(actor, alternative.location),
            "rule",
            alternative.reason,
            alternative.priority,
        ))

    result: list[_DecisionCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate_id, activity_id, location_id, source, reason, priority in raw:
        definition = definitions.get(activity_id)
        key = (activity_id, location_id)
        if definition is None or key in seen or phase not in definition.allowed_phases:
            continue
        if not _destination_is_open_and_accessible(graph, actor, location_id, phase):
            continue
        route = graph.shortest_route(
            str(actor.get("current_location_id", "")),
            location_id,
            phase=phase,
            access_tags=actor.get("access_tags", ()),
        )
        if route is None or not _has_capacity(graph, occupancy, location_id):
            continue
        seen.add(key)
        result.append(_DecisionCandidate(
            candidate_id=candidate_id,
            activity_id=activity_id,
            action_class=definition.action_class,
            category=definition.category,
            location_id=location_id,
            source=source,
            reason=reason,
            priority=priority,
            route=route,
            definition=definition,
        ))
    return result


def rank_campus_npc_activities(
    context,
    actor_id: str,
    schedule_plan: Mapping[str, Any],
    graph: CampusLocationGraph,
    definitions: Mapping[str, CampusActivityDefinition],
    policy: CampusDecisionPolicy,
    occupancy: Counter[str],
) -> list[Dict[str, Any]]:
    actor = context.state.population.get(actor_id)
    if not isinstance(actor, dict):
        return []
    candidates = _build_candidates(
        context.state,
        actor_id,
        actor,
        schedule_plan,
        graph,
        definitions,
        policy,
        occupancy,
    )
    if not candidates:
        return []
    personality = PersonalityTraits(**{
        name: int(actor.get("personality", {}).get(name, 50))
        for name in PersonalityTraits.__dataclass_fields__
    })
    rng = context.rng.stream("npc_decision")
    scheduled_priority = int(schedule_plan.get("priority", 0))
    scored: list[tuple[float, str, _DecisionCandidate, Dict[str, float], float]] = []
    for candidate in candidates:
        score = score_action(
            personality,
            _decision_factors(
                context.state,
                actor_id,
                actor,
                candidate,
                scheduled_priority,
                policy.route_minutes_for_max_cost,
            ),
        )
        jitter = rng.uniform(-policy.score_jitter, policy.score_jitter)
        total = round(score.total + jitter, 3)
        scored.append((total, candidate.candidate_id, candidate, score.contributions, jitter))
    ranked: list[Dict[str, Any]] = []
    for total, _, chosen, contributions, jitter in sorted(
        scored, key=lambda item: (-item[0], item[1])
    ):
        ranked_reasons = [
            key
            for key, value in sorted(
                contributions.items(),
                key=lambda item: (-item[1], item[0]),
            )
            if value > 0
        ][:3]
        ranked.append({
            "candidate_id": chosen.candidate_id,
            "activity_id": chosen.activity_id,
            "action_class": chosen.action_class,
            "location_id": chosen.location_id,
            "priority": chosen.priority,
            "decision_source": chosen.source,
            "decision_reason": chosen.reason,
            "reason_codes": ranked_reasons,
            "scheduled_activity_id": str(schedule_plan.get("activity_id", "")),
            "scheduled_location_id": str(schedule_plan.get("location_id", "")),
            "candidate_count": len(candidates),
            "score": total,
            "score_jitter": round(jitter, 3),
            "score_contributions": {key: round(value, 3) for key, value in contributions.items()},
            "route_minutes": chosen.route.total_minutes,
            "day": context.state.clock.day,
            "phase": context.state.clock.phase,
        })
    return ranked


def choose_campus_npc_activity(
    context,
    actor_id: str,
    schedule_plan: Mapping[str, Any],
    graph: CampusLocationGraph,
    definitions: Mapping[str, CampusActivityDefinition],
    policy: CampusDecisionPolicy,
    occupancy: Counter[str],
) -> Optional[Dict[str, Any]]:
    ranked = rank_campus_npc_activities(
        context, actor_id, schedule_plan, graph, definitions, policy, occupancy
    )
    if not ranked:
        return None
    chosen = ranked[0]
    reserve_decision_destination(graph, occupancy, chosen["location_id"])
    return chosen


def make_campus_npc_decision_selector(
    graph: CampusLocationGraph,
    definitions: Mapping[str, CampusActivityDefinition],
    policy: CampusDecisionPolicy,
):
    def select(context, actor_id, schedule_plan, occupancy):
        return choose_campus_npc_activity(
            context,
            actor_id,
            schedule_plan,
            graph,
            definitions,
            policy,
            occupancy,
        )

    return select


def campus_decision_invariant(state: WorldState) -> Iterable[str]:
    errors: list[str] = []
    for actor_id, actor in state.population.items():
        if actor_id == "player" or not isinstance(actor, dict):
            continue
        decision = actor.get("current_decision")
        if decision is None:
            continue
        if not isinstance(decision, dict):
            errors.append(f"actor {actor_id} current_decision must be a mapping")
            continue
        if (
            decision.get("day") != state.clock.day
            or decision.get("phase") != state.clock.phase
        ):
            errors.append(f"actor {actor_id} current_decision clock mismatch")
        if decision.get("action_class") not in {"major", "free"}:
            errors.append(f"actor {actor_id} current_decision has invalid action class")
        if decision.get("location_id") not in state.places:
            errors.append(f"actor {actor_id} current_decision references unknown place")
        if decision.get("decision_source") not in {"schedule", "rule", "task", "llm"}:
            errors.append(f"actor {actor_id} current_decision has invalid source")
        candidate_count = decision.get("candidate_count")
        if (
            isinstance(candidate_count, bool)
            or not isinstance(candidate_count, int)
            or candidate_count < 1
        ):
            errors.append(f"actor {actor_id} current_decision candidate count is invalid")
    return errors


__all__ = [
    "CampusDecisionAlternative",
    "CampusDecisionPolicy",
    "campus_decision_invariant",
    "choose_campus_npc_activity",
    "load_campus_decision_policy",
    "make_campus_npc_decision_selector",
    "rank_campus_npc_activities",
    "reserve_decision_destination",
]
