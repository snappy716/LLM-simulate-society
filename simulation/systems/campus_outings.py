"""Voluntary long shared activities. Consent is not attendance or romance.

The optional ledger is backward compatible with saves preceding this feature.
No money, relationship database, clock or model client is duplicated here.
"""
from copy import copy, deepcopy
from dataclasses import replace
from math import isfinite

from simulation.actions.commands import SimulationCommand
from simulation.systems.campus_anomalies import _available
from simulation.systems.campus_anomaly_meetings import stamp
from simulation.systems.campus_messaging import are_phone_contacts, append_structured_phone_message
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP, adjust_relationship
from simulation.systems.time import consume_major_action
from simulation.systems.transactions import TransactionOutcome

ACTIONS = ("INVITE_CAMPUS_OUTING", "ACCEPT_CAMPUS_OUTING", "DECLINE_CAMPUS_OUTING",
           "CANCEL_CAMPUS_OUTING", "ATTEND_CAMPUS_OUTING")
LIVE = {"pending", "confirmed"}
KINDS = {"companionship": "一起相处", "date": "约会"}
PLACES = ("mirror_lake_square", "library_reading_hall")
PHASES = ("afternoon", "evening")


def records(state):
    return state.situations.get("campus_outings", {}).get("records", {})


def participants(row):
    return (row["proposer_id"], row["recipient_id"])


def active_outing(state, actor):
    return next((r for r in records(state).values() if r["status"] == "confirmed"
        and actor in participants(r) and (r["day"], r["phase"]) == (state.clock.day, state.clock.phase)), None)


def willing(state, actor, other, kind):
    """NPC response policy, never auto-accept on behalf of the player.

    Relationship and personality are reasons to consider an invitation, not a
    charm roll purchasing a romantic relationship. The result is only this outing.
    """
    person = state.population[actor]
    relation = {**DEFAULT_RELATIONSHIP, **state.relationships.get(actor, {}).get(other, {})}
    if relation["suspicion"] >= 50 or relation["conflict"] >= 40 or relation["trust"] < 40:
        return False
    if max(person.get("needs", {}).get(k, 0) for k in ("rest", "food", "safety")) >= 90:
        return False
    if kind == "date":
        return relation["closeness"] >= 35 and relation["familiarity"] >= 30 and relation["trust"] >= 60
    social = person.get("needs", {}).get("social", 0)
    extroversion = person.get("personality", {}).get("extraversion", 50)
    return relation["familiarity"] >= 10 and relation["closeness"] + social + extroversion >= 75


def slot_problem(state, first, second, day, phase, location, graph, *, ignore=None):
    if (type(day) not in (int, float) or not isfinite(day) or day != int(day)
            or not state.clock.day <= day <= state.clock.day + 3
            or phase not in PHASES or location not in PLACES
            or stamp(day, phase) < stamp(state.clock.day, state.clock.phase)):
        return "请选择未来三天内的下午或晚间公共地点。"
    from simulation.systems.campus_commitments import commitments_at
    for who in (first, second):
        actor = state.population[who]
        if not _available(state, who):
            return "有人暂时无法在表世界活动。"
        if commitments_at(state, who, day, phase, ignore=("outing", ignore)):
            return "有人已经确认了这个时段的其他约定。"
        schedule = actor.get("weekly_schedule", {}).get(str((int(day) - 1) % 7), {}).get(phase, {})
        if int(schedule.get("priority", 0)) >= 90 or actor.get("active_forum_task_id"):
            return "有人需要先履行课程、工作或委托，不能覆盖原有责任。"
        if (day, phase) == (state.clock.day, state.clock.phase) and state.action_economy["actors"][who]["major_remaining"] < 1:
            return "有人已没有本时段的主要行动。"
        if not graph.is_open(location, phase) or graph.shortest_route(actor["current_location_id"], location,
                phase=phase, access_tags=actor.get("access_tags", ())) is None:
            return "有人无法沿开放道路抵达约定地点。"
    return None


