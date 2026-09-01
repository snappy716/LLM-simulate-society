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


def _peer_trade(*, npc, context, target=None, item_id=None, quantity=1,
                unit_price=None, accept=False, reason="", **_):
    if target is None or not item_id or unit_price is None:
        return ActionResult(False, "missing_trade_target", "NPC 交易缺少交易对象、物品或报价。")
    offer,error,_ = context["peer_offer"](
        seller_id=target.id,buyer_id=npc.id,item_id=item_id,
        quantity=quantity,unit_price=unit_price)
    if error is not None:
        return ActionResult(False,error.code,error.message)
    receipt,event = context["peer_trade_response"](
        offer_id=offer.id,responder_id=npc.id,accept=accept,reason=reason)
    # Refusing a valid quote is a completed decision and still consumes this
    # phase's trade action; it is not a failed engine command.
    completed = receipt.success or receipt.code == "rejected"
    wealth_delta=-receipt.total_price if receipt.success else 0
    return ActionResult(
        completed,receipt.code,receipt.message,
        event.event_id if event else receipt.event_id,
        state_changes={"wealth":wealth_delta} if receipt.success else {},
    )


def _use_item(*, npc, context, item_id=None, **_):
    if not item_id:
        return ActionResult(False,"missing_item","使用物品时必须指定 item_id。")
    receipt=context["use_item"](actor_id=npc.id,item_id=item_id)
    return ActionResult(
        receipt.success,receipt.code,receipt.message,receipt.event_id,
        state_changes=dict(receipt.state_changes) if receipt.success else {},
    )


def _give_item(*,npc,context,target=None,item_id=None,quantity=1,**_):
    if target is None or not item_id:
        return ActionResult(False,"missing_target","给予物品需要接收者和 item_id。")
    receipt=context["item_transfer"](
        action_id="GIVE_ITEM",actor_id=npc.id,target_id=target.id,
        item_id=item_id,quantity=quantity)
    return ActionResult(
        receipt.success,receipt.code,receipt.message,receipt.event_id,
        state_changes={"legal_risk":receipt.legal_risk_delta} if receipt.legal_risk_delta else {})


def _drop_item(*,npc,context,item_id=None,quantity=1,**_):
    if not item_id:
        return ActionResult(False,"missing_item","丢弃物品需要 item_id。")
    receipt=context["item_transfer"](
        action_id="DROP_ITEM",actor_id=npc.id,item_id=item_id,quantity=quantity)
    return ActionResult(receipt.success,receipt.code,receipt.message,receipt.event_id)


def _pick_up_item(*,npc,context,item_id=None,quantity=1,container_id=None,**_):
    if not item_id:
        return ActionResult(False,"missing_item","拾取物品需要 item_id。")
    receipt=context["item_transfer"](
        action_id="PICK_UP_ITEM",actor_id=npc.id,item_id=item_id,
        quantity=quantity,container_id=container_id)
    return ActionResult(
        receipt.success,receipt.code,receipt.message,receipt.event_id,
        state_changes={"legal_risk":receipt.legal_risk_delta} if receipt.legal_risk_delta else {})


def _equip_item(*,npc,context,item_id=None,instance_id=None,**_):
    if not item_id:
        return ActionResult(False,"missing_item","装备物品需要 item_id。")
    receipt=context["equipment_action"](
        action_id="EQUIP_ITEM",actor_id=npc.id,item_id=item_id,
        instance_id=instance_id)
    return ActionResult(
        receipt.success,receipt.code,receipt.message,receipt.event_id,
        state_changes=dict(receipt.state_changes) if receipt.success else {})


def _unequip_item(*,npc,context,item_id=None,instance_id=None,slot=None,**_):
    receipt=context["equipment_action"](
        action_id="UNEQUIP_ITEM",actor_id=npc.id,item_id=item_id,
        instance_id=instance_id,slot=slot)
    return ActionResult(receipt.success,receipt.code,receipt.message,receipt.event_id)


def _passage(action_id,*,npc,context,passage_id=None,**_):
    if not passage_id:
        return ActionResult(False,"missing_passage","入口行动需要 passage_id。")
    receipt=context["passage_action"](
        action_id=action_id,actor_id=npc.id,passage_id=passage_id)
    completed=receipt.success or receipt.check is not None
    return ActionResult(completed,receipt.code,receipt.message,receipt.event_id)


def _present_identity(*,npc,context,target=None,item_id=None,difficulty_override=None,**_):
    if target is None or not item_id:
        return ActionResult(False,"missing_identity_target","身份检查需要检查人员和身份物品。")
    receipt=context["identity_action"](
        actor_id=npc.id,inspector_id=target.id,item_id=item_id,
        difficulty_override=difficulty_override)
    # An attempted inspection consumes the action even when the deception fails.
    completed=receipt.success or receipt.check is not None
    return ActionResult(completed,receipt.code,receipt.message,receipt.event_id,
                        state_changes={"suspicion":receipt.suspicion_delta})


