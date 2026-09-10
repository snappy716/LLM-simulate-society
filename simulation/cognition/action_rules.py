"""Actor-local rule explanations, not a second policy or a decision engine."""
from copy import deepcopy


RULES_VERSION = 1
COMMON_RULES = {
    "choice": "按本人性格、价值、需求、情绪、关系、经历和目标自主权衡；规则限定可行性，排序/评分不是命令。",
    "primary": "每时段选一个主体安排，可合法休息；主体不等于必扣主要行动，不必耗尽次数。",
    "free": "普通移动、购物、吃饭、短聊不扣主要行动，但仍受条件/资源限制；不替代主体安排，买完不算上完课或做完工作。",
    "optional_purchase": "free_options 可选或不选；只买所选商店/物品，按实际缺口减量。条件失效可跳过，随后复核自选主体。",
    "cost": "执行时核验本人真实余次与预留，不能重复消费同一次主要行动；候选费用不是保证。",
    "place": "须沿开放且有权限的实际路线到适用场所；免费移动不是瞬移或穿越关闭入口。",
    "resources": "核验真实金钱、数量、容量、装备和材料；报价/接受不等于成交，仍须原子结算。",
    "commitment": "委托受接取锁、期限、资格限制；确认约定可能预留行动。承诺不是到场或完成。",
    "consent": "他人有独立安排和意愿；邀请不是同意，拒绝/未见/条件变化不是背叛，不替玩家决定。",
    "contact": "当面须同地，手机须已有联系；通讯录非全校名单，历史消息非实时定位。",
    "knowledge": "仅用本人已知且有来源/日期的信息；不读他人私密计划。规则不授予新事实或泄密许可。",
    "outcome": "说话/计划不创建物品、奖励、任务完成、关系承诺或治疗；仅实际结果可称已发生。",
    "failure": "失效保留真实原因，只执行已授权且仍合法的后续/兜底；日内不完整重排，失败留给次日规划。",
}
TRAIT_MEANINGS = {
    "extraversion": "主动交往与外部刺激倾向",
    "agreeableness": "体谅、合作与缓和分歧倾向",
    "conscientiousness": "持续投入、准备和履行承诺倾向",
    "openness": "探索新事物与接受新观点倾向",
    "emotional_sensitivity": "对压力和人际信号的敏感程度",
    "risk_tolerance": "接受不确定性与风险的倾向",
    "rule_alignment": "认同规范与维护秩序的倾向",
    "altruism": "在权衡自身需要时关心和帮助他人的倾向",
}


def action_rule_context(state, actor_id):
    """Read-only; budget numbers come from the authoritative runtime aggregate.

    Exposes only this actor's reserved slots and current budget. Dialogue gets
    no private appointment, case, location or other actor IDs from this block.
    """
    from simulation.systems.campus_departures import active_departure
    from simulation.systems.campus_anomaly_meetings import reserved_meeting
    from simulation.systems.campus_commitments import commitments_for

    budget = state.action_economy.get("actors", {}).get(actor_id, {})
    current = (budget.get("day"), budget.get("phase")) == (state.clock.day, state.clock.phase)
    return {
        "version": RULES_VERSION,
        "common": dict(COMMON_RULES),
        "clock": {"day": state.clock.day, "phase": state.clock.phase},
        "daily_planning": "只在跨日规划输入 day 所指的这一天，不额外加一天；日内执行并复核已选安排。",
        "own_confirmed_slots": [{key: row[key] for key in ("kind", "day", "phase", "major_action_cost")}
            for row in commitments_for(state, actor_id)],
        "phase_policy": deepcopy(state.action_economy.get("policy", {}).get("phases", {})),
        "own_current_budget": {
            "day": state.clock.day, "phase": state.clock.phase,
            "major_remaining": budget.get("major_remaining") if current else None,
            "known": current,
            "reserved_for_existing_commitment": bool(active_departure(state, actor_id) or reserved_meeting(state, actor_id)),
        },
        "personality_scale": {"minimum": 0, "maximum": 100,
            "meanings": dict(TRAIT_MEANINGS),
            "interpretation": "数值表示倾向，不是命令或必然行为；实际值使用 identity.personality。不同情境可以改变权衡。"},
        "planning_note": "未来时段上限不是保证可用次数，仍受已承诺事项、实际任务和执行时条件影响。",
    }


def candidate_cost(candidate):
    """Describe existing action metadata; never invent a cheap unknown action."""
    action_class = candidate.get("action_class")
    conditional_rest = candidate.get("activity_id") == "REST"
    cost = None if conditional_rest else {"free": 0, "major": 1}.get(action_class)
    return {"action_class": action_class, "major_action_cost": cost,
        "cost_rechecked_at_execution": True,
        **({"cost_condition": "普通休息沿用免费规则；在表世界住处恢复缺损生命/专注时，充分休息消耗一次主要行动。"}
           if conditional_rest else {})}