def _notify(context, row, sender, message, policy):
    other = next(who for who in participants(row) if who != sender)
    sent = append_structured_phone_message(context, sender, other, message, policy, source="campus_outing")
    row["message_ids"].append(sent["message_id"])
    context.emit("CAMPUS_OUTING_UPDATED", message, actor_ids=participants(row), visibility="private",
        knowledge_tags=["schedule", "relationship"], payload={"outing_id": row["outing_id"], "status": row["status"]})


def _transition(context, row, status, actor, message, policy):
    row.update(status=status, revision=row["revision"] + 1, reason=message)
    _notify(context, row, actor, message, policy)


def visible_row(row, actor):
    result = deepcopy(row)
    if result["receipt"]:
        # A shared experience does not expose the partner's private budget or
        # their directional relationship scores to the viewer.
        receipt = result["receipt"]
        receipt["costs"] = {actor: receipt["costs"][actor]}
        receipt["relationship_deltas"] = {actor: receipt["relationship_deltas"][actor]}
    return result


def _result(row, actor, code="outing_updated"):
    return TransactionOutcome(True, True, code, row["reason"], commit=True,
        payload={"outing": visible_row(row, actor)})


def make_outing_handler(graph, action_policy, messaging_policy):
    def handle(context, command):
        state, actor, p = context.state, command.actor_id, command.parameters
        def fail(code, message):
            return TransactionOutcome(False, False, code, message)
        if actor not in state.population or (command.source == "player" and actor != "player"):
            return fail("actor_not_authorized", "不能代替他人作出邀请或同意。")
        if (command.issued_day, command.issued_phase) != (state.clock.day, state.clock.phase):
            return fail("command_clock_mismatch", "时段已变化，请刷新。")
        if command.action_id == "INVITE_CAMPUS_OUTING":
            target, kind = p.get("target_id"), p.get("kind", "companionship")
            if not isinstance(target, str) or target not in state.population or target == actor:
                return fail("invalid_recipient", "请选择一位其他人物。")
            if not isinstance(kind, str) or kind not in KINDS or not are_phone_contacts(state, actor, target):
                return fail("contact_required", "需要已有联系方式，并明确是普通相处还是约会。")
            day, phase, location = p.get("day"), p.get("phase"), p.get("location_id")
            problem = slot_problem(state, actor, target, day, phase, location, graph)
            if problem or stamp(day, phase) <= stamp(state.clock.day, state.clock.phase):
                return fail("outing_unavailable", problem or "请留出回应时间，选择后续时段。")
            pair = {actor, target}
            if any(set(participants(r)) == pair and (r["status"] in LIVE or
                    (r["created_day"], r["created_phase"]) == (state.clock.day, state.clock.phase)) for r in records(state).values()):
                return fail("outing_pair_cooldown", "已经邀请过，请等待回应或下一时段，不反复催促。")
            ledger = state.situations.setdefault("campus_outings", {"schema_version": 1, "records": {}})
            key = f"outing:{len(ledger['records']) + 1}"
            row = {"outing_id": key, "proposer_id": actor, "recipient_id": target, "kind": kind,
                "day": int(day), "phase": phase, "location_id": location,
                "created_day": state.clock.day, "created_phase": state.clock.phase,
                "status": "pending", "revision": 0, "message_ids": [], "attended": [], "receipt": None,
                "reason": "邀请已发出；答应并不代表已经赴约。"}
            ledger["records"][key] = row
            _notify(context, row, actor, f"愿意第 {int(day)} 天{phase}在{state.places[location]['name']}{KINDS[kind]}吗？各需留一次主要行动，随时可以取消。", messaging_policy)
            if target != "player":
                accepted = willing(state, target, actor, kind)
                _transition(context, row, "confirmed" if accepted else "declined", target,
                    "好，到时见；这次相处不意味着任何恋爱承诺。" if accepted else "这次暂不参加，谢谢你的邀请。", messaging_policy)
            return _result(row, actor, "outing_invited")
        key = p.get("outing_id")
        row = records(state).get(key) if isinstance(key, str) else None
        if not row or actor not in participants(row):
            return fail("outing_not_visible", "不能查看或操作他人的私人相处约定。")
        revision = p.get("expected_revision")
        if type(revision) not in (int, float) or revision != row["revision"] or row["status"] not in LIVE:
            return fail("outing_revision_conflict", "约定已变化，请刷新。")
        if command.action_id == "ACCEPT_CAMPUS_OUTING":
            if actor != row["recipient_id"] or row["status"] != "pending":
                return fail("recipient_required", "只有受邀者可以接受待回应邀请。")
            problem = slot_problem(state, *participants(row), row["day"], row["phase"], row["location_id"], graph, ignore=key)
            if problem:
                return fail("outing_unavailable", problem)
            if actor != "player" and not willing(state, actor, row["proposer_id"], row["kind"]):
                return fail("outing_declined", "本人目前不愿参加。")
            _transition(context, row, "confirmed", actor, "已同意本次相处；到场后仍需确认，不自动确立恋爱关系。", messaging_policy)
        elif command.action_id in ("DECLINE_CAMPUS_OUTING", "CANCEL_CAMPUS_OUTING"):
            declining = command.action_id == "DECLINE_CAMPUS_OUTING"
            if declining and (actor != row["recipient_id"] or row["status"] != "pending"):
                return fail("recipient_required", "只有受邀者可以拒绝待回应邀请。")
            _transition(context, row, "declined" if declining else "cancelled", actor,
                "已婉拒或取消；不扣行动，不返还已用行动，也不惩罚拒绝。", messaging_policy)
        elif command.action_id == "ATTEND_CAMPUS_OUTING":
            if row["status"] != "confirmed" or (row["day"], row["phase"]) != (state.clock.day, state.clock.phase):
                return fail("outing_not_due", "还未到已确认的约定时段。")
            if actor in row["attended"]:
                return fail("outing_already_arrived", "已经确认到场，仍需等待另一人。")
            if not _available(state, actor) or state.population[actor]["current_location_id"] != row["location_id"]:
                return fail("outing_wrong_location", "请先沿开放道路实际到达约定地点。")
            row["attended"].append(actor)
            row["revision"] += 1
            row["reason"] = "已确认到场；双方就绪前不扣行动、不发相处收益。"
            if command.source == "player":
                settle_outings(context, action_policy, messaging_policy)
            return _result(row, actor, "outing_arrived")
        else:
            return fail("unsupported_outing_action", "未知相处行动。")
        return _result(row, actor)
    return handle


