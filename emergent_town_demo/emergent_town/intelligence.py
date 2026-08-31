from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Dict, Iterable, List, Optional

from .models import IntelFact


class IntelligenceSystem:
    def __init__(self):
        self.facts: Dict[str, IntelFact] = {}

    def create(self, *, subject_id: str, predicate: str, object_id: str, day: int,
               phase: str, source_type: str, source_id: Optional[str], confidence: float,
               secrecy: int, known_by: Iterable[str], evidence_ids=None,
               distortion: float = 0.0, summary: str = "") -> IntelFact:
        fact = IntelFact(
            id=f"intel_{uuid.uuid4().hex[:12]}", subject_id=subject_id,
            predicate=predicate, object_id=object_id, day=day, phase=phase,
            source_type=source_type, source_id=source_id,
            confidence=max(0.0, min(1.0, confidence)), secrecy=max(0, min(100, secrecy)),
            distortion=max(0.0, min(1.0, distortion)), known_by=list(dict.fromkeys(known_by)),
            evidence_ids=list(evidence_ids or []),summary=summary)
        self.facts[fact.id] = fact
        return fact

    def known_facts(self, npc_id: str) -> List[IntelFact]:
        return [fact for fact in self.facts.values() if npc_id in fact.known_by]

    def can_share(self, speaker, listener, fact: IntelFact) -> float:
        relation = speaker.relationships.get(listener.id)
        trust = relation.trust if relation else 35
        suspicion = relation.suspicion if relation else 0
        faction_loyalty = 35 if fact.secrecy >= 60 and speaker.faction_ids else 0
        score = trust + speaker.personality.get("social", 50)*0.25
        score += speaker.states.get("civic_duty", 50)*0.2
        score -= fact.secrecy*0.65 + suspicion*0.4 + faction_loyalty
        if set(speaker.faction_ids) & set(listener.faction_ids):
            score += 65
        return max(0.0, min(100.0, score))

    def share(self, fact_id: str, speaker, listener, *, truthful: bool = True) -> Optional[IntelFact]:
        fact = self.facts.get(fact_id)
        if not fact or speaker.id not in fact.known_by:
            return None
        if truthful:
            if listener.id not in fact.known_by:
                fact.known_by.append(listener.id)
            return fact
        distorted = replace(
            fact, id=f"intel_{uuid.uuid4().hex[:12]}", source_type="statement",
            source_id=speaker.id, confidence=max(0.15, fact.confidence*0.55),
            distortion=min(1.0, fact.distortion+0.45), known_by=[listener.id])
        self.facts[distorted.id] = distorted
        return distorted
