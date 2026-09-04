"""Autonomous, bounded NPC-to-NPC encounters after campus activities settle."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping

from simulation.domain.campus import RELATIONSHIP_NAMES
from simulation.domain.world_state import WorldState
from simulation.systems.campus_intelligence import (
    CampusIntelligencePolicy,
    create_campus_claim,
    disclosable_known_claims,
    share_known_claim,
)
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP, adjust_relationship
from simulation.systems.campus_tasks import phase_index


@dataclass(frozen=True)
class CampusInteractionPolicy:
    max_interactions_per_phase: int
    pair_cooldown_phases: int
    hook_lifetime_phases: int
    max_recent_interactions: int
    max_open_hooks: int
    minimum_pair_score: float
    intents: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        positive = (
            self.max_interactions_per_phase,
            self.pair_cooldown_phases,
            self.hook_lifetime_phases,
            self.max_recent_interactions,
            self.max_open_hooks,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in positive):
            raise ValueError("campus interaction limits must be positive integers")
        if self.minimum_pair_score < 0:
            raise ValueError("campus interaction minimum pair score cannot be negative")
        if not self.intents or "small_talk" not in self.intents:
            raise ValueError("campus interactions require a small_talk intent")


def load_campus_interaction_policy(registry) -> CampusInteractionPolicy:
    payload = registry.get("configuration", "campus_interactions")
    raw_intents = payload.get("intents", ())
    if not isinstance(raw_intents, list):
        raise ValueError("campus interaction intents must be a list")
    intents: Dict[str, Dict[str, Any]] = {}
    for raw in raw_intents:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
            raise ValueError("campus interaction intent requires an id")
        intent_id = raw["id"]
        if intent_id in intents:
            raise ValueError(f"duplicate campus interaction intent: {intent_id}")
        for outcome_key in ("relationship_on_accept", "relationship_on_reject"):
            outcome = raw.get(outcome_key, {})
            if not isinstance(outcome, dict) or any(
                not isinstance(deltas, dict)
                or any(name not in RELATIONSHIP_NAMES or not isinstance(value, int) for name, value in deltas.items())
                for deltas in outcome.values()
            ):
                raise ValueError(f"invalid relationship deltas for {intent_id}")
        intents[intent_id] = deepcopy(raw)
    return CampusInteractionPolicy(
        max_interactions_per_phase=int(payload.get("max_interactions_per_phase", 0)),
        pair_cooldown_phases=int(payload.get("pair_cooldown_phases", 0)),
        hook_lifetime_phases=int(payload.get("hook_lifetime_phases", 0)),
        max_recent_interactions=int(payload.get("max_recent_interactions", 0)),
        max_open_hooks=int(payload.get("max_open_hooks", 0)),
        minimum_pair_score=float(payload.get("minimum_pair_score", 0)),
        intents=intents,
    )


def install_campus_interactions(state: WorldState) -> None:
    if not state.cognition:
        raise ValueError("campus cognition must be installed before interactions")
    if "interactions" in state.cognition:
        raise ValueError("campus interactions are already installed")
    state.cognition["interactions"] = {
        "sequence": 0,
        "hook_sequence": 0,
        "recent": [],
        "hooks": [],
        "pair_last_phase": {},
    }


def _relation(state: WorldState, owner_id: str, target_id: str) -> Mapping[str, int]:
    value = state.relationships.get(owner_id, {}).get(target_id)
    return value if isinstance(value, dict) else DEFAULT_RELATIONSHIP


def _pair_key(first_id: str, second_id: str) -> str:
    return "|".join(sorted((first_id, second_id)))


def _shared_clubs(first: Mapping[str, Any], second: Mapping[str, Any]) -> list[str]:
    return sorted(set(first.get("club_ids", ())) & set(second.get("club_ids", ())))


def _activity_category(actor: Mapping[str, Any]) -> str:
    return str(actor.get("current_activity", {}).get("effects", {}).get("category", ""))


def _pair_score(state: WorldState, first_id: str, second_id: str, rng) -> float:
    first = state.population[first_id]
    second = state.population[second_id]
    relation = _relation(state, first_id, second_id)
    score = (
        0.18 * (int(first.get("needs", {}).get("social", 0)) + int(second.get("needs", {}).get("social", 0)))
        + 0.10 * (int(first.get("personality", {}).get("extraversion", 50)) + int(second.get("personality", {}).get("extraversion", 50)))
        + 0.08 * int(relation.get("familiarity", 0))
        + 0.06 * int(relation.get("trust", 50))
        - 0.10 * int(relation.get("conflict", 0))
    )
    if first.get("college_id") and first.get("college_id") == second.get("college_id"):
        score += 7
    if _shared_clubs(first, second):
        score += 13
    if first_id in state.cognition.get("focused_ids", ()) or second_id in state.cognition.get("focused_ids", ()):
        score += 12
    if _activity_category(first) in {"social", "club"}:
        score += 10
    if _activity_category(second) in {"social", "club"}:
        score += 10
    return round(score + rng.uniform(-6.0, 6.0), 3)


def _initiative(actor: Mapping[str, Any]) -> int:
    return (
        int(actor.get("needs", {}).get("social", 0))
        + int(actor.get("personality", {}).get("extraversion", 50))
        + int(actor.get("attributes", {}).get("expression", 5)) * 4
    )


def _open_hook(state: WorldState, first_id: str, second_id: str) -> Dict[str, Any] | None:
    interactions = state.cognition["interactions"]
    pair = {first_id, second_id}
    for hook in interactions.get("hooks", ()):
        if hook.get("state") == "open" and {hook.get("actor_id"), hook.get("target_id")} == pair:
            return hook
    return None


def _has_active_pair_hook(state: WorldState, first_id: str, second_id: str) -> bool:
    pair = {first_id, second_id}
    return any(
        hook.get("state") in {"open", "task_posted"}
        and {hook.get("actor_id"), hook.get("target_id")} == pair
        for hook in state.cognition["interactions"].get("hooks", ())
    )


def _legal_intents(
    state: WorldState,
    actor_id: str,
    target_id: str,
    policy: CampusInteractionPolicy,
) -> list[Dict[str, Any]]:
    actor = state.population[actor_id]
    target = state.population[target_id]
    relation = _relation(state, actor_id, target_id)
    categories = {_activity_category(actor), _activity_category(target)}
    shared_clubs = _shared_clubs(actor, target)
    target_distress = max(
        int(target.get("emotions", {}).get("sadness", 0)),
        int(target.get("emotions", {}).get("fear", 0)),
    )
    actor_anger = int(actor.get("emotions", {}).get("anger", 0))
    open_hook = _open_hook(state, actor_id, target_id)
    candidates: list[Dict[str, Any]] = []
    for intent_id, definition in policy.intents.items():
        required_categories = set(definition.get("requires_any_category", ()))
        if required_categories and not required_categories & categories:
            continue
        if definition.get("requires_shared_club") and not shared_clubs:
            continue
        if definition.get("requires_active_task") and not actor.get("active_forum_task_id"):
            continue
        if definition.get("requires_open_hook") and open_hook is None:
            continue
        distress_threshold = int(definition.get("requires_target_emotion", 0))
        if distress_threshold and target_distress < distress_threshold:
            continue
        conflict_threshold = int(definition.get("requires_conflict_or_anger", 0))
        if conflict_threshold and max(actor_anger, int(relation.get("conflict", 0))) < conflict_threshold:
            continue
        personality = actor.get("personality", {})
        needs = actor.get("needs", {})
        score = float(definition.get("base_score", 0))
        if intent_id == "small_talk":
            score += 0.25 * int(needs.get("social", 0)) + 0.12 * int(personality.get("extraversion", 50))
        elif intent_id == "exchange_ideas":
            score += 0.16 * int(needs.get("curiosity", 0)) + 0.12 * int(personality.get("openness", 50))
        elif intent_id == "offer_support":
            score += 0.16 * int(personality.get("altruism", 50)) + 0.9 * target_distress
        elif intent_id == "coordinate_club":
            score += 0.14 * int(personality.get("conscientiousness", 50)) + 4 * len(shared_clubs)
        elif intent_id == "ask_task_help":
            score += 0.20 * int(needs.get("commitment_pressure", 0)) + 0.12 * int(relation.get("trust", 50))
        elif intent_id == "follow_up_promise":
            score += 0.20 * int(relation.get("obligation", 0)) + 0.10 * int(relation.get("trust", 50))
        elif intent_id == "confront":
            score += 0.8 * actor_anger + 0.8 * int(relation.get("conflict", 0))
            score -= 0.12 * int(personality.get("agreeableness", 50))
        recent_repeats = sum(
            1
            for record in state.cognition["interactions"].get("recent", ())[-24:]
            if record.get("actor_id") == actor_id and record.get("intent_id") == intent_id
        )
        score -= min(24, recent_repeats * 8)
        candidates.append({
            "candidate_id": intent_id,
            "intent_id": intent_id,
            "activity_id": "NPC_SOCIAL_INTERACTION",
            "location_id": actor.get("current_location_id"),
            "reason": definition.get("name", intent_id),
            "reason_codes": [intent_id, "co_located"],
            "rule_score": round(score, 3),
            "open_hook_id": open_hook.get("hook_id") if open_hook else None,
        })
    return sorted(candidates, key=lambda item: (-float(item["rule_score"]), item["intent_id"]))


def _clamp_meter(value: int) -> int:
    return max(0, min(100, value))


def _apply_emotions(actor: Dict[str, Any], deltas: Mapping[str, Any]) -> Dict[str, int]:
    emotions = actor.setdefault("emotions", {})
    applied: Dict[str, int] = {}
    for name, raw_delta in deltas.items():
        if name not in {"joy", "fear", "anger", "sadness", "shame"} or not isinstance(raw_delta, int):
            raise ValueError(f"invalid interaction emotion delta: {name}")
        before = int(emotions.get(name, 0))
        after = _clamp_meter(before + raw_delta)
        emotions[name] = after
        applied[name] = after - before
    return applied


def _acceptance_score(
    state: WorldState,
    actor_id: str,
    target_id: str,
    intent_id: str,
    rng,
) -> float:
    actor = state.population[actor_id]
    target = state.population[target_id]
    relation = _relation(state, target_id, actor_id)
    personality = target.get("personality", {})
    score = (
        0.28 * int(personality.get("agreeableness", 50))
        + 0.18 * int(relation.get("trust", 50))
        + 0.10 * int(relation.get("familiarity", 0))
        + 0.08 * int(target.get("needs", {}).get("social", 0))
        - 0.16 * int(relation.get("suspicion", 0))
        - 0.14 * int(relation.get("conflict", 0))
    )
    if _shared_clubs(actor, target):
        score += 8
    if actor.get("college_id") and actor.get("college_id") == target.get("college_id"):
        score += 5
    if intent_id == "offer_support":
        score += 0.10 * int(target.get("attributes", {}).get("empathy", 5))
    if intent_id == "confront":
        score += 0.20 * int(personality.get("risk_tolerance", 50))
    return round(score + rng.uniform(-8.0, 8.0), 3)


def _expire_hooks(state: WorldState, now: int, policy: CampusInteractionPolicy) -> int:
    expired = 0
    hooks = state.cognition["interactions"].get("hooks", [])
    for hook in hooks:
        if hook.get("state") == "open" and now > int(hook.get("expires_phase_index", now)):
            hook["state"] = "expired"
            expired += 1
    active_hooks = [
        hook for hook in hooks if hook.get("state") in {"open", "task_posted"}
    ]
    terminal_hooks = [
        hook for hook in hooks if hook.get("state") not in {"open", "task_posted"}
    ]
    hooks[:] = [*terminal_hooks[-policy.max_recent_interactions:], *active_hooks]
    return expired


def _create_hook(
    state: WorldState,
    actor_id: str,
    target_id: str,
    hook_type: str,
    policy: CampusInteractionPolicy,
    now: int,
) -> str | None:
    interactions = state.cognition["interactions"]
    open_hooks = [hook for hook in interactions["hooks"] if hook.get("state") == "open"]
    if len(open_hooks) >= policy.max_open_hooks or _has_active_pair_hook(state, actor_id, target_id):
        return None
    interactions["hook_sequence"] += 1
    hook_id = f"social_hook:{interactions['hook_sequence']:06d}"
    interactions["hooks"].append({
        "hook_id": hook_id,
        "hook_type": hook_type,
        "actor_id": actor_id,
        "target_id": target_id,
        "created_day": state.clock.day,
        "created_phase": state.clock.phase,
        "expires_phase_index": now + policy.hook_lifetime_phases,
        "state": "open",
    })
    return hook_id


def _create_outcome_claims(
    state: WorldState,
    *,
    actor_id: str,
    target_id: str,
    interaction_id: str,
    intent_id: str,
    outcome: str,
    summary: str,
    hook_id: str | None,
    hook_transition: str | None,
) -> list[str]:
    """Persist only socially consequential, rule-verified interaction outcomes."""
    predicate = ""
    object_id = hook_id or target_id
    secrecy = 40
    if hook_transition == "created":
        predicate = "social_commitment_opened"
    elif hook_transition == "completed":
        predicate = "social_commitment_completed"
    elif hook_transition == "broken":
        predicate = "social_commitment_broken"
    elif intent_id == "confront":
        predicate = (
            "social_confrontation_addressed"
            if outcome == "accepted"
            else "social_confrontation_escalated"
        )
        object_id = interaction_id
        secrecy = 55
    if not predicate:
        return []
    claim = create_campus_claim(
        state,
        subject_id=actor_id,
        predicate=predicate,
        object_id=str(object_id),
        summary=summary,
        secrecy=secrecy,
        known_by=[actor_id, target_id],
        evidence_kind="interaction_outcome",
    )
    return [str(claim["claim_id"])]


def _resolve_interaction(
    context,
    actor_id: str,
    target_id: str,
    candidate: Mapping[str, Any],
    policy: CampusInteractionPolicy,
    source: str,
    model_reason: str,
    now: int,
    intelligence_policy: CampusIntelligencePolicy,
    cognition_runtime=None,
) -> Dict[str, Any]:
    state = context.state
    actor = state.population[actor_id]
    target = state.population[target_id]
    intent_id = str(candidate["intent_id"])
    definition = policy.intents[intent_id]
    acceptance = _acceptance_score(state, actor_id, target_id, intent_id, context.rng.stream("campus_interaction_outcome"))
    accepted = acceptance >= float(definition.get("acceptance_threshold", 0))
    outcome_key = "accept" if accepted else "reject"
    relationship = definition.get(f"relationship_on_{outcome_key}", {})
    actor_relation = adjust_relationship(state, actor_id, target_id, relationship.get("initiator", {}))
    target_relation = adjust_relationship(state, target_id, actor_id, relationship.get("target", {}))
    emotions = definition.get("emotion_on_accept", {}) if accepted else definition.get("emotion_on_reject", {})
    actor_emotions = _apply_emotions(actor, emotions.get("initiator", {}))
    target_emotions = _apply_emotions(target, emotions.get("target", {}))
    social_relief = int(definition.get("social_relief", 0)) if accepted else 0
    actor["needs"]["social"] = _clamp_meter(int(actor["needs"].get("social", 0)) - social_relief)
    target["needs"]["social"] = _clamp_meter(int(target["needs"].get("social", 0)) - social_relief // 2)
    curiosity_relief = int(definition.get("curiosity_relief", 0)) if accepted else 0
    actor["needs"]["curiosity"] = _clamp_meter(int(actor["needs"].get("curiosity", 0)) - curiosity_relief)

    hook_id = candidate.get("open_hook_id")
    hook_transition = None
    if definition.get("resolves_hook") and isinstance(hook_id, str):
        for hook in state.cognition["interactions"]["hooks"]:
            if hook.get("hook_id") == hook_id and hook.get("state") == "open":
                hook["state"] = "completed" if accepted else "broken"
                hook_transition = "completed" if accepted else "broken"
                hook["resolved_day"] = state.clock.day
                hook["resolved_phase"] = state.clock.phase
                break
    elif accepted and definition.get("creates_hook"):
        hook_id = _create_hook(
            state, actor_id, target_id, str(definition["creates_hook"]), policy, now
        )
        if hook_id:
            hook_transition = "created"

    interaction_state = state.cognition["interactions"]
    interaction_state["sequence"] += 1
    interaction_id = f"interaction:{interaction_state['sequence']:08d}"
    outcome = "accepted" if accepted else "rejected"
    summary_template = str(definition[f"summary_{outcome_key}"])
    summary = summary_template.format(
        actor=actor.get("display_name", actor_id),
        target=target.get("display_name", target_id),
    )
    outcome_claim_ids = _create_outcome_claims(
        state,
        actor_id=actor_id,
        target_id=target_id,
        interaction_id=interaction_id,
        intent_id=intent_id,
        outcome=outcome,
        summary=summary,
        hook_id=str(hook_id) if isinstance(hook_id, str) else None,
        hook_transition=hook_transition,
    )
    information_share = None
    if accepted:
        information_share = share_known_claim(
            state,
            sender_id=actor_id,
            receiver_id=target_id,
            interaction_id=interaction_id,
            intent_id=intent_id,
            policy=intelligence_policy,
            rng=context.rng.stream("campus_information_exchange"),
        )
    dialogue_summary = information_share.get("dialogue_summary", summary) if information_share else summary
    wording_source = "rule"
    wording_fact_ids: list[str] = []
    if cognition_runtime is not None:
        relevant_fact_ids = set(outcome_claim_ids)
        if information_share is not None:
            relevant_fact_ids.add(str(information_share["claim_id"]))
        allowed_facts = [
            item for item in disclosable_known_claims(
                state, actor_id, target_id, intelligence_policy
            )
            if item["claim"]["claim_id"] in relevant_fact_ids
        ]
        dialogue = cognition_runtime.compose_interaction_dialogue(
            state,
            actor_id,
            target_id,
            {
                "location_id": actor.get("current_location_id"),
                "intent_id": intent_id,
                "intent_name": definition.get("name", intent_id),
                "outcome": outcome,
                "verified_summary": summary,
                "hook_transition": hook_transition,
            },
            interaction_state.get("recent", ()),
            allowed_facts,
        )
        if dialogue is not None:
            actor_name = actor.get("display_name", actor_id)
            target_name = target.get("display_name", target_id)
            dialogue_summary = f"{actor_name}对{target_name}说：‘{dialogue['utterance']}’"
            wording_source = "llm"
            wording_fact_ids = list(dialogue.get("fact_ids_used", ()))
    record = {
        "interaction_id": interaction_id,
        "day": state.clock.day,
        "phase": state.clock.phase,
        "scene_id": actor.get("current_location_id"),
        "actor_id": actor_id,
        "target_id": target_id,
        "intent_id": intent_id,
        "outcome": outcome,
        "decision_source": source,
        "acceptance_score": acceptance,
        "relationship_deltas": {"actor": actor_relation, "target": target_relation},
        "emotion_deltas": {"actor": actor_emotions, "target": target_emotions},
        "hook_id": hook_id,
        "hook_transition": hook_transition,
        "shared_claim_id": information_share.get("claim_id") if information_share else None,
        "outcome_claim_ids": outcome_claim_ids,
        "dialogue_summary": dialogue_summary,
        "wording_source": wording_source,
        "wording_fact_ids": wording_fact_ids,
        "model_reason": model_reason[:300],
    }
    interaction_state["recent"].append(record)
    del interaction_state["recent"][:-policy.max_recent_interactions]
    interaction_state["pair_last_phase"][_pair_key(actor_id, target_id)] = now
    context.emit(
        "NPC_INTERACTION_RESOLVED",
        dialogue_summary,
        actor_ids=[actor_id],
        target_ids=[target_id],
        scene_id=str(actor.get("current_location_id", "")) or None,
        payload=deepcopy(record),
        visibility="private",
        severity=3 if hook_id or intent_id == "confront" else 2,
        knowledge_tags=["social", "relationship", "interaction", intent_id],
    )
    if information_share is not None:
        context.emit(
            "NPC_INFORMATION_SHARED",
            str(information_share["dialogue_summary"]),
            actor_ids=[actor_id],
            target_ids=[target_id],
            scene_id=str(actor.get("current_location_id", "")) or None,
            payload=deepcopy(information_share),
            visibility="private",
            severity=3,
            knowledge_tags=["social", "dialogue", "information", intent_id],
            correlation_id=interaction_id,
        )
    return record


def advance_campus_interactions(
    context,
    policy: CampusInteractionPolicy,
    intelligence_policy: CampusIntelligencePolicy,
    cognition_runtime=None,
) -> Dict[str, int]:
    """Resolve free social encounters after every NPC reaches its destination."""
    state = context.state
    interaction_state = state.cognition.get("interactions")
    if not isinstance(interaction_state, dict):
        raise ValueError("campus interactions are not installed")
    now = phase_index(state.clock.day, state.clock.phase)
    summary = {
        "interaction_count": 0,
        "interaction_accepted_count": 0,
        "interaction_rejected_count": 0,
        "interaction_llm_count": 0,
        "interaction_rule_count": 0,
        "interaction_hook_created_count": 0,
        "interaction_hook_resolved_count": 0,
        "interaction_hook_expired_count": _expire_hooks(state, now, policy),
        "interaction_information_shared_count": 0,
        "interaction_outcome_claim_count": 0,
        "interaction_llm_wording_count": 0,
        "interaction_rule_wording_count": 0,
    }
    groups: Dict[str, list[str]] = {}
    for actor_id, actor in sorted(state.population.items()):
        if actor_id == "player" or not isinstance(actor, dict):
            continue
        if actor.get("current_activity", {}).get("status") != "completed":
            continue
        location_id = str(actor.get("current_location_id", ""))
        if location_id:
            groups.setdefault(location_id, []).append(actor_id)
    rng = context.rng.stream("campus_interaction_pairs")
    pairs: list[tuple[float, str, str]] = []
    for actor_ids in groups.values():
        for index, first_id in enumerate(actor_ids):
            for second_id in actor_ids[index + 1:]:
                last_phase = interaction_state["pair_last_phase"].get(_pair_key(first_id, second_id))
                if isinstance(last_phase, int) and now - last_phase <= policy.pair_cooldown_phases:
                    continue
                score = _pair_score(state, first_id, second_id, rng)
                if score >= policy.minimum_pair_score:
                    pairs.append((score, first_id, second_id))
    used: set[str] = set()
    interaction_llm_attempted = False
    for _, first_id, second_id in sorted(pairs, key=lambda item: (-item[0], item[1], item[2])):
        if len(used) >= policy.max_interactions_per_phase * 2:
            break
        if first_id in used or second_id in used:
            continue
        first = state.population[first_id]
        second = state.population[second_id]
        if (_initiative(first), first_id) >= (_initiative(second), second_id):
            actor_id, target_id = first_id, second_id
        else:
            actor_id, target_id = second_id, first_id
        candidates = _legal_intents(state, actor_id, target_id, policy)
        if not candidates:
            continue
        chosen = candidates[0]
        source = "rule"
        model_reason = ""
        if (
            not interaction_llm_attempted
            and cognition_runtime is not None
            and actor_id in state.cognition.get("focused_ids", ())
        ):
            interaction_llm_attempted = True
            llm_choice = cognition_runtime.select_interaction(
                state, actor_id, target_id, candidates
            )
            if llm_choice is not None:
                chosen = llm_choice
                source = "llm"
                model_reason = str(llm_choice.get("model_reason", ""))
        open_before = _open_hook(state, actor_id, target_id)
        record = _resolve_interaction(
            context, actor_id, target_id, chosen, policy, source, model_reason, now,
            intelligence_policy, cognition_runtime,
        )
        used.update((actor_id, target_id))
        summary["interaction_count"] += 1
        summary[f"interaction_{record['outcome']}_count"] += 1
        summary[f"interaction_{source}_count"] += 1
        if open_before and record.get("intent_id") == "follow_up_promise":
            summary["interaction_hook_resolved_count"] += 1
        elif record.get("hook_id"):
            summary["interaction_hook_created_count"] += 1
        if record.get("shared_claim_id"):
            summary["interaction_information_shared_count"] += 1
        summary["interaction_outcome_claim_count"] += len(record.get("outcome_claim_ids", ()))
        summary[f"interaction_{record['wording_source']}_wording_count"] += 1
    return summary


def campus_interaction_invariant(state: WorldState) -> Iterable[str]:
    interaction_state = state.cognition.get("interactions")
    if interaction_state is None:
        return ()
    errors: list[str] = []
    if not isinstance(interaction_state, dict):
        return ("campus cognition interactions must be a mapping",)
    recent = interaction_state.get("recent", [])
    hooks = interaction_state.get("hooks", [])
    if not isinstance(recent, list) or not isinstance(hooks, list):
        return ("campus interaction records and hooks must be lists",)
    for record in recent:
        if not isinstance(record, dict) or record.get("actor_id") not in state.population or record.get("target_id") not in state.population:
            errors.append("campus interaction references unknown actors")
        elif record.get("actor_id") == record.get("target_id"):
            errors.append("campus interaction cannot target self")
        elif record.get("outcome") not in {"accepted", "rejected"}:
            errors.append("campus interaction has invalid outcome")
        elif record.get("decision_source") not in {"rule", "llm"}:
            errors.append("campus interaction has invalid decision source")
        elif record.get("wording_source") not in {"rule", "llm"}:
            errors.append("campus interaction has invalid wording source")
        elif not isinstance(record.get("outcome_claim_ids"), list) or any(
            claim_id not in state.knowledge.get("claims", {})
            for claim_id in record.get("outcome_claim_ids", ())
        ):
            errors.append("campus interaction references an invalid outcome claim")
        elif not isinstance(record.get("wording_fact_ids"), list) or any(
            claim_id not in state.knowledge.get("claims", {})
            for claim_id in record.get("wording_fact_ids", ())
        ):
            errors.append("campus interaction wording references an invalid claim")
    hook_ids: set[str] = set()
    for hook in hooks:
        hook_id = hook.get("hook_id") if isinstance(hook, dict) else None
        if not isinstance(hook_id, str) or not hook_id or hook_id in hook_ids:
            errors.append("campus interaction hook id is invalid or duplicated")
            continue
        hook_ids.add(hook_id)
        if hook.get("actor_id") not in state.population or hook.get("target_id") not in state.population:
            errors.append(f"campus interaction hook {hook_id} references unknown actors")
        if hook.get("state") not in {"open", "task_posted", "completed", "broken", "expired"}:
            errors.append(f"campus interaction hook {hook_id} has invalid state")
        if hook.get("state") == "task_posted" and hook.get("linked_task_id") not in state.tasks:
            errors.append(f"campus interaction hook {hook_id} references unknown linked task")
    return errors


__all__ = [
    "CampusInteractionPolicy", "advance_campus_interactions",
    "campus_interaction_invariant", "install_campus_interactions",
    "load_campus_interaction_policy",
]
