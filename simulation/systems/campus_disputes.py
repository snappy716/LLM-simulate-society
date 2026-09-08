"""Private, persistent disagreements grounded in real surface confrontations.

Listening is not proof of blame. Mediation needs both current statements and
both participants' willingness; no rewards, teleportation or forced consent.
"""
from dataclasses import replace

from simulation.actions.commands import SimulationCommand
from simulation.systems.campus_messaging import are_phone_contacts, append_structured_phone_message
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP, adjust_relationship
from simulation.systems.campus_vitals import actor_layer, battle_locked
from simulation.systems.transactions import TransactionOutcome

DISPUTE_ACTIONS = ("ASK_NPC_DISPUTE", "MEDIATE_DISPUTE")
OPEN = {"open", "easing"}


def _ledger(state):
    return state.situations.setdefault("campus_disputes", {"schema_version": 1, "sequence": 0, "cases": {}, "last_auto_phase": -1})


def _tick(state):
    from simulation.systems.campus_tasks import phase_index
    return phase_index(state.clock.day, state.clock.phase)


def _relation(state, actor, target):
    return {**DEFAULT_RELATIONSHIP, **state.relationships.get(actor, {}).get(target, {})}


def record_dispute(context, interaction):
    state = context.state
    first, second = interaction["actor_id"], interaction["target_id"]
    if (interaction["intent_id"] != "confront" or interaction["outcome"] != "rejected"
            or "player" in (first, second) or any(actor_layer(state, n) != "surface" for n in (first, second))):
        return
    ledger = _ledger(state)
    if any(interaction["interaction_id"] in c["source_interaction_ids"] for c in ledger["cases"].values()):
        return
    parties = sorted((first, second))
    case = next((c for c in ledger["cases"].values() if c["parties"] == parties and c["status"] in OPEN), None)
    if case is None:
        ledger["sequence"] += 1
        case_id = f"campus-dispute:{ledger['sequence']}"
        case = {"case_id": case_id, "parties": parties, "created_day": state.clock.day, "created_tick": _tick(state),
            "status": "open", "revision": 0, "source_interaction_ids": [], "statements": {}, "disclosed_to": [],
            "last_attempt_day": 0, "history": [], "location_id": interaction["scene_id"]}
        ledger["cases"][case_id] = case
    case["source_interaction_ids"] = [*case["source_interaction_ids"], interaction["interaction_id"]][-12:]
    case["revision"] += 1
    case["status"] = "open"
    case["statements"] = {}  # New disagreement invalidates old willingness.
    case["history"] = [*case["history"], {"day": state.clock.day, "kind": "confrontation", "source": interaction["interaction_id"]}][-24:]
    context.emit("CAMPUS_DISPUTE_OPENED", "一次未缓和的当面争执留下了待处理的分歧，双方尚未和解。",
        actor_ids=parties, scene_id=interaction["scene_id"], visibility="private", severity=3,
        knowledge_tags=["social", "dispute"], payload={"case_id": case["case_id"], "source_interaction_id": interaction["interaction_id"]})


def _reachable(state, actor, target):
    return (not battle_locked(state, actor) and not battle_locked(state, target)
        and actor_layer(state, actor) == actor_layer(state, target) == "surface"
        and (are_phone_contacts(state, actor, target) or state.population[actor]["current_location_id"] == state.population[target]["current_location_id"]))


def _willing(state, target, mediator):
    relation = _relation(state, target, mediator)
    return (relation["trust"] >= 35 and relation["suspicion"] < 60 and relation["conflict"] < 50
            and state.population[target].get("emotions", {}).get("anger", 0) < 75)


def _statement(context, case, actor, target, messaging_policy):
    state = context.state
    willing = _willing(state, target, actor)
    text = "之前那次当面争执还没有说清。我愿意先听听彼此的想法，不代表已经原谅或同意对方。" if willing else "这件事我现在不想谈，请先给我一点空间。"
    case["statements"].setdefault(actor, {})[target] = {"day": state.clock.day, "case_revision": case["revision"], "willing": willing, "summary": text}
    if actor not in case["disclosed_to"]:
        case["disclosed_to"].append(actor)
    if are_phone_contacts(state, actor, target):
        append_structured_phone_message(context, target, actor, text, messaging_policy, source="dispute_statement")
    context.emit("CAMPUS_DISPUTE_STATEMENT", text, actor_ids=[target], target_ids=[actor], visibility="private",
        knowledge_tags=["social", "dispute", "firsthand_statement"], payload={"case_id": case["case_id"], "willing": willing})
    return text


