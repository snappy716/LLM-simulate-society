from __future__ import annotations

from .registry import ActionDefinition, ActionRegistry, ActionResult


def _event(context, event_type, message, npc, *, target=None, tags=None, severity=3,
           conflict=0, danger=0, secret=0, trace_ids=None):
    event = context["make_event"](
        event_type, message, [npc.id] + ([target.id] if target else []),
        context["scene_id"], severity=severity, conflict=conflict, danger=danger,
        secret=secret, emotion=3, tags=list(tags or []),
        object_ids=list(trace_ids or []))
    return event


def _work(*, npc, context, **_):
    npc.wealth += 2
    event = _event(context, "WORK_COMPLETED", f"{npc.name} 完成工作并获得了收入。", npc,
                   tags=["work", "economy"], severity=1)
    return ActionResult(True, "success", event.description, event.event_id,
                        state_changes={"wealth": 2})


def _temporary_work(*, npc, context, **_):
    npc.wealth += 1
    event = _event(context, "TEMPORARY_WORK_FOUND", f"{npc.name} 找到一份临时工作，暂时缓解经济压力。",
                   npc, tags=["work", "poverty"], severity=2)
    return ActionResult(True, "success", event.description, event.event_id,
                        state_changes={"wealth": 1})


def _rest(*, npc, context, **_):
    npc.states["energy"] = min(100, npc.states.get("energy", 70)+35)
    event = _event(context, "REST_COMPLETED", f"{npc.name} 停下其他活动进行休息。", npc,
                   tags=["rest"], severity=1)
    return ActionResult(True, "success", event.description, event.event_id)


def _request_aid(*, npc, context, **_):
    npc.states["satiety"] = min(100, npc.states.get("satiety", 50)+35)
    event = _event(context, "AID_RECEIVED", f"{npc.name} 获得了一份食物和临时援助。", npc,
                   tags=["aid", "food"], severity=2)
    return ActionResult(True, "success", event.description, event.event_id)


def _share_intel(*, npc, context, target=None, fact_id=None, truthful=True, **_):
    if not target or not fact_id:
        return ActionResult(False, "missing_target", "交流缺少对象或具体情报。")
    system = context["intelligence"]
    fact = system.facts.get(fact_id)
    if not fact or npc.id not in fact.known_by:
        return ActionResult(False, "unknown_information", f"{npc.name} 并不知道这条情报。")
    if truthful and system.can_share(npc, target, fact) < 35:
        return ActionResult(False, "withheld", f"{npc.name} 决定不向 {target.name} 泄露这条情报。")
    shared = system.share(fact_id, npc, target, truthful=truthful)
    event_type = "INFORMATION_SHARED" if truthful else "FALSE_INFORMATION_SHARED"
    content=fact.summary or f"{fact.subject_id} {fact.predicate} {fact.object_id}"
    event = _event(context, event_type,
                   f"{npc.name} 向 {target.name} {'透露' if truthful else '声称'}：{content}。",
                   npc, target=target, tags=["social", "information"],
                   severity=3, secret=fact.secrecy)
    return ActionResult(True, "success", event.description, event.event_id,
                        produced_intel_ids=[shared.id])


def _steal(*, npc, context, target=None, **_):
    if not target or target.wealth <= 0:
        return ActionResult(False, "invalid_target", "没有可以偷窃的目标。")
    if target.current_scene != context["scene_id"]:
        return ActionResult(False, "target_absent", f"{target.name} 不在现场，偷窃无法实施。")
    check = context["opposed_check"](npc, target, "stealth", "observation", "偷窃")
    if check.margin < 15:
        event = _event(context, "THEFT_ATTEMPT_EXPOSED",
                       f"{target.name} 发现 {npc.name} 试图偷窃自己。", npc, target=target,
                       tags=["crime", "theft", "exposure"], severity=5, conflict=6)
        return ActionResult(False, "exposed", event.description, event.event_id)
    amount = min(target.wealth, 8)
    target.wealth -= amount
    npc.wealth += amount
    event = _event(context, "ITEM_STOLEN", f"{npc.name} 从 {target.name} 身上偷走了价值 {amount} 的财物。",
                   npc, target=target, tags=["crime", "theft"], severity=4, secret=7)
    return ActionResult(True, "success", event.description, event.event_id)


