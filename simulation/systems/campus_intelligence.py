"""Subjective, source-tracked information for the campus simulation.

The claim catalogue is authoritative data, but an actor may only reason about
claims present in their own belief ledger. Sharing copies a fallible belief;
it never grants access to the catalogue as a whole.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping

from simulation.domain.world_state import WorldState
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP


CAMPUS_INTELLIGENCE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CampusIntelligencePolicy:
    shareable_intent_ids: tuple[str, ...]
    minimum_belief_confidence: float
    disclosure_base: float
    recent_share_limit: int

    def __post_init__(self) -> None:
        if not self.shareable_intent_ids:
            raise ValueError("campus intelligence needs at least one shareable intent")
        if len(set(self.shareable_intent_ids)) != len(self.shareable_intent_ids):
            raise ValueError("shareable campus intelligence intents must be unique")
        if not 0.0 <= self.minimum_belief_confidence <= 1.0:
            raise ValueError("minimum belief confidence must be between zero and one")
        if not 0.0 <= self.disclosure_base <= 100.0:
            raise ValueError("disclosure base must be between zero and one hundred")
        if isinstance(self.recent_share_limit, bool) or self.recent_share_limit < 1:
            raise ValueError("recent share limit must be a positive integer")


def load_campus_intelligence_policy(registry) -> CampusIntelligencePolicy:
    interaction_config = registry.get("configuration", "campus_interactions")
    payload = interaction_config.get(
        "information_exchange", {}
    )
    policy = CampusIntelligencePolicy(
        shareable_intent_ids=tuple(str(value) for value in payload.get("shareable_intent_ids", ())),
        minimum_belief_confidence=float(payload.get("minimum_belief_confidence", 0.35)),
        disclosure_base=float(payload.get("disclosure_base", 12.0)),
        recent_share_limit=int(payload.get("recent_share_limit", 96)),
    )
    intent_ids = {
        str(intent.get("id")) for intent in interaction_config.get("intents", ())
        if isinstance(intent, dict)
    }
    unknown = set(policy.shareable_intent_ids) - intent_ids
    if unknown:
        raise ValueError(f"unknown shareable campus interaction intents: {sorted(unknown)}")
    return policy


def _new_claim(
    state: WorldState,
    *,
    subject_id: str,
    predicate: str,
    object_id: str,
    summary: str,
    secrecy: int,
    known_by: Iterable[str],
    evidence_kind: str,
) -> Dict[str, Any]:
    if subject_id not in state.population:
        raise KeyError(f"unknown campus claim subject: {subject_id}")
    owners = list(dict.fromkeys(known_by))
    if any(owner_id not in state.population for owner_id in owners):
        raise KeyError("campus claim owner does not exist")
    if not predicate or not object_id or not summary:
        raise ValueError("campus claim fields cannot be empty")
    if isinstance(secrecy, bool) or not isinstance(secrecy, int) or not 0 <= secrecy <= 100:
        raise ValueError("campus claim secrecy must be between zero and one hundred")
    aggregate = state.knowledge
    aggregate["claim_sequence"] += 1
    claim_id = f"claim:{aggregate['claim_sequence']:08d}"
    claim = {
        "claim_id": claim_id,
        "subject_id": subject_id,
        "predicate": predicate,
        "object_id": object_id,
        "summary": summary[:240],
        "secrecy": secrecy,
        "evidence_kind": evidence_kind,
        "created_day": state.clock.day,
        "created_phase": state.clock.phase,
    }
    aggregate["claims"][claim_id] = claim
    for owner_id in owners:
        aggregate["beliefs_by_actor"][owner_id][claim_id] = {
            "claim_id": claim_id,
            "source_actor_id": owner_id,
            "upstream_source_actor_id": None,
            "source_kind": "self" if owner_id == subject_id else evidence_kind,
            "confidence": 1.0,
            "distortion": 0.0,
            "learned_day": state.clock.day,
            "learned_phase": state.clock.phase,
            "last_confirmed_day": state.clock.day,
            "last_confirmed_phase": state.clock.phase,
            "transmission_count": 0,
        }
    return claim


def create_campus_claim(
    state: WorldState,
    *,
    subject_id: str,
    predicate: str,
    object_id: str,
    summary: str,
    secrecy: int,
    known_by: Iterable[str],
    evidence_kind: str = "event",
) -> Dict[str, Any]:
    """Create a verified claim and explicitly assign its initial knowers."""
    if state.knowledge.get("schema_version") != CAMPUS_INTELLIGENCE_SCHEMA_VERSION:
        raise ValueError("campus intelligence is not installed")
    return _new_claim(
        state,
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
        summary=summary,
        secrecy=secrecy,
        known_by=known_by,
        evidence_kind=evidence_kind,
    )


def install_campus_intelligence(
    state: WorldState,
    colleges: Mapping[str, Mapping[str, Any]],
    clubs: Mapping[str, Mapping[str, Any]],
) -> None:
    if not state.population:
        raise ValueError("campus population must be installed before intelligence")
    if any(key in state.knowledge for key in ("claims", "beliefs_by_actor", "claim_sequence")):
        raise ValueError("campus intelligence is already installed")
    state.knowledge.update({
        "schema_version": CAMPUS_INTELLIGENCE_SCHEMA_VERSION,
        "claim_sequence": 0,
        "share_sequence": 0,
        "claims": {},
        "beliefs_by_actor": {actor_id: {} for actor_id in state.population},
        "recent_shares": [],
    })
    for actor_id, actor in sorted(state.population.items()):
        if not isinstance(actor, dict):
            continue
        display_name = str(actor.get("display_name", actor_id))
        role_name = "学生" if actor.get("role_kind") == "student" else "教职工"
        _new_claim(
            state,
            subject_id=actor_id,
            predicate="campus_role",
            object_id=str(actor.get("occupation_id", actor.get("role_kind", "campus_member"))),
            summary=f"{display_name}是校内{role_name}。",
            secrecy=5,
            known_by=[actor_id],
            evidence_kind="profile",
        )
        college_id = actor.get("college_id")
        if isinstance(college_id, str) and college_id in colleges:
            college_name = str(colleges[college_id].get("name", college_id))
            _new_claim(
                state,
                subject_id=actor_id,
                predicate="college_affiliation",
                object_id=college_id,
                summary=f"{display_name}来自{college_name}。",
                secrecy=5,
                known_by=[actor_id],
                evidence_kind="profile",
            )
        for club_id in actor.get("club_ids", ()):
            if club_id not in clubs:
                continue
            club_name = str(clubs[club_id].get("name", club_id))
            _new_claim(
                state,
                subject_id=actor_id,
                predicate="club_membership",
                object_id=str(club_id),
                summary=f"{display_name}参加了{club_name}。",
                secrecy=15,
                known_by=[actor_id],
                evidence_kind="profile",
            )


def known_claims(state: WorldState, actor_id: str) -> list[Dict[str, Any]]:
    beliefs = state.knowledge.get("beliefs_by_actor", {}).get(actor_id, {})
    claims = state.knowledge.get("claims", {})
    return [
        {"claim": deepcopy(claims[claim_id]), "belief": deepcopy(belief)}
        for claim_id, belief in sorted(beliefs.items())
        if claim_id in claims and isinstance(belief, dict)
    ]


def _disclosure_limit(
    state: WorldState,
    sender_id: str,
    receiver_id: str,
    policy: CampusIntelligencePolicy,
) -> float:
    sender = state.population[sender_id]
    relation = state.relationships.get(sender_id, {}).get(receiver_id, DEFAULT_RELATIONSHIP)
    personality = sender.get("personality", {})
    return max(0.0, min(100.0,
        policy.disclosure_base
        + 0.38 * int(relation.get("trust", 50))
        + 0.20 * int(relation.get("familiarity", 0))
        + 0.16 * int(relation.get("closeness", 0))
        + 0.16 * int(personality.get("openness", 50))
        - 0.22 * int(relation.get("suspicion", 0))
        - 0.12 * int(relation.get("conflict", 0))
    ))


def disclosable_known_claims(
    state: WorldState,
    sender_id: str,
    receiver_id: str,
    policy: CampusIntelligencePolicy,
) -> list[Dict[str, Any]]:
    """Return only beliefs this sender may safely disclose to this receiver."""
    if sender_id not in state.population or receiver_id not in state.population:
        raise KeyError("campus information disclosure actors must exist")
    disclosure_limit = _disclosure_limit(state, sender_id, receiver_id, policy)
    return [
        item for item in known_claims(state, sender_id)
        if float(item["belief"].get("confidence", 0.0)) >= policy.minimum_belief_confidence
        and int(item["claim"].get("secrecy", 100)) <= disclosure_limit
    ]


def share_specific_known_claim(
    state: WorldState,
    *,
    sender_id: str,
    receiver_id: str,
    claim_id: str,
    interaction_id: str,
    intent_id: str,
    policy: CampusIntelligencePolicy,
    acquisition_method: str = "direct_statement",
) -> Dict[str, Any] | None:
    """Copy one explicitly selected, disclosure-safe belief and its source chain."""
    eligible = {
        item["claim"]["claim_id"]: item
        for item in disclosable_known_claims(state, sender_id, receiver_id, policy)
    }
    item = eligible.get(claim_id)
    if item is None:
        return None
    receiver_beliefs = state.knowledge["beliefs_by_actor"][receiver_id]
    if claim_id in receiver_beliefs:
        return None
    claim = item["claim"]
    sender_belief = item["belief"]
    receiver_relation = state.relationships.get(receiver_id, {}).get(sender_id, DEFAULT_RELATIONSHIP)
    credibility = (
        0.55
        + 0.35 * int(receiver_relation.get("trust", 50)) / 100
        - 0.18 * int(receiver_relation.get("suspicion", 0)) / 100
    )
    confidence = round(max(0.1, min(
        0.98,
        float(sender_belief.get("confidence", 0.0))
        * max(0.25, credibility)
        * (1.0 - float(sender_belief.get("distortion", 0.0)) * 0.35),
    )), 3)
    distortion = round(min(
        1.0,
        float(sender_belief.get("distortion", 0.0))
        + 0.04
        + (100 - int(receiver_relation.get("trust", 50))) / 500,
    ), 3)
    receiver_beliefs[claim_id] = {
        "claim_id": claim_id,
        "source_actor_id": sender_id,
        "upstream_source_actor_id": sender_belief.get("source_actor_id"),
        "source_kind": "statement",
        "confidence": confidence,
        "distortion": distortion,
        "learned_day": state.clock.day,
        "learned_phase": state.clock.phase,
        "last_confirmed_day": state.clock.day,
        "last_confirmed_phase": state.clock.phase,
        "transmission_count": int(sender_belief.get("transmission_count", 0)) + 1,
    }
    state.knowledge["share_sequence"] += 1
    share_id = f"share:{state.knowledge['share_sequence']:08d}"
    sender_name = state.population[sender_id].get("display_name", sender_id)
    receiver_name = state.population[receiver_id].get("display_name", receiver_id)
    receipt = {
        "share_id": share_id,
        "claim_id": claim_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "interaction_id": interaction_id,
        "intent_id": intent_id,
        "day": state.clock.day,
        "phase": state.clock.phase,
        "source_actor_id": sender_id,
        "upstream_source_actor_id": sender_belief.get("source_actor_id"),
        "confidence": confidence,
        "distortion": distortion,
        "secrecy": int(claim["secrecy"]),
        "acquisition_method": acquisition_method,
        "dialogue_summary": f"{sender_name}对{receiver_name}说：“{claim['summary']}”",
    }
    recent = state.knowledge["recent_shares"]
    recent.append(deepcopy(receipt))
    del recent[:-policy.recent_share_limit]
    return receipt


def share_known_claim(
    state: WorldState,
    *,
    sender_id: str,
    receiver_id: str,
    interaction_id: str,
    intent_id: str,
    policy: CampusIntelligencePolicy,
    rng,
) -> Dict[str, Any] | None:
    """Copy one eligible subjective belief and preserve its source chain."""
    if sender_id not in state.population or receiver_id not in state.population:
        raise KeyError("campus information transfer actors must exist")
    if sender_id == receiver_id:
        raise ValueError("campus information cannot be shared with self")
    if intent_id not in policy.shareable_intent_ids:
        return None
    beliefs_by_actor = state.knowledge.get("beliefs_by_actor", {})
    sender_beliefs = beliefs_by_actor.get(sender_id, {})
    receiver_beliefs = beliefs_by_actor.get(receiver_id, {})
    claims = state.knowledge.get("claims", {})
    disclosure_limit = _disclosure_limit(state, sender_id, receiver_id, policy)
    candidates: list[tuple[float, str, Dict[str, Any], Dict[str, Any]]] = []
    for claim_id, belief in sender_beliefs.items():
        claim = claims.get(claim_id)
        if (
            not isinstance(claim, dict)
            or not isinstance(belief, dict)
            or claim_id in receiver_beliefs
            or float(belief.get("confidence", 0.0)) < policy.minimum_belief_confidence
            or int(claim.get("secrecy", 100)) > disclosure_limit
        ):
            continue
        novelty = 8 if claim.get("subject_id") != sender_id else 3
        score = (
            float(belief.get("confidence", 0.0)) * 60
            - int(claim.get("secrecy", 0)) * 0.3
            + novelty
            + rng.uniform(-4.0, 4.0)
        )
        candidates.append((score, claim_id, claim, belief))
    if not candidates:
        return None
    _, claim_id, _, _ = max(candidates, key=lambda item: (item[0], item[1]))
    return share_specific_known_claim(
        state,
        sender_id=sender_id,
        receiver_id=receiver_id,
        claim_id=claim_id,
        interaction_id=interaction_id,
        intent_id=intent_id,
        policy=policy,
    )


def campus_intelligence_invariant(state: WorldState) -> Iterable[str]:
    aggregate = state.knowledge
    if not aggregate:
        return ()
    errors: list[str] = []
    if aggregate.get("schema_version") != CAMPUS_INTELLIGENCE_SCHEMA_VERSION:
        errors.append("campus intelligence schema_version is unsupported")
    claims = aggregate.get("claims")
    beliefs_by_actor = aggregate.get("beliefs_by_actor")
    recent = aggregate.get("recent_shares")
    if not isinstance(claims, dict) or not isinstance(beliefs_by_actor, dict) or not isinstance(recent, list):
        return [*errors, "campus intelligence claims, beliefs, and shares have invalid containers"]
    for claim_id, claim in claims.items():
        if not isinstance(claim, dict) or claim.get("claim_id") != claim_id:
            errors.append(f"invalid campus claim {claim_id}")
        elif claim.get("subject_id") not in state.population:
            errors.append(f"campus claim {claim_id} references unknown subject")
        elif not 0 <= int(claim.get("secrecy", -1)) <= 100:
            errors.append(f"campus claim {claim_id} has invalid secrecy")
    for actor_id, beliefs in beliefs_by_actor.items():
        if actor_id not in state.population or not isinstance(beliefs, dict):
            errors.append(f"invalid campus belief owner {actor_id}")
            continue
        for claim_id, belief in beliefs.items():
            if claim_id not in claims or not isinstance(belief, dict):
                errors.append(f"campus belief references unknown claim {claim_id}")
                continue
            if belief.get("claim_id") != claim_id:
                errors.append(f"campus belief id mismatch for {claim_id}")
            if belief.get("source_actor_id") not in state.population:
                errors.append(f"campus belief {claim_id} references unknown source")
            if not 0.0 <= float(belief.get("confidence", -1.0)) <= 1.0:
                errors.append(f"campus belief {claim_id} has invalid confidence")
            if not 0.0 <= float(belief.get("distortion", -1.0)) <= 1.0:
                errors.append(f"campus belief {claim_id} has invalid distortion")
    for share in recent:
        if not isinstance(share, dict):
            errors.append("campus information share must be a mapping")
        elif share.get("claim_id") not in claims:
            errors.append("campus information share references unknown claim")
        elif share.get("sender_id") not in state.population or share.get("receiver_id") not in state.population:
            errors.append("campus information share references unknown actors")
    return errors


__all__ = [
    "CAMPUS_INTELLIGENCE_SCHEMA_VERSION", "CampusIntelligencePolicy",
    "campus_intelligence_invariant", "create_campus_claim", "disclosable_known_claims",
    "install_campus_intelligence", "known_claims",
    "load_campus_intelligence_policy", "share_known_claim", "share_specific_known_claim",
]