def settle_outings(context, action_policy, messaging_policy):
    """After arrivals, settle both costs once within the parent transaction.

    Player attendance is explicit. All conditions and both budgets are checked
    before spending; there is no partial payment when a partner leaves or refuses.
    """
    state, count = context.state, 0
    for row in records(state).values():
        pair = participants(row)
        if (row["status"] != "confirmed" or set(row["attended"]) != set(pair)
                or (row["day"], row["phase"]) != (state.clock.day, state.clock.phase)):
            continue
        if not all(_available(state, who) and state.population[who]["current_location_id"] == row["location_id"]
                   and state.action_economy["actors"][who]["major_remaining"] >= 1 for who in pair):
            continue
        if not all(who == "player" or willing(state, who, next(x for x in pair if x != who), row["kind"]) for who in pair):
            _transition(context, row, "cancelled", row["proposer_id"], "当前有人不愿继续，取消本次相处。", messaging_policy)
            continue
        # Preflight on a detached world also checks every other reservation.
        # consume_major_action mutates only the budget aggregate. Copy that
        # aggregate, not thousands of unrelated world events for each pair.
        preview = copy(state)
        preview.action_economy = deepcopy(state.action_economy)
        commands = [replace(context.command, actor_id=who, action_id="ATTEND_CAMPUS_OUTING",
            parameters={"outing_id": row["outing_id"]}, issued_day=state.clock.day,
            issued_phase=state.clock.phase, source="rule") for who in pair]
        if not all(consume_major_action(preview, action_policy, cmd).success for cmd in commands):
            continue
        costs, gains = {}, {}
        for cmd in commands:
            who = cmd.actor_id
            before = state.action_economy["actors"][who]["major_remaining"]
            paid = consume_major_action(state, action_policy, cmd)
            if not paid.success:
                raise RuntimeError("preflighted outing budget changed inside transaction")
            costs[who] = {"before": before, "after": before - 1}
            other = next(x for x in pair if x != who)
            gains[who] = adjust_relationship(state, who, other, {"familiarity": 2, "closeness": 2, "trust": 1})
        row["receipt"] = {"command_id": context.command.command_id, "day": state.clock.day,
            "phase": state.clock.phase, "location_id": row["location_id"], "costs": costs,
            "relationship_deltas": gains, "summary": f"我们实际在{state.places[row['location_id']]['name']}共度了一段时间。"}
        for who in pair:
            activity = state.population[who].get("current_activity", {})
            if activity.get("activity_id") == "WAIT_CAMPUS_OUTING" and (activity.get("day"), activity.get("phase")) == (state.clock.day, state.clock.phase):
                activity.update(activity_id="ATTEND_CAMPUS_OUTING", action_class="major",
                    effects={"outing_id": row["outing_id"], "summary": row["receipt"]["summary"]})
        context.emit("CAMPUS_SHARED_OUTING_COMPLETED", row["receipt"]["summary"], actor_ids=pair,
            scene_id=row["location_id"], visibility="private", knowledge_tags=["activity", "relationship", "shared_experience"],
            payload={"outing_id": row["outing_id"], "kind": row["kind"]})
        _transition(context, row, "completed", row["proposer_id"], row["receipt"]["summary"], messaging_policy)
        count += 1
    return {"completed_outing_count": count}