def _record_intelligence(*,npc,context,fact_id=None,**_):
    if not fact_id:
        return ActionResult(False,"missing_fact","记录情报需要 fact_id。")
    receipt=context["intel_action"](actor_id=npc.id,fact_id=fact_id)
    return ActionResult(receipt.success,receipt.code,receipt.message,receipt.event_id,
                        produced_intel_ids=[fact_id] if receipt.success else [])


def _threaten_with_weapon(*,npc,context,target=None,difficulty_override=None,**_):
    if target is None:
        return ActionResult(False,"missing_target","持械威慑需要指定目标。")
    receipt=context["weapon_action"](
        actor_id=npc.id,target_id=target.id,difficulty_override=difficulty_override)
    completed=receipt.success or receipt.check is not None
    return ActionResult(completed,receipt.code,receipt.message,receipt.event_id,
                        state_changes={"target_fear":receipt.fear_delta})


def _perform_ritual(illegal,*,npc,context,difficulty_override=None,**_):
    receipt=context["ritual_action"](
        actor_id=npc.id,illegal=illegal,difficulty_override=difficulty_override)
    completed=receipt.success or receipt.check is not None
    return ActionResult(
        completed,receipt.code,receipt.message,receipt.event_id,
        produced_trace_ids=list(receipt.consequences.trace_ids)
        if receipt.consequences else [],
        state_changes={"sanity":receipt.sanity_delta,
                       "legal_risk":receipt.legal_risk_delta}
        if receipt.success else {})


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
        ActionDefinition("TRADE_WITH_NPC", "economy", ["solve_hunger", "obtain_supply", "gain_money"],
                         _peer_trade, required_target="npc", energy_cost=1,
                         tags=["trade", "item", "peer_trade"]),
        ActionDefinition("USE_ITEM", "item", ["solve_hunger", "restore_energy", "obtain_supply"],
                         _use_item, energy_cost=1, tags=["item", "use"]),
        ActionDefinition("GIVE_ITEM","item",["protect_friend","seek_social_aid"],
                         _give_item,required_target="npc",energy_cost=1,tags=["item","transfer"]),
        ActionDefinition("DROP_ITEM","item",["conceal_identity"],
                         _drop_item,energy_cost=1,tags=["item","transfer"]),
        ActionDefinition("PICK_UP_ITEM","item",["obtain_supply"],
                         _pick_up_item,energy_cost=1,tags=["item","transfer"]),
        ActionDefinition("EQUIP_ITEM","item",["obtain_supply","protect_self"],
                         _equip_item,energy_cost=1,tags=["item","equipment"]),
        ActionDefinition("UNEQUIP_ITEM","item",["obtain_supply"],
                         _unequip_item,energy_cost=1,tags=["item","equipment"]),
        ActionDefinition("PICK_LOCK","environment",["obtain_supply","conceal_identity"],
                         lambda **kw:_passage("PICK_LOCK",**kw),energy_cost=3,
                         required_skills=["lockpicking"],tags=["item","passage","illegal"]),
        ActionDefinition("FORCE_OPEN","environment",["obtain_supply"],
                         lambda **kw:_passage("FORCE_OPEN",**kw),energy_cost=5,
                         required_skills=["force_entry"],tags=["item","passage","noisy"]),
        ActionDefinition("UNLOCK_WITH_KEY","environment",["obtain_supply"],
                         lambda **kw:_passage("UNLOCK_WITH_KEY",**kw),energy_cost=1,
                         tags=["item","passage","key"]),
        ActionDefinition("CLIMB_WITH_ROPE","environment",["obtain_supply"],
                         lambda **kw:_passage("CLIMB_WITH_ROPE",**kw),energy_cost=5,
                         required_skills=["climbing"],tags=["item","passage","climbing"]),
        ActionDefinition("TRAVERSE_PASSAGE","environment",["obtain_supply"],
                         lambda **kw:_passage("TRAVERSE_PASSAGE",**kw),energy_cost=1,
                         tags=["passage","movement"]),
        ActionDefinition("PRESENT_IDENTITY","social",["conceal_identity","perform_duty"],
                         _present_identity,required_target="npc",energy_cost=2,
                         required_skills=["deception"],tags=["item","identity","inspection"]),
        ActionDefinition("RECORD_INTELLIGENCE","investigation",["perform_duty","protect_faction"],
                         _record_intelligence,energy_cost=1,
                         tags=["item","notebook","information"]),
        ActionDefinition("THREATEN_WITH_WEAPON","conflict",["gain_money","protect_self"],
                         _threaten_with_weapon,required_target="npc",energy_cost=4,
                         required_skills=["combat"],tags=["item","weapon","illegal","threat"]),
        ActionDefinition("PERFORM_LEGAL_RITUAL","occult",["protect_self","perform_duty"],
                         lambda **kw:_perform_ritual(False,**kw),energy_cost=8,
                         required_skills=["ritual"],tags=["item","ritual","legal"]),
        ActionDefinition("PERFORM_SECRET_RITUAL","occult",["protect_faction"],
                         lambda **kw:_perform_ritual(True,**kw),energy_cost=12,
                         required_skills=["ritual"],tags=["item","ritual","illegal"]),
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