def _trade(*, npc, context, direction, shop_id=None, item_id=None, quantity=1, **_):
    if not shop_id or not item_id:
        return ActionResult(False, "missing_trade_target", "交易缺少商店或物品。")
    receipt = context["trade"](
        actor_id=npc.id, shop_id=shop_id, item_id=item_id,
        quantity=quantity, direction=direction,
    )
    wealth_delta = (-receipt.total_price if direction == "buy" else receipt.total_price)
    return ActionResult(
        receipt.success, receipt.code, receipt.message, receipt.event_id,
        state_changes={"wealth": wealth_delta} if receipt.success else {},
    )


def _generic(*, npc, context, action_label="行动", target=None, **_):
    event = _event(context, "ACTION_COMPLETED", f"{npc.name} 完成了{action_label}。", npc,
                   target=target, tags=["action"], severity=2)
    return ActionResult(True, "success", event.description, event.event_id)


def build_action_registry() -> ActionRegistry:
    registry = ActionRegistry()
    definitions = [
        ActionDefinition("DO_REGULAR_WORK", "economy", ["gain_money", "perform_duty"], _work,
                         energy_cost=5),
        ActionDefinition("SEEK_TEMPORARY_WORK", "economy", ["gain_money"], _temporary_work,
                         energy_cost=4),
        ActionDefinition("TAKE_SHORT_REST", "survival", ["restore_energy"], _rest),
        ActionDefinition("REQUEST_AID", "survival", ["solve_hunger", "seek_social_aid"], _request_aid),
        ActionDefinition("SHARE_INFORMATION", "social", ["perform_duty", "protect_friend"], _share_intel,
                         required_target="npc", required_skills=["insight"]),
        ActionDefinition("LIE_ABOUT_INFORMATION", "social", ["conceal_identity", "protect_faction"],
                         lambda **kw: _share_intel(truthful=False, **kw), required_target="npc",
                         required_skills=["deception"]),
        ActionDefinition("STEAL_ITEM", "crime", ["gain_money", "obtain_money_illegally"], _steal,
                         required_target="npc", required_skills=["stealth"], energy_cost=8, legal_risk=12),
        ActionDefinition("BUY_ITEM", "economy", ["solve_hunger", "obtain_supply"],
                         lambda **kw: _trade(direction="buy", **kw), required_target="shop",
                         energy_cost=1, tags=["trade", "item"]),
        ActionDefinition("SELL_ITEM", "economy", ["gain_money"],
                         lambda **kw: _trade(direction="sell", **kw), required_target="shop",
                         energy_cost=1, tags=["trade", "item"]),
    ]
    generic = {
        "OBSERVE_SCENE":("investigation", ["perform_duty"], 3),
        "SEARCH_SCENE":("investigation", ["perform_duty"], 7),
        "QUESTION_WITNESS":("investigation", ["perform_duty"], 4),
        "CHECK_RECORDS":("investigation", ["perform_duty"], 4),
        "WATCH_LOCATION":("investigation", ["protect_tingen", "protect_faction"], 5),
        "WARN_ACCOMPLICE":("crime", ["protect_faction"], 2),
        "MOVE_EVIDENCE":("crime", ["protect_faction", "conceal_identity"], 7),
        "DESTROY_EVIDENCE":("crime", ["protect_faction", "conceal_identity"], 7),
        "PERFORM_SECRET_RITUAL":("occult", ["protect_faction"], 18),
        "EXAMINE_OCCULT_TRACE":("occult", ["protect_tingen"], 8),
        "SURVEIL_SUSPECT":("official", ["protect_tingen"], 6),
        "PLAN_INTERVENTION":("official", ["protect_tingen"], 4),
        "STOP_RITUAL":("official", ["protect_tingen"], 16),
        "FLEE_TO_SCENE":("safety", ["avoid_arrest"], 10),
    }
    for action_id, (category, satisfies, cost) in generic.items():
        definitions.append(ActionDefinition(
            action_id, category, satisfies,
            lambda action_label=action_id, **kw: _generic(action_label=action_label, **kw),
            energy_cost=cost))
    for definition in definitions:
        registry.register(definition)
    return registry