def expire_outings(context, policy, *, ending=False):
    for row in records(context.state).values():
        due, now = stamp(row["day"], row["phase"]), stamp(context.state.clock.day, context.state.clock.phase)
        if row["status"] in LIVE and (due < now or (ending and due == now)):
            _transition(context, row, "missed", row["proposer_id"],
                "时段已结束，本次相处未完成；记录实际到场情况，不推断失约原因。", policy)


def outing_view(state, actor="player"):
    return [visible_row(r, actor) for r in records(state).values() if actor in participants(r)]


def outing_agenda_view(state, actor="player"):
    contacts = state.cognition.get("messaging", {}).get("contacts_by_actor", {}).get(actor, [])
    rows = outing_view(state, actor)
    for row in rows:
        other = next(who for who in participants(row) if who != actor)
        row["partner_name"] = state.population[other].get("display_name", other)
        row["location_name"] = state.places[row["location_id"]]["name"]
        row["can_reply"] = row["status"] == "pending" and row["recipient_id"] == actor
        row["can_cancel"] = row["status"] in LIVE
        row["can_attend"] = (row["status"] == "confirmed" and actor not in row["attended"]
            and (row["day"], row["phase"]) == (state.clock.day, state.clock.phase)
            and _available(state, actor) and state.population[actor]["current_location_id"] == row["location_id"])
    return {"records": rows, "contacts": [{"actor_id": who, "name": state.population[who].get("display_name", who)}
            for who in contacts if who in state.population],
        "slots": [{"day": day, "phase": phase, "location_id": location, "location_name": state.places[location]["name"]}
            for day in range(state.clock.day, state.clock.day + 4) for phase in PHASES for location in PLACES
            if location in state.places and stamp(day, phase) > stamp(state.clock.day, state.clock.phase)],
        "note": "只邀请已有联系人；可自由拒绝或取消。双方实际到场并确认才各扣一次主要行动，普通聊天免费。约会不自动确立恋爱关系。"}


