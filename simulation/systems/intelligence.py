from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Dict, Iterable, List, Optional

from simulation.domain.planning import IntelFact
from simulation.domain.interactions import IntelRecordReceipt


class IntelligenceSystem:
    def __init__(self):
        self.facts: Dict[str, IntelFact] = {}

    def create(self, *, subject_id: str, predicate: str, object_id: str, day: int,
               phase: str, source_type: str, source_id: Optional[str], confidence: float,
               secrecy: int, known_by: Iterable[str], evidence_ids=None,
               distortion: float = 0.0, summary: str = "") -> IntelFact:
        owners=list(dict.fromkeys(known_by))
        normalized_confidence=max(0.0, min(1.0, confidence))
        normalized_distortion=max(0.0, min(1.0, distortion))
        fact = IntelFact(
            id=f"intel_{uuid.uuid4().hex[:12]}", subject_id=subject_id,
            predicate=predicate, object_id=object_id, day=day, phase=phase,
            source_type=source_type, source_id=source_id,
            confidence=normalized_confidence, secrecy=max(0, min(100, secrecy)),
            distortion=normalized_distortion, known_by=owners,
            evidence_ids=list(evidence_ids or []),summary=summary,
            recall_confidence={actor_id:normalized_confidence for actor_id in owners},
            recall_distortion={actor_id:normalized_distortion for actor_id in owners})
        self.facts[fact.id] = fact
        return fact

    def known_facts(self, npc_id: str) -> List[IntelFact]:
        facts=[fact for fact in self.facts.values() if npc_id in fact.known_by]
        for fact in facts:
            self._ensure_recall(fact,npc_id)
        return facts

    def confidence_for(self,fact: IntelFact,actor_id: str) -> float:
        self._ensure_recall(fact,actor_id)
        return fact.recall_confidence.get(actor_id,0.0)

    def distortion_for(self,fact: IntelFact,actor_id: str) -> float:
        self._ensure_recall(fact,actor_id)
        return fact.recall_distortion.get(actor_id,1.0)

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
            speaker_confidence=self.confidence_for(fact,speaker.id)
            speaker_distortion=self.distortion_for(fact,speaker.id)
            recorded=speaker.id in fact.recorded_by
            carried_confidence=max(0.0,min(1.0,speaker_confidence*(0.96 if recorded else 0.86)))
            carried_distortion=max(0.0,min(1.0,speaker_distortion+(0.02 if recorded else 0.07)))
            fact.recall_confidence[listener.id]=max(
                fact.recall_confidence.get(listener.id,0.0),carried_confidence)
            fact.recall_distortion[listener.id]=min(
                fact.recall_distortion.get(listener.id,1.0),carried_distortion)
            return fact
        distorted = replace(
            fact, id=f"intel_{uuid.uuid4().hex[:12]}", source_type="statement",
            source_id=speaker.id, confidence=max(0.15, fact.confidence*0.55),
            distortion=min(1.0, fact.distortion+0.45), known_by=[listener.id],
            recorded_by=[],record_source_instance_ids={},
            recall_confidence={listener.id:max(0.15,self.confidence_for(fact,speaker.id)*0.55)},
            recall_distortion={listener.id:min(1.0,self.distortion_for(fact,speaker.id)+0.45)})
        self.facts[distorted.id] = distorted
        return distorted

    def record(self,world,*,actor_id: str,fact_id: str,item_id: str = "blank_notebook"):
        fact=self.facts.get(fact_id)
        if actor_id!="player" and actor_id not in world.npcs:
            return self._record_failure(actor_id,fact_id,item_id,"unknown_actor","记录者不存在。")
        if fact is None or actor_id not in fact.known_by:
            return self._record_failure(actor_id,fact_id,item_id,"unknown_information","不能记录尚未知晓的情报。")
        inventory=world.economy.actor_inventory(actor_id)
        if inventory.quantity(item_id)<1:
            return self._record_failure(actor_id,fact_id,item_id,"notebook_missing","记录情报需要空白笔记本。")
        instances=world.item_instances.instances_for(actor_id,item_id,world.day)
        instance=next((candidate for candidate in instances if candidate.condition>0),None)
        if instance is None:
            return self._record_failure(actor_id,fact_id,item_id,"notebook_unavailable","没有可用的笔记本实例。")
        before_confidence=self.confidence_for(fact,actor_id)
        before_distortion=self.distortion_for(fact,actor_id)
        use_definition=world.item_uses.definition(item_id)
        recording_bonus=int(use_definition.grants_effects.get("recording_bonus",0))
        after_confidence=max(before_confidence,min(1.0,0.80+recording_bonus/100))
        after_distortion=min(before_distortion,max(0.0,0.10-recording_bonus/300))
        if actor_id not in fact.recorded_by:
            fact.recorded_by.append(actor_id)
        fact.record_source_instance_ids[actor_id]=instance.id
        fact.recall_confidence[actor_id]=round(after_confidence,4)
        fact.recall_distortion[actor_id]=round(after_distortion,4)
        actor_name="玩家" if actor_id=="player" else world.npcs[actor_id].name
        return IntelRecordReceipt(
            True,"success",f"{actor_name}把情报记录在笔记本中，后续更不易遗忘或歪曲。",
            actor_id,fact_id,item_id,instance.id,before_confidence,after_confidence,
            before_distortion,after_distortion)

    def decay_day(self,current_day: int):
        changed=[]
        for fact in self.facts.values():
            if current_day<=fact.day:
                continue
            for actor_id in list(fact.known_by):
                self._ensure_recall(fact,actor_id)
                recorded=actor_id in fact.recorded_by
                confidence_loss=0.004 if recorded else 0.025
                distortion_gain=0.002 if recorded else 0.015
                before=(fact.recall_confidence[actor_id],fact.recall_distortion[actor_id])
                fact.recall_confidence[actor_id]=round(max(0.05,before[0]-confidence_loss),4)
                fact.recall_distortion[actor_id]=round(min(1.0,before[1]+distortion_gain),4)
                changed.append((fact.id,actor_id,recorded))
        return changed

    @staticmethod
    def _ensure_recall(fact: IntelFact,actor_id: str):
        if actor_id in fact.known_by:
            fact.recall_confidence.setdefault(actor_id,fact.confidence)
            fact.recall_distortion.setdefault(actor_id,fact.distortion)

    @staticmethod
    def _record_failure(actor_id,fact_id,item_id,code,message):
        return IntelRecordReceipt(False,code,message,actor_id,fact_id,item_id)
