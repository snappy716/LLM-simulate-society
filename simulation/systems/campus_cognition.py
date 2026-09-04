"""Bounded subjective cognition for the persistent campus population."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping, Sequence

from simulation.actions.commands import SimulationCommand
from simulation.cognition.focus_slots import FocusCandidate, FocusSlotAllocator
from simulation.cognition.provider import (
    CognitionProvider,
    OllamaCognitionProvider,
    OpenAICompatibleCognitionProvider,
    RuleOnlyProvider,
)
from simulation.domain.cognition import (
    BoundedDecisionRequest,
    BoundedDecisionResponse,
    BoundedDialogueRequest,
    BoundedDialogueResponse,
    CognitionPolicy,
)
from simulation.domain.events import SimulationEvent
from simulation.domain.world_state import WorldState
from simulation.systems.transactions import TransactionOutcome
from simulation.systems.campus_intelligence import known_claims


COGNITION_SCHEMA_VERSION = 1
_SKIPPED_MEMORY_EVENTS = {"WORLD_PHASE_ADVANCED"}


def load_cognition_policy(registry) -> CognitionPolicy:
    payload = registry.get("configuration", "cognition_policy")
    allowed = CognitionPolicy.__dataclass_fields__
    return CognitionPolicy(**{
        key: payload[key] for key in allowed if key in payload
    })


def install_campus_cognition(state: WorldState, policy: CognitionPolicy) -> None:
    if state.cognition:
        raise ValueError("campus cognition is already initialized")
    initial = sorted(
        actor_id for actor_id, actor in state.population.items()
        if actor_id != "player" and isinstance(actor, dict)
        and actor.get("simulation_tier") == "focused"
    )[:policy.total_focus_slots]
    state.cognition.update({
        "schema_version": COGNITION_SCHEMA_VERSION,
        "policy": policy.to_dict(),
        "focused_ids": initial,
        "awakened_ids": [],
        "observations": {},
        "observation_ids_by_actor": {actor_id: [] for actor_id in state.population if actor_id != "player"},
        "memory_by_actor": {actor_id: [] for actor_id in state.population if actor_id != "player"},
        "reflections": {},
        "usage": _fresh_usage(state.clock.day),
        "decision_cache": {},
        "decision_cache_order": [],
        "decision_audit": [],
        "provider": {"mode": "rule", "configured": False, "model": ""},
    })


def _fresh_usage(day: int) -> Dict[str, Any]:
    return {
        "day": day,
        "calls": 0,
        "estimated_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "phase_calls": {},
        "purpose_phase_calls": {},
        "cache_hits": 0,
        "fallbacks": 0,
        "rejected_responses": 0,
        "provider_errors": 0,
        "budget_blocks": 0,
    }


def _stable_fraction(*values: str) -> float:
    digest = hashlib.sha256(":".join(values).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


def _event_observers(state: WorldState, event: SimulationEvent) -> Sequence[str]:
    involved = {
        actor_id for actor_id in (*event.actor_ids, *event.target_ids)
        if actor_id in state.population and actor_id != "player"
    }
    if event.visibility in {"secret", "private"} or not event.scene_id or event.severity < 3:
        return sorted(involved)
    local = {
        actor_id for actor_id, actor in state.population.items()
        if actor_id != "player" and isinstance(actor, dict)
        and actor.get("current_location_id") == event.scene_id
    }
    return sorted(involved | local)


def project_cognition_events(state: WorldState, events: Iterable[SimulationEvent]) -> None:
    """Turn committed, perceivable events into actor-local observations and memories."""
    if not state.cognition:
        return
    policy = CognitionPolicy(**state.cognition["policy"])
    observations = state.cognition["observations"]
    observation_index = state.cognition["observation_ids_by_actor"]
    memories = state.cognition["memory_by_actor"]
    for event in events:
        if event.event_type in _SKIPPED_MEMORY_EVENTS:
            continue
        involved = set(event.actor_ids) | set(event.target_ids)
        for observer_id in _event_observers(state, event):
            actor = state.population[observer_id]
            insight = int(actor.get("attributes", {}).get("insight", 5))
            directly_involved = observer_id in involved
            base_accuracy = 0.92 if directly_involved else 0.58 + insight * 0.035
            uncertainty = _stable_fraction(event.event_id, observer_id) * 0.08
            accuracy = round(max(0.35, min(0.99, base_accuracy - uncertainty)), 3)
            salience = min(100, event.severity * 9 + (22 if directly_involved else 5))
            observation_id = f"obs:{event.event_id}:{observer_id}"
            interpretation = "亲历" if directly_involved else "现场目击"
            observation = {
                "observation_id": observation_id,
                "observer_id": observer_id,
                "source_event_id": event.event_id,
                "day": event.day,
                "phase": event.phase,
                "scene_id": event.scene_id,
                "summary": event.public_summary,
                "accuracy": accuracy,
                "salience": salience,
                "interpretation": interpretation,
                "knowledge_tags": list(event.knowledge_tags),
            }
            observations[observation_id] = observation
            actor_observations = observation_index.setdefault(observer_id, [])
            actor_observations.append(observation_id)
            while len(actor_observations) > policy.observation_limit_per_actor:
                observations.pop(actor_observations.pop(0), None)
            actor_memories = memories.setdefault(observer_id, [])
            actor_memories.append({
                "memory_id": f"mem:{event.event_id}:{observer_id}",
                "source_observation_id": observation_id,
                "day": event.day,
                "phase": event.phase,
                "scene_id": event.scene_id,
                "summary": event.public_summary,
                "confidence": accuracy,
                "salience": salience,
                "interpretation": interpretation,
                "knowledge_tags": list(event.knowledge_tags),
            })
            limit = (
                policy.memory_limit_per_actor
                if observer_id in state.cognition.get("focused_ids", ())
                else policy.persistent_memory_limit_per_actor
            )
            del actor_memories[:-limit]


def _relationship_relevance(state: WorldState, actor_id: str) -> float:
    relation = state.relationships.get(actor_id, {}).get("player", {})
    if not isinstance(relation, dict):
        return 0.0
    return (
        float(relation.get("familiarity", 0)) * 0.2
        + float(relation.get("trust", 0)) * 0.3
        + float(relation.get("closeness", 0)) * 0.4
        + float(relation.get("obligation", 0)) * 0.1
    )


def allocate_focus_slots(state: WorldState, policy: CognitionPolicy) -> list[str]:
    allocator = FocusSlotAllocator(policy.total_focus_slots, policy.player_awakened_slots)
    for actor_id in state.cognition.get("awakened_ids", ()):
        allocator.awaken(actor_id)
    player_party_members: set[str] = set()
    for party in state.parties.values():
        if isinstance(party, dict) and "player" in party.get("member_ids", ()):
            player_party_members.update(party.get("member_ids", ()))
    candidates: list[FocusCandidate] = []
    for actor_id, actor in state.population.items():
        if actor_id == "player" or not isinstance(actor, dict):
            continue
        active_task = bool(actor.get("active_forum_task_id"))
        emotions = actor.get("emotions", {})
        distress = max((int(emotions.get(key, 0)) for key in ("fear", "anger", "sadness", "shame")), default=0)
        candidates.append(FocusCandidate(
            npc_id=actor_id,
            player_awakened=actor_id in state.cognition.get("awakened_ids", ()),
            active_task_score=80 if active_task else 0,
            night_action_score={"willing": 45, "capable": 30, "sensitive": 15}.get(actor.get("night_access"), 0),
            world_relevance_score=(
                (100 if actor_id in player_party_members else 0)
                + _relationship_relevance(state, actor_id)
                + distress * 0.3
                + (25 if actor.get("simulation_tier") == "focused" else 0)
            ),
        ))
    selected = allocator.allocate(candidates)
    state.cognition["focused_ids"] = selected
    for actor_id, actor in state.population.items():
        if actor_id != "player" and isinstance(actor, dict):
            actor["simulation_tier"] = "focused" if actor_id in selected else "persistent"
            actor["awakened_by_player"] = actor_id in allocator.awakened_ids
    return selected


def _reflect_actor(state: WorldState, actor_id: str, policy: CognitionPolicy) -> None:
    recent = state.cognition["memory_by_actor"].get(actor_id, [])[-policy.reflection_memory_limit:]
    if not recent:
        state.cognition["reflections"].pop(actor_id, None)
        return
    important = sorted(recent, key=lambda item: (-int(item["salience"]), -int(item["day"])))[:3]
    tags = sorted({tag for item in important for tag in item.get("knowledge_tags", ())})
    state.cognition["reflections"][actor_id] = {
        "day": state.clock.day,
        "phase": state.clock.phase,
        "summary": "；".join(str(item["summary"]) for item in important)[:600],
        "concerns": tags[:6],
        "memory_ids": [item["memory_id"] for item in important],
        "source": "rule",
    }


def advance_cognition_phase(context, policy: CognitionPolicy) -> Dict[str, Any]:
    state = context.state
    usage = state.cognition.get("usage", {})
    if usage.get("day") != state.clock.day:
        state.cognition["usage"] = _fresh_usage(state.clock.day)
        for actor_memories in state.cognition.get("memory_by_actor", {}).values():
            if not isinstance(actor_memories, list):
                continue
            for memory in actor_memories:
                age = max(0, state.clock.day - int(memory.get("day", state.clock.day)))
                protection = min(0.02, int(memory.get("salience", 0)) / 5000)
                memory["confidence"] = round(max(0.1, float(memory.get("confidence", 0.5)) - age * (0.025 - protection)), 3)
    focused = allocate_focus_slots(state, policy)
    for actor_id in focused:
        _reflect_actor(state, actor_id, policy)
    return {
        "cognition_focused_count": len(focused),
        "cognition_awakened_count": len(state.cognition.get("awakened_ids", ())),
    }


def make_awaken_npc_handler(policy: CognitionPolicy):
    def awaken(context, command: SimulationCommand) -> TransactionOutcome:
        if command.actor_id != "player":
            return TransactionOutcome(False, False, "player_only", "只有玩家可以记名觉醒 NPC。")
        target_id = str(command.parameters.get("target_id", ""))
        target = context.state.population.get(target_id)
        if target_id == "player" or not isinstance(target, dict):
            return TransactionOutcome(False, False, "unknown_target", "目标 NPC 不存在。")
        awakened = context.state.cognition.setdefault("awakened_ids", [])
        if target_id in awakened:
            return TransactionOutcome(False, True, "already_awakened", "该 NPC 已经被记名觉醒。")
        if len(awakened) >= policy.player_awakened_slots:
            return TransactionOutcome(False, False, "awakened_slots_full", "玩家的记名觉醒名额已用完。")
        awakened.append(target_id)
        allocate_focus_slots(context.state, policy)
        context.emit(
            "NPC_AWAKENED_BY_PLAYER",
            f"{target.get('display_name', target_id)} 成为了玩家长期关注的人物。",
            actor_ids=["player"], target_ids=[target_id],
            payload={"target_id": target_id, "awakened_count": len(awakened)},
            visibility="private", severity=4,
            knowledge_tags=["cognition", "relationship"],
        )
        return TransactionOutcome(True, True, "success", "NPC 记名觉醒完成。", commit=True, payload={
            "target_id": target_id,
            "awakened_count": len(awakened),
            "remaining_slots": policy.player_awakened_slots - len(awakened),
        })
    return awaken


def make_cognition_decision_selector(runtime, graph, definitions, decision_policy):
    """Select through an LLM only after the rule layer produced legal candidates."""
    from simulation.systems.campus_decisions import (
        rank_campus_npc_activities,
        reserve_decision_destination,
    )

    def select(context, actor_id, schedule_plan, occupancy):
        candidates = rank_campus_npc_activities(
            context, actor_id, schedule_plan, graph, definitions, decision_policy, occupancy
        )
        if not candidates:
            return None
        chosen = runtime.select(context.state, actor_id, candidates) or deepcopy(candidates[0])
        reserve_decision_destination(graph, occupancy, str(chosen["location_id"]))
        return chosen

    return select


class CognitionRuntime:
    """Owns the ephemeral provider secret and applies persistent hard budgets."""

    def __init__(self, policy: CognitionPolicy, provider: CognitionProvider | None = None) -> None:
        self.policy = policy
        self.provider: CognitionProvider = provider or RuleOnlyProvider()

    def configure_rule(self) -> None:
        if isinstance(self.provider, OpenAICompatibleCognitionProvider):
            self.provider.secret_forget()
        self.provider = RuleOnlyProvider()

    def configure_openai_compatible(self, base_url: str, model: str, api_key: str) -> None:
        if not base_url or not model or not api_key:
            raise ValueError("兼容接口需要 Base URL、模型名和 API Key。")
        if isinstance(self.provider, OpenAICompatibleCognitionProvider):
            self.provider.secret_forget()
        self.provider = OpenAICompatibleCognitionProvider(
            base_url, model, api_key, timeout_seconds=self.policy.request_timeout_seconds,
        )

    def configure_ollama(self, base_url: str, model: str) -> None:
        if not base_url or not model:
            raise ValueError("Ollama 需要 Base URL 和模型名。")
        if isinstance(self.provider, OpenAICompatibleCognitionProvider):
            self.provider.secret_forget()
        self.provider = OllamaCognitionProvider(
            base_url, model, timeout_seconds=self.policy.request_timeout_seconds,
        )

    def publish_status(self, state: WorldState) -> None:
        state.cognition["provider"] = self.public_status()

    def public_status(self) -> Dict[str, Any]:
        return {
            "mode": self.provider.name,
            "configured": self.provider.configured,
            "model": self.provider.model,
        }

    def _request(self, state: WorldState, actor_id: str, candidates: Sequence[Mapping[str, Any]]) -> BoundedDecisionRequest:
        actor = state.population[actor_id]
        reflection = state.cognition.get("reflections", {}).get(actor_id, {})
        memories = state.cognition.get("memory_by_actor", {}).get(actor_id, [])[-self.policy.reflection_memory_limit:]
        public_candidates = tuple({
            "candidate_id": item["candidate_id"],
            "activity_id": item["activity_id"],
            "location_id": item["location_id"],
            "reason": item["decision_reason"],
            "reason_codes": list(item.get("reason_codes", ())),
            "rule_score": item.get("score", 0),
        } for item in candidates[:self.policy.candidate_limit])
        return BoundedDecisionRequest(
            npc_id=actor_id,
            candidate_revision=state.revision,
            day=state.clock.day,
            phase=state.clock.phase,
            identity={
                "role_kind": actor.get("role_kind"),
                "college_id": actor.get("college_id"),
                "occupation_id": actor.get("occupation_id"),
                "core_values": list(actor.get("core_values", ())),
                "moral_boundaries": list(actor.get("moral_boundaries", ())),
                "fear_id": actor.get("fear_id"),
                "obsession_id": actor.get("obsession_id"),
                "contradiction_id": actor.get("contradiction_id"),
                "personality": deepcopy(actor.get("personality", {})),
            },
            state={
                "location_id": actor.get("current_location_id"),
                "needs": deepcopy(actor.get("needs", {})),
                "emotions": deepcopy(actor.get("emotions", {})),
                "active_task": bool(actor.get("active_forum_task_id")),
            },
            reflection=str(reflection.get("summary", "")),
            memories=tuple({
                "day": item.get("day"), "phase": item.get("phase"),
                "summary": item.get("summary"), "confidence": item.get("confidence"),
                "interpretation": item.get("interpretation"),
            } for item in memories),
            candidates=public_candidates,
        )

    def _select_response(
        self,
        state: WorldState,
        request: BoundedDecisionRequest,
        *,
        purpose: str,
    ) -> BoundedDecisionResponse | None:
        usage = state.cognition["usage"]
        if usage.get("day") != state.clock.day:
            state.cognition["usage"] = usage = _fresh_usage(state.clock.day)
        phase_calls = int(usage["phase_calls"].get(state.clock.phase, 0))
        purpose_phase_calls = usage.setdefault("purpose_phase_calls", {})
        purpose_key = f"{state.clock.phase}:{purpose}"
        current_purpose_calls = int(purpose_phase_calls.get(purpose_key, 0))
        player_dialogue_calls = sum(
            int(value) for key, value in purpose_phase_calls.items()
            if str(key).endswith(":player_dialogue")
        )
        automated_calls = int(usage["calls"]) - player_dialogue_calls
        canonical = json.dumps(request.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        cache_payload = request.to_dict()
        cache_payload["candidate_revision"] = 0
        cache_canonical = json.dumps(
            cache_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        cache_key = hashlib.sha256(
            (self.provider.model + purpose + cache_canonical).encode("utf-8")
        ).hexdigest()
        cached = state.cognition["decision_cache"].get(cache_key)
        if isinstance(cached, dict):
            usage["cache_hits"] += 1
            raw = deepcopy(cached)
            raw["candidate_revision"] = state.revision
        else:
            estimated = max(1, len(canonical) // 4) + self.policy.max_output_tokens
            purpose_limit = (
                self.policy.phase_call_limit - self.policy.interaction_reserved_phase_calls
                if purpose == "activity"
                else self.policy.interaction_phase_call_limit
            )
            if (
                int(usage["calls"]) >= self.policy.daily_call_limit
                or automated_calls >= self.policy.daily_call_limit - self.policy.player_dialogue_daily_reserve
                or phase_calls >= self.policy.phase_call_limit
                or current_purpose_calls >= purpose_limit
                or int(usage["estimated_tokens"]) + estimated > self.policy.daily_estimated_token_limit
            ):
                usage["budget_blocks"] += 1
                usage["fallbacks"] += 1
                return None
            usage["calls"] += 1
            usage["phase_calls"][state.clock.phase] = phase_calls + 1
            purpose_phase_calls[purpose_key] = current_purpose_calls + 1
            usage["estimated_tokens"] += estimated
            try:
                raw = dict(self.provider.decide(request, max_output_tokens=self.policy.max_output_tokens))
            except Exception:
                usage["provider_errors"] += 1
                usage["fallbacks"] += 1
                return None
            provider_usage = raw.pop("_usage", {})
            if isinstance(provider_usage, dict):
                usage["prompt_tokens"] += int(provider_usage.get("prompt_tokens", 0))
                usage["completion_tokens"] += int(provider_usage.get("completion_tokens", 0))
            state.cognition["decision_cache"][cache_key] = deepcopy(raw)
            order = state.cognition["decision_cache_order"]
            order.append(cache_key)
            while len(order) > self.policy.cache_limit:
                state.cognition["decision_cache"].pop(order.pop(0), None)
        try:
            response = BoundedDecisionResponse.from_mapping(raw)
        except (TypeError, ValueError):
            usage["rejected_responses"] += 1
            usage["fallbacks"] += 1
            return None
        legal_ids = {
            str(item.get("candidate_id"))
            for item in request.candidates[:self.policy.candidate_limit]
        }
        if (
            response.npc_id != request.npc_id
            or response.candidate_revision != state.revision
            or response.selected_action_id not in legal_ids
        ):
            usage["rejected_responses"] += 1
            usage["fallbacks"] += 1
            return None
        return response

    def compose_phone_reply(
        self,
        state: WorldState,
        npc_id: str,
        target_id: str,
        incoming_text: str,
        recent_messages: Sequence[Mapping[str, Any]],
        allowed_facts: Sequence[Mapping[str, Any]] | None = None,
    ) -> Dict[str, Any] | None:
        """Generate non-authoritative wording from an NPC's bounded knowledge."""
        if (
            npc_id not in state.cognition.get("focused_ids", ())
            or not self.provider.configured
            or not callable(getattr(self.provider, "respond", None))
        ):
            return None
        actor = state.population[npc_id]
        fact_source = (
            allowed_facts
            if allowed_facts is not None
            else known_claims(state, npc_id)
        )
        allowed = tuple({
            "claim_id": item["claim"]["claim_id"],
            "summary": item["claim"]["summary"],
            "confidence": item["belief"]["confidence"],
            "source_kind": item["belief"]["source_kind"],
        } for item in fact_source[-8:])
        request = BoundedDialogueRequest(
            npc_id=npc_id,
            target_id=target_id,
            candidate_revision=state.revision,
            day=state.clock.day,
            phase=state.clock.phase,
            identity={
                "role_kind": actor.get("role_kind"),
                "college_id": actor.get("college_id"),
                "occupation_id": actor.get("occupation_id"),
                "core_values": list(actor.get("core_values", ())),
                "moral_boundaries": list(actor.get("moral_boundaries", ())),
                "personality": deepcopy(actor.get("personality", {})),
            },
            state={
                "needs": deepcopy(actor.get("needs", {})),
                "emotions": deepcopy(actor.get("emotions", {})),
            },
            relationship=deepcopy(state.relationships.get(npc_id, {}).get(target_id, {})),
            recent_messages=tuple({
                "sender_id": item.get("sender_id"),
                "receiver_id": item.get("receiver_id"),
                "day": item.get("day"),
                "phase": item.get("phase"),
                "text": str(item.get("text", ""))[:240],
            } for item in recent_messages[-6:]),
            incoming_text=incoming_text[:240],
            allowed_facts=allowed,
        )
        usage = state.cognition["usage"]
        if usage.get("day") != state.clock.day:
            state.cognition["usage"] = usage = _fresh_usage(state.clock.day)
        purpose_phase_calls = usage.setdefault("purpose_phase_calls", {})
        purpose_key = f"{state.clock.phase}:player_dialogue"
        current_purpose_calls = int(purpose_phase_calls.get(purpose_key, 0))
        canonical = json.dumps(
            request.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        estimated = max(1, len(canonical) // 4) + self.policy.max_output_tokens
        if (
            int(usage["calls"]) >= self.policy.daily_call_limit
            or current_purpose_calls >= self.policy.player_dialogue_phase_call_limit
            or int(usage["estimated_tokens"]) + estimated > self.policy.daily_estimated_token_limit
        ):
            usage["budget_blocks"] += 1
            usage["fallbacks"] += 1
            return None
        usage["calls"] += 1
        purpose_phase_calls[purpose_key] = current_purpose_calls + 1
        usage["estimated_tokens"] += estimated
        try:
            raw = dict(self.provider.respond(request, max_output_tokens=self.policy.max_output_tokens))
        except Exception:
            usage["provider_errors"] += 1
            usage["fallbacks"] += 1
            return None
        provider_usage = raw.pop("_usage", {})
        if isinstance(provider_usage, dict):
            usage["prompt_tokens"] += int(provider_usage.get("prompt_tokens", 0))
            usage["completion_tokens"] += int(provider_usage.get("completion_tokens", 0))
        try:
            response = BoundedDialogueResponse.from_mapping(raw)
        except (TypeError, ValueError):
            usage["rejected_responses"] += 1
            usage["fallbacks"] += 1
            return None
        allowed_ids = {str(item["claim_id"]) for item in allowed}
        if (
            response.npc_id != npc_id
            or response.target_id != target_id
            or response.candidate_revision != state.revision
            or not set(response.fact_ids_used).issubset(allowed_ids)
        ):
            usage["rejected_responses"] += 1
            usage["fallbacks"] += 1
            return None
        audit = state.cognition["decision_audit"]
        audit.append({
            "day": state.clock.day,
            "phase": state.clock.phase,
            "npc_id": npc_id,
            "target_id": target_id,
            "candidate_revision": state.revision,
            "purpose": "player_dialogue",
            "model": self.provider.model,
            "fact_ids_used": list(response.fact_ids_used),
        })
        del audit[:-96]
        return {
            "utterance": response.utterance,
            "fact_ids_used": list(response.fact_ids_used),
            "source": "llm",
        }

    def select(self, state: WorldState, actor_id: str, candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any] | None:
        if not candidates or actor_id not in state.cognition.get("focused_ids", ()) or not self.provider.configured:
            return None
        request = self._request(state, actor_id, candidates)
        response = self._select_response(state, request, purpose="activity")
        if response is None:
            return None
        legal = {item["candidate_id"]: item for item in candidates[:self.policy.candidate_limit]}
        chosen = deepcopy(legal[response.selected_action_id])
        chosen["rule_decision_source"] = chosen.get("decision_source", "rule")
        chosen["decision_source"] = "llm"
        chosen["decision_reason"] = "bounded_llm_choice"
        chosen["reason_codes"] = [*chosen.get("reason_codes", ()), "llm_preference"][:4]
        audit = state.cognition["decision_audit"]
        audit.append({
            "day": state.clock.day, "phase": state.clock.phase, "npc_id": actor_id,
            "candidate_revision": state.revision, "selected_action_id": response.selected_action_id,
            "purpose": "activity", "model": self.provider.model, "reason": response.reason[:500],
        })
        del audit[:-96]
        return chosen

    def select_interaction(
        self,
        state: WorldState,
        actor_id: str,
        target_id: str,
        candidates: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any] | None:
        if not candidates or actor_id not in state.cognition.get("focused_ids", ()) or not self.provider.configured:
            return None
        actor = state.population[actor_id]
        target = state.population[target_id]
        relation = state.relationships.get(actor_id, {}).get(target_id, {})
        memories = state.cognition.get("memory_by_actor", {}).get(actor_id, [])[-self.policy.reflection_memory_limit:]
        reflection = state.cognition.get("reflections", {}).get(actor_id, {})
        request = BoundedDecisionRequest(
            npc_id=actor_id,
            candidate_revision=state.revision,
            day=state.clock.day,
            phase=state.clock.phase,
            identity={
                "role_kind": actor.get("role_kind"),
                "college_id": actor.get("college_id"),
                "occupation_id": actor.get("occupation_id"),
                "core_values": list(actor.get("core_values", ())),
                "moral_boundaries": list(actor.get("moral_boundaries", ())),
                "personality": deepcopy(actor.get("personality", {})),
            },
            state={
                "location_id": actor.get("current_location_id"),
                "needs": deepcopy(actor.get("needs", {})),
                "emotions": deepcopy(actor.get("emotions", {})),
                "interaction_target": {
                    "npc_id": target_id,
                    "role_kind": target.get("role_kind"),
                    "college_id": target.get("college_id"),
                    "current_activity_id": target.get("current_activity", {}).get("activity_id"),
                },
                "relationship": deepcopy(relation),
                "known_information": [
                    {
                        "claim_id": item["claim"]["claim_id"],
                        "summary": item["claim"]["summary"],
                        "confidence": item["belief"]["confidence"],
                        "source_kind": item["belief"]["source_kind"],
                    }
                    for item in known_claims(state, actor_id)[-8:]
                ],
            },
            reflection=str(reflection.get("summary", "")),
            memories=tuple({
                "day": item.get("day"), "phase": item.get("phase"),
                "summary": item.get("summary"), "confidence": item.get("confidence"),
                "interpretation": item.get("interpretation"),
            } for item in memories),
            candidates=tuple({
                "candidate_id": item["candidate_id"],
                "activity_id": item.get("activity_id", "NPC_SOCIAL_INTERACTION"),
                "location_id": item.get("location_id"),
                "intent_id": item.get("intent_id"),
                "reason": item.get("reason"),
                "reason_codes": list(item.get("reason_codes", ())),
                "rule_score": item.get("rule_score", 0),
            } for item in candidates[:self.policy.candidate_limit]),
        )
        response = self._select_response(state, request, purpose="interaction")
        if response is None:
            return None
        legal = {item["candidate_id"]: item for item in candidates[:self.policy.candidate_limit]}
        chosen = deepcopy(legal[response.selected_action_id])
        chosen["model_reason"] = response.reason[:300]
        audit = state.cognition["decision_audit"]
        audit.append({
            "day": state.clock.day, "phase": state.clock.phase, "npc_id": actor_id,
            "target_id": target_id, "candidate_revision": state.revision,
            "selected_action_id": response.selected_action_id, "purpose": "interaction",
            "model": self.provider.model, "reason": response.reason[:500],
        })
        del audit[:-96]
        return chosen


def cognition_invariant(state: WorldState) -> Iterable[str]:
    aggregate = state.cognition
    if not aggregate:
        return ()
    errors: list[str] = []
    if aggregate.get("schema_version") != COGNITION_SCHEMA_VERSION:
        errors.append("cognition schema_version is unsupported")
    try:
        policy = CognitionPolicy(**aggregate.get("policy", {}))
    except (TypeError, ValueError) as exc:
        return [f"invalid cognition policy: {exc}"]
    focused = aggregate.get("focused_ids")
    awakened = aggregate.get("awakened_ids")
    if not isinstance(focused, list) or len(focused) != len(set(focused)) or len(focused) > policy.total_focus_slots:
        errors.append("cognition focused_ids exceed or violate slot policy")
        focused = []
    if not isinstance(awakened, list) or len(awakened) != len(set(awakened)) or len(awakened) > policy.player_awakened_slots:
        errors.append("cognition awakened_ids exceed or violate slot policy")
        awakened = []
    unknown = (set(focused) | set(awakened)) - (set(state.population) - {"player"})
    if unknown:
        errors.append("cognition slots reference unknown NPCs")
    if not set(awakened).issubset(set(focused)):
        errors.append("awakened NPCs must remain focused")
    for actor_id, memory_ids in aggregate.get("memory_by_actor", {}).items():
        if actor_id not in state.population or actor_id == "player" or not isinstance(memory_ids, list):
            errors.append(f"invalid cognition memory owner {actor_id}")
        elif len(memory_ids) > policy.memory_limit_per_actor:
            errors.append(f"cognition memory limit exceeded for {actor_id}")
    observation_ids_by_actor = aggregate.get("observation_ids_by_actor", {})
    observations = aggregate.get("observations", {})
    if not isinstance(observation_ids_by_actor, dict) or not isinstance(observations, dict):
        errors.append("cognition observations and indexes must be mappings")
    else:
        for actor_id, observation_ids in observation_ids_by_actor.items():
            if actor_id not in state.population or actor_id == "player" or not isinstance(observation_ids, list):
                errors.append(f"invalid cognition observation owner {actor_id}")
            elif len(observation_ids) > policy.observation_limit_per_actor:
                errors.append(f"cognition observation limit exceeded for {actor_id}")
            elif any(observation_id not in observations for observation_id in observation_ids):
                errors.append(f"cognition observation index is broken for {actor_id}")
    provider = aggregate.get("provider", {})
    if not isinstance(provider, dict) or "api_key" in provider or "base_url" in provider:
        errors.append("cognition provider state must be sanitized")
    return errors


__all__ = [
    "COGNITION_SCHEMA_VERSION", "CognitionRuntime", "advance_cognition_phase",
    "allocate_focus_slots", "cognition_invariant", "install_campus_cognition",
    "load_cognition_policy", "make_awaken_npc_handler", "make_cognition_decision_selector",
    "project_cognition_events",
]