def outing_plan(state, actor):
    row = active_outing(state, actor)
    if not row:
        return None
    original = state.cognition.get("daily_plans", {}).get("actors", {}).get(actor, {}).get(state.clock.phase, {})
    return {"activity_id": "WAIT_CAMPUS_OUTING", "action_class": "free", "location_id": row["location_id"],
        "day": state.clock.day, "phase": state.clock.phase, "decision_source": "rule", "candidate_count": 1,
        "planned_source": original.get("planned_source", "rule"),
        "decision_reason": "confirmed_shared_outing", "parameters": {"outing_id": row["outing_id"],
            "expected_revision": row["revision"]}}


def arrive_for_outing(context, command, handler):
    row = active_outing(context.state, command.actor_id)
    if not row or row["outing_id"] != command.parameters.get("outing_id"):
        return TransactionOutcome(False, False, "outing_unavailable", "约定已经变化。")
    return handler(context, replace(command, action_id="ATTEND_CAMPUS_OUTING",
        parameters={"outing_id": row["outing_id"], "expected_revision": row["revision"]}))


def outing_candidates(context, actor, schedule, graph, occupancy, policy, top_score):
    """Optional long-activity choices in the existing once-daily planning call.

    No extra model call and no omniscient scan of strangers' private diaries.
    Each intention still requires a reply and a successful reservation at dawn.
    """
    from simulation.systems.campus_decisions import _has_capacity
    state = context.state
    if state.clock.phase not in PHASES or int(schedule.get("priority", 0)) >= policy.protected_schedule_priority:
        return []
    person = state.population[actor]
    contacts = [who for who in state.relationships.get(actor, {}) if who != actor
        and who in state.population and are_phone_contacts(state, actor, who)]
    contacts.sort(key=lambda who: (-state.relationships[actor][who].get("closeness", 0), who))
    result = []
    for other in contacts[:3]:
        kind = "companionship"
        if not willing(state, actor, other, kind):
            continue
        if any(set(participants(r)) == {actor, other} and (r["status"] in LIVE or r["created_day"] >= state.clock.day - 1)
               for r in records(state).values()):
            continue
        for location in PLACES:
            if not _has_capacity(graph, occupancy, location) or slot_problem(state, actor, other,
                    state.clock.day, state.clock.phase, location, graph):
                continue
            route = graph.shortest_route(person["current_location_id"], location, phase=state.clock.phase,
                access_tags=person.get("access_tags", ()))
            intent = {"target_id": other, "kind": kind, "day": state.clock.day,
                "phase": state.clock.phase, "location_id": location}
            score = top_score - 18 + (person.get("needs", {}).get("social", 0) - 40) * .4
            score += (person.get("personality", {}).get("extraversion", 50) - 50) * .2
            result.append({"candidate_id": f"outing-choice:{actor}:{other}:{state.clock.day}:{state.clock.phase}:{location}",
                "activity_id": "WAIT_CAMPUS_OUTING", "action_class": "major", "location_id": location,
                "parameters": {"outing_intent": intent}, "priority": 40, "decision_source": "rule",
                "decision_reason": f"邀请熟人{state.population[other].get('display_name', other)}共同相处；需对方同意，各留一次主要行动，实际到场才有共同经历；被拒绝则按原日程。",
                "reason_codes": ["personal_interest", "voluntary_companionship"], "score": round(score, 3),
                "day": state.clock.day, "phase": state.clock.phase, "route_minutes": route.total_minutes})
            # A separate legal choice, not an automatic upgrade of friendship.
            # Same daily request, same consent/reservation/attendance pipeline.
            from simulation.systems.campus_bonds import own_bond_context
            if willing(state, actor, other, "date") and any(
                    r["other_id"] == other and r["status"] == "active" for r in own_bond_context(state, actor)):
                date = deepcopy(result[-1])
                date["candidate_id"] += ":date"
                date["parameters"]["outing_intent"]["kind"] = "date"
                date["decision_reason"] = f"明确邀请{state.population[other].get('display_name', other)}约会；可拒绝，不自动确立恋爱关系。"
                date["score"] += .01
                date["reason_codes"] = ["personal_interest", "voluntary_date"]
                result.append(date)
            break
    return result