def dispute_view(state, actor_id="player"):
    rows = []
    for case in state.situations.get("campus_disputes", {}).get("cases", {}).values():
        if actor_id not in case["disclosed_to"] and actor_id not in case["parties"]:
            continue
        statements = case["statements"].get(actor_id, {})
        rows.append({"case_id": case["case_id"], "status": case["status"], "revision": case["revision"],
            "parties": [{"npc_id": n, "name": state.population[n]["display_name"],
                         "heard": n in statements and statements[n]["case_revision"] == case["revision"] and statements[n]["day"] == state.clock.day}
                        for n in case["parties"]],
            "can_attempt": case["status"] in OPEN and case["last_attempt_day"] != state.clock.day,
            "summary": "待听取双方意见" if case["status"] == "open" else "分歧已缓和，仍需后续沟通" if case["status"] == "easing" else "本次分歧已达成和解"})
    return rows


def make_dispute_handler(messaging_policy):
    def handle(context, command):
        state, actor = context.state, command.actor_id
        def fail(code, text):
            return TransactionOutcome(False, False, code, text)
        if actor not in state.population or (command.source == "player" and actor != "player"):
            return fail("actor_not_authorized", "不能替其他人处理纠纷。")
        if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
            return fail("command_clock_mismatch", "这次交谈所属的时段已经过期。")
        ledger = _ledger(state)
        case_id = command.parameters.get("case_id")
        if case_id is not None and not isinstance(case_id, str):
            return fail("invalid_parameters", "纠纷编号格式不正确。")
        if command.action_id == "ASK_NPC_DISPUTE":
            target = command.parameters.get("npc_id")
            if not isinstance(target, str) or target not in state.population or target == actor:
                return fail("unknown_npc", "请选择其他人物。")
            if not _reachable(state, actor, target):
                return fail("not_available", "需要当面或已有手机联系方式，且双方处于表世界、没有参战。")
            case = next((c for c in ledger["cases"].values() if c["status"] in OPEN and target in c["parties"]
                         and (case_id is None or c["case_id"] == case_id)), None)
            if case is None:
                return fail("no_known_dispute", "对方暂时没有可以谈及的未解决争执。")
            if actor in case["parties"]:
                return fail("not_neutral", "当事人不能把自己当作独立调解者。")
            old = case["statements"].get(actor, {}).get(target, {})
            if old.get("day") == state.clock.day and old.get("case_revision") == case["revision"]:
                return TransactionOutcome(True, True, "already_heard", old["summary"], payload={"case": next(r for r in dispute_view(state, actor) if r["case_id"] == case["case_id"])})
            # A refusal grants no case identity or information about the other party.
            if not _willing(state, target, actor):
                return fail("statement_withheld", "对方现在不愿谈及这件事，请尊重其意愿。")
            text = _statement(context, case, actor, target, messaging_policy)
            view = next(r for r in dispute_view(state, actor) if r["case_id"] == case["case_id"])
            return TransactionOutcome(True, True, "success", text, commit=True, payload={"case": view})
        case = ledger["cases"].get(case_id)
        if not case or actor not in case["disclosed_to"]:
            return fail("unknown_dispute", "尚未了解这项纠纷。")
        if actor in case["parties"]:
            return fail("not_neutral", "调解者不能是纠纷当事人。")
        if case["status"] not in OPEN:
            return fail("dispute_closed", "本次分歧已经处理，不能重复获取效果。")
        if case["last_attempt_day"] == state.clock.day:
            return fail("dispute_cooldown", "今天已经尝试过，请给双方一些时间。")
        revision = command.parameters.get("expected_case_revision")
        # Godot round-trips JSON numbers as floats; integral 1.0 is revision 1.
        if type(revision) not in (int, float) or revision != case["revision"]:
            return fail("dispute_revision_conflict", "纠纷情况已变化，请重新听取双方意见。")
        if any(not _reachable(state, actor, n) for n in case["parties"]):
            return fail("not_available", "需要能够联系双方，不能隔空替不在场且无联系方式的人作主。")
        statements = case["statements"].get(actor, {})
        if any(statements.get(n, {}).get("case_revision") != case["revision"] or statements.get(n, {}).get("day") != state.clock.day for n in case["parties"]):
            return fail("both_statements_required", "需要先分别听取双方今天的意见，不能只听一面之词。")
        case["last_attempt_day"] = state.clock.day
        if not all(_willing(state, n, actor) for n in case["parties"]):
            text, kind = "有一方现在不愿继续，调解暂停；未强行改变双方关系。", "declined"
        else:
            attrs = state.population[actor].get("attributes", {})
            relief = 6 + min(8, (int(attrs.get("empathy", 5)) + int(attrs.get("insight", 5))) // 2)
            first, second = case["parties"]
            for owner, target in ((first, second), (second, first)):
                adjust_relationship(state, owner, target, {"conflict": -relief, "trust": 2})
                emotions = state.population[owner].get("emotions", {})
                emotions["anger"] = max(0, int(emotions.get("anger", 0)) - 5)
            case["status"] = "settled" if max(_relation(state, first, second)["conflict"], _relation(state, second, first)["conflict"]) <= 10 else "easing"
            kind = case["status"]
            text = "双方在沟通后达成了本次和解；这不代表所有旧问题都被抹去。" if kind == "settled" else "双方的紧张已有缓和，但分歧仍需之后继续处理。"
        case["history"] = [*case["history"], {"day": state.clock.day, "kind": kind, "mediator_id": actor}][-24:]
        context.emit("CAMPUS_DISPUTE_MEDIATED", text, actor_ids=[actor], target_ids=case["parties"], visibility="private", severity=3,
            knowledge_tags=["social", "dispute", kind], payload={"case_id": case_id, "outcome": kind})
        for party in case["parties"]:
            if are_phone_contacts(state, actor, party):
                append_structured_phone_message(context, actor, party, text, messaging_policy, source="dispute_mediation_receipt")
        return TransactionOutcome(True, True, kind, text, commit=True, payload={"case": next(r for r in dispute_view(state, actor) if r["case_id"] == case_id)})
    return handle


def advance_dispute_mediation(context, messaging_policy):
    state = context.state
    ledger = state.situations.get("campus_disputes")
    if not ledger or ledger["last_auto_phase"] == _tick(state):
        return {"npc_dispute_attempts": 0}
    ledger["last_auto_phase"] = _tick(state)
    handler, attempts, used = make_dispute_handler(messaging_policy), 0, set()
    for case in ledger["cases"].values():
        if case["status"] not in OPEN or case["created_tick"] >= _tick(state) or case["last_attempt_day"] == state.clock.day:
            continue
        candidates = [n for n, person in state.population.items() if n != "player" and n not in case["parties"] and n not in used
            and person.get("personality", {}).get("altruism", 0) >= 55
            and person.get("current_activity", {}).get("status") == "completed"
            and all(are_phone_contacts(state, n, p) and _reachable(state, n, p) and _willing(state, p, n) for p in case["parties"])]
        candidates.sort(key=lambda n: (-state.population[n].get("attributes", {}).get("empathy", 5), n))
        if not candidates:
            continue
        actor = candidates[0]
        first = case["parties"][0]
        append_structured_phone_message(context, first, actor, "我们之前有一次没说清的争执。你认识我们双方，方便分别听听，再帮忙沟通吗？", messaging_policy, source="dispute_help_request")
        base = SimulationCommand(f"npc-mediation:{case['case_id']}:{_tick(state)}", actor, "ASK_NPC_DISPUTE", state.revision,
            issued_day=state.clock.day, issued_phase=state.clock.phase, source="rule")
        for party in case["parties"]:
            handler(context, replace(base, parameters={"case_id": case["case_id"], "npc_id": party}))
        handler(context, replace(base, action_id="MEDIATE_DISPUTE", parameters={"case_id": case["case_id"], "expected_case_revision": case["revision"]}))
        attempts += 1
        used.add(actor)
        if attempts >= 2:
            break
    return {"npc_dispute_attempts": attempts}


def disputes_invariant(state):
    ledger = state.situations.get("campus_disputes")
    if ledger is None:
        return
    try:
        if ledger["schema_version"] != 1 or type(ledger["sequence"]) is not int or ledger["sequence"] != len(ledger["cases"]):
            yield "invalid dispute ledger"
        pairs = set()
        for key, case in ledger["cases"].items():
            parties = case["parties"]
            if (key != case["case_id"] or len(parties) != 2 or len(set(parties)) != 2 or any(n not in state.population or n == "player" for n in parties)
                    or case["status"] not in OPEN | {"settled"} or type(case["revision"]) is not int or case["revision"] < 1
                    or not 0 <= case["last_attempt_day"] <= state.clock.day or not 1 <= case["created_day"] <= state.clock.day
                    or case["location_id"] not in state.places or not case["source_interaction_ids"] or len(case["source_interaction_ids"]) > 12
                    or len(case["history"]) > 24 or any(n not in state.population for n in case["disclosed_to"])):
                yield "invalid dispute case"
            pair = tuple(sorted(parties))
            if case["status"] in OPEN:
                if pair in pairs:
                    yield "duplicate active dispute pair"
                pairs.add(pair)
            for mediator, statements in case["statements"].items():
                if mediator not in state.population or mediator in parties:
                    yield "invalid dispute mediator"
                for participant, row in statements.items():
                    if participant not in parties or type(row["willing"]) is not bool or not 1 <= row["day"] <= state.clock.day or row["case_revision"] != case["revision"]:
                        yield "invalid dispute statement"
    except (KeyError, TypeError, AttributeError, ValueError):
        yield "malformed dispute ledger"
