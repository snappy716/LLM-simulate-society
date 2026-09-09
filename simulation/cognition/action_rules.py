"""Actor-local rule explanations, not a second policy or a decision engine."""
from copy import deepcopy


RULES_VERSION = 1
COMMON_RULES = {
    "choice": "规则说明可行条件，不替你选择。结合本人的性格、价值、需求、情绪、关系、已知经历与目标权衡；候选顺序和评分不是命令。",
    "primary": "每日为每个时段选择一个主体安排；可以选择合法的休息。主体安排与动作是否扣主要行动不是同一个概念，不必为耗尽次数而加班。",
    "free": "普通移动、购物、吃饭、短暂聊天不扣主要行动，属于可配合主体安排的附加行动；买完东西不代表整段学习、工作或休息已经完成。免费不等于无物资或其他条件。",
    "optional_purchase": "每日计划可从 free_options 自选附加采购，也可不选；这不是购物命令。执行时仅购买你所选的商店与物品，按仍存在的缺口缩减数量，条件变化可跳过，然后继续核对你选择的主体安排。",
    "cost": "主要行动受本人的实际剩余次数和预留约束，不能把两项都需要该次行动的任务排成同时完成。候选费用只是规划依据，执行时重新核验。",
    "place": "实体行动须实际沿可通行路线到达，检查开放时段、权限和适用场所。免费移动不等于瞬移或可以穿过关闭的入口。",
    "resources": "只能花费实际拥有的钱和物品，检查数量、容量、装备及必要材料。报价不是成交，接受后仍须原子核验和结算。",
    "commitment": "委托受真实接取锁、期限与资格限制；已确认约定可能预留行动。承诺不是到场，尚未履行不能说成已完成。",
    "consent": "其他人有自己的安排和意愿，邀请不是同意。可能没见到、被拒绝或条件变化；不把这些解释成背叛，不替玩家作决定。",
    "contact": "当面交流须满足实际同地条件；异地手机交流需要已有联系方式。通讯录不是所有人的名单，历史消息也不是实时定位。",
    "knowledge": "只使用本人知道的带来源、日期的信息，不读取他人私有计划或隐情。共享规则不授予新事实，也不是向玩家透露私人信息的许可。",
    "outcome": "模型表达和计划不直接创建物品、奖励、任务完成、关系承诺或治疗结果；只把已有实际结果说成已发生。",
    "failure": "原计划失效时保留真实原因，只能执行已经授权且仍合法的后续或兜底；日内不额外调用模型完整重排。失败反馈进入下一次跨日规划。",
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

    Only a boolean for this actor's current reservation is exposed. In
    particular, dialogue gets no private appointment, case or other actor IDs.
    """
    from simulation.systems.campus_departures import active_departure
    from simulation.systems.campus_anomaly_meetings import reserved_meeting

    budget = state.action_economy.get("actors", {}).get(actor_id, {})
    current = (budget.get("day"), budget.get("phase")) == (state.clock.day, state.clock.phase)
    return {
        "version": RULES_VERSION,
        "common": dict(COMMON_RULES),
        "clock": {"day": state.clock.day, "phase": state.clock.phase},
        "daily_planning": "只在跨日规划输入 day 所指的这一天，不额外加一天；日内执行并复核已选安排。",
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