def invite_chosen_outings(context, plans, handler):
    if context.state.clock.phase != "morning":
        return
    people = sorted(plans)
    offset = (context.state.clock.day - 1) % max(1, len(people))
    for actor in people[offset:] + people[:offset]:
        for plan in plans[actor].values():
            intent = plan.get("parameters", {}).get("outing_intent")
            if not intent:
                continue
            command = SimulationCommand(f"daily-outing:{actor}:{context.state.clock.day}", actor,
                "INVITE_CAMPUS_OUTING", context.state.revision, parameters=intent,
                issued_day=context.state.clock.day, issued_phase=context.state.clock.phase, source="rule")
            outcome = handler(context, command)
            plan["outing_response_code"] = outcome.code
            if outcome.success:
                plan["outing_id"] = outcome.payload["outing"]["outing_id"]
            break  # One invitation considered per daily plan, not an API quota.


def outings_invariant(state):
    ledger = state.situations.get("campus_outings")
    if ledger is None:
        return []
    try:
        if ledger["schema_version"] != 1:
            return ["invalid outing ledger version"]
        occupied = set()
        for key, row in ledger["records"].items():
            pair = set(participants(row))
            if (key != row["outing_id"] or len(pair) != 2 or not pair <= state.population.keys()
                    or row["kind"] not in KINDS or row["phase"] not in PHASES or row["location_id"] not in PLACES
                    or type(row["day"]) is not int or type(row["created_day"]) is not int
                    or not 1 <= row["created_day"] <= state.clock.day
                    or not row["created_day"] <= row["day"] <= row["created_day"] + 3
                    or stamp(row["day"], row["phase"]) <= stamp(row["created_day"], row["created_phase"])
                    or type(row["revision"]) is not int or row["revision"] < 0 or not row["message_ids"]
                    or row["status"] not in LIVE | {"declined", "cancelled", "missed", "completed"}
                    or not set(row["attended"]) <= pair or len(row["attended"]) != len(set(row["attended"]))):
                return ["invalid outing record"]
            if row["status"] in {"pending", "declined"} and row["attended"]:
                return ["unconfirmed outing claims attendance"]
            if row["status"] == "confirmed":
                slots = {(who, row["day"], row["phase"]) for who in pair}
                if slots & occupied:
                    return ["overlapping outings"]
                occupied.update(slots)
            receipt = row["receipt"]
            if row["status"] == "completed":
                if (set(row["attended"]) != pair or not receipt or not receipt["command_id"]
                        or (receipt["day"], receipt["phase"], receipt["location_id"]) != (row["day"], row["phase"], row["location_id"])
                        or stamp(row["day"], row["phase"]) > stamp(state.clock.day, state.clock.phase)
                        or set(receipt["costs"]) != pair or set(receipt["relationship_deltas"]) != pair):
                    return ["outing lacks shared attendance receipt"]
                for who in pair:
                    cost = receipt["costs"][who]
                    maximum = state.action_economy["policy"]["phases"][row["phase"]]["major_actions"]
                    if (type(cost["before"]) is not int or type(cost["after"]) is not int or cost["after"] < 0
                            or cost["before"] > maximum or cost["before"] - cost["after"] != 1):
                        return ["invalid shared outing cost"]
                    gains = receipt["relationship_deltas"][who]
                    if set(gains) != {"familiarity", "closeness", "trust"} or any(
                            type(gains[k]) is not int or not 0 <= gains[k] <= maximum
                            for k, maximum in (("familiarity", 2), ("closeness", 2), ("trust", 1))):
                        return ["invalid shared outing relationship receipt"]
            elif receipt is not None:
                return ["unfinished outing claims shared experience"]
    except (KeyError, ValueError, TypeError, AttributeError):
        return ["malformed outing ledger"]
    return []
