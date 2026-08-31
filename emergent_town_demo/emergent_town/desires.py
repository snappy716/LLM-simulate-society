from __future__ import annotations

from typing import Dict, List

from .models import Desire


class DesireEngine:
    """Turns state into competing motives; it never chooses an action itself."""

    def evaluate(self, npc, world=None) -> List[Desire]:
        states = npc.states
        morality = npc.personality.get("morality", 50)
        risk = npc.personality.get("risk", 50)
        ambition = npc.personality.get("ambition", 50)
        wealth = max(0, npc.wealth)
        desires: Dict[str, Desire] = {}

        def add(desire_id: str, strength: float, reason: str):
            strength = max(0.0, min(100.0, strength))
            if strength <= 0:
                return
            item = desires.setdefault(desire_id, Desire(desire_id, strength, []))
            item.strength = max(item.strength, strength)
            item.reasons.append(reason)

        add("restore_energy", 100 - states.get("energy", 70), "精力不足")
        add("solve_hunger", 100 - states.get("satiety", 70), "饱食度不足")
        add("seek_treatment", 100 - npc.health, "健康受损")
        add("preserve_sanity", 100 - npc.sanity, "理智受损")
        add("reduce_stress", states.get("stress", 0), "压力累积")
        add("seek_company", states.get("loneliness", 0), "感到孤独")
        add("gain_money", min(100, (50-wealth)*1.4 + npc.needs.get("financial_pressure", 0)*0.55), "经济压力")
        add("preserve_reputation", 100-states.get("reputation", 50), "声誉受损")
        add("avoid_arrest", states.get("legal_risk", 0)*1.15, "法律风险")
        add("perform_duty", states.get("civic_duty", 50)*0.7, "职业或公民责任")

        if wealth < 10 and states.get("satiety", 70) < 30:
            add("seek_social_aid", 65 + morality*0.25, "贫困且饥饿")
            add("obtain_money_illegally", 35 + risk*0.35 + ambition*0.2 - morality*0.45,
                "缺钱且缺少食物")
        if getattr(npc, "layer", "ordinary") == "official_beyonder":
            add("protect_tingen", 75 + states.get("alertness", 50)*0.2, "官方非凡者职责")
        if getattr(npc, "layer", "ordinary") == "hostile_beyonder":
            add("protect_faction", 70 + states.get("alertness", 50)*0.2, "隐秘组织职责")
            add("conceal_identity", 45 + states.get("legal_risk", 0)*0.6, "隐藏非凡身份")
        special = getattr(npc, "special_needs", {})
        if "crime_control" in special:
            add("commit_crime", 100-special["crime_control"], "犯罪自制力正在下降")
        if "ritual_stability" in special:
            add("perform_ritual", 100-special["ritual_stability"], "仪式稳定感正在下降")
        if "occult_supply" in special:
            add("collect_occult_item", 100-special["occult_supply"], "非凡材料储备正在下降")
        return sorted(desires.values(), key=lambda desire: desire.strength, reverse=True)

    def dominant(self, npc, world=None, limit: int = 3) -> List[Desire]:
        return self.evaluate(npc, world)[:limit]
