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

DISPUTE_ACTIONS = ("ASK_NPC_DISPUTE", "REVIEW_DISPUTE_RECORD", "MEDIATE_DISPUTE")
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
    _record_source(context, first, second, interaction["scene_id"], {
        "kind": "confrontation", "source_id": interaction["interaction_id"],
        "summary": "一次未缓和的当面争执留下了待处理的分歧，双方尚未和解。"})


def record_failed_commitment(context, task):
    """Only an actually accepted, now expired surface obligation needs clarification.

    Unclaimed notices, declined invitations and cancelled tasks are not breaches.
    Existing task consequences own relationship penalties; never double-penalize.
    """
    state = context.state
    issuer, assignee = task.get("issuer_id"), task.get("assignee_id")
    if (state.tasks.get(task.get("task_id")) is not task
            or not any(r.get("kind") == "claimed" for r in task.get("history", []))
            or task.get("forum") != "surface" or task.get("state") != "expired"
            or state.clock.day <= task.get("expires_day", state.clock.day)
            or not isinstance(assignee, str) or assignee == issuer or "player" in (issuer, assignee)
            or any(n not in state.population for n in (issuer, assignee))):
        return
    _record_source(context, issuer, assignee, task["scene_id"], {
        "kind": "expired_commitment", "source_id": "task-expired:" + task["task_id"], "task_id": task["task_id"],
        "summary": f"已承接的委托《{task['title']}》超过期限，双方需要核对未完成的原因；逾期不等于故意违约。"})


def _record_source(context, first, second, location, source):
    state, ledger = context.state, _ledger(context.state)
    if any(source["source_id"] in c["source_interaction_ids"] or any(r["source_id"] == source["source_id"] for r in c.get("source_refs", []))
           for c in ledger["cases"].values()):
        return
    parties = sorted((first, second))
    case = next((c for c in ledger["cases"].values() if c["parties"] == parties and c["status"] in OPEN), None)
    if case is None:
        ledger["sequence"] += 1
        case_id = f"campus-dispute:{ledger['sequence']}"
        case = {"case_id": case_id, "parties": parties, "created_day": state.clock.day, "created_tick": _tick(state),
            "status": "open", "revision": 0, "source_interaction_ids": [], "statements": {}, "disclosed_to": [],
            "last_attempt_day": 0, "history": [], "location_id": location}
        ledger["cases"][case_id] = case
    if source["kind"] == "confrontation":
        case["source_interaction_ids"] = [*case["source_interaction_ids"], source["source_id"]][-12:]
    case["source_refs"] = [*case.get("source_refs", []), {**source, "day": state.clock.day, "phase": state.clock.phase}][-12:]
    case["revision"] += 1
    case["status"] = "open"
    case["statements"] = {}  # New disagreement invalidates old willingness.
    case["history"] = [*case["history"], {"day": state.clock.day, "kind": source["kind"], "source": source["source_id"]}][-24:]
    context.emit("CAMPUS_DISPUTE_OPENED", source["summary"],
        actor_ids=parties, scene_id=location, visibility="private", severity=3,
        knowledge_tags=["social", "dispute"], payload={"case_id": case["case_id"], "source_kind": source["kind"], "source_id": source["source_id"],
            **({"source_interaction_id": source["source_id"]} if source["kind"] == "confrontation" else {})})


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
    if willing and any(r["kind"] == "expired_commitment" for r in case.get("source_refs", [])):
        text = "那项已经承接的委托逾期了，事情还没说清。我愿意一起核对公开记录和双方的情况；不能仅凭逾期断定谁在故意失信。"
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
            "record_required": any(r["kind"] == "expired_commitment" for r in case.get("source_refs", [])),
            "record_reviewed": case.get("record_reviews", {}).get(actor_id, {}).get("revision") == case["revision"],
            "source_summary": "；".join(r["summary"] for r in case.get("source_refs", [])[-3:]),
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
        if command.action_id == "REVIEW_DISPUTE_RECORD":
            from simulation.systems.campus_intelligence import create_campus_claim
            if battle_locked(state, actor) or actor_layer(state, actor) != "surface":
                return fail("not_available", "请在表世界且未参战时核对记录。")
            if case["status"] not in OPEN:
                return fail("dispute_closed", "本次分歧已经处理。")
            sources = [r for r in case.get("source_refs", []) if r["kind"] == "expired_commitment"]
            if not sources:
                return fail("no_public_record", "没有可核对的委托逾期记录，请分别听取双方。")
            old = case.get("record_reviews", {}).get(actor, {})
            if old.get("revision") == case["revision"]:
                return TransactionOutcome(True, True, "already_reviewed", "这份版本的公开记录已经核对。",
                    payload={"case": next(r for r in dispute_view(state, actor) if r["case_id"] == case_id)})
            claims = []
            for source in sources:
                task = state.tasks.get(source["task_id"], {})
                if task.get("state") != "expired" or set((task.get("issuer_id"), task.get("assignee_id"))) != set(case["parties"]):
                    return fail("source_changed", "原始委托记录已变化，不能核实。")
            for source in sources:
                task = state.tasks[source["task_id"]]
                claim = create_campus_claim(state, subject_id=task["assignee_id"], predicate="accepted_task_expired",
                    object_id=task["task_id"], summary=source["summary"], secrecy=20, known_by=[actor], evidence_kind="public_record")
                claim["source_context"] = {"location_id": task["scene_id"], "layer": "surface", "source_kind": "public_record",
                    "source_id": task["task_id"], "day": source["day"], "phase": source["phase"]}
                claims.append(claim["claim_id"])
            case.setdefault("record_reviews", {})[actor] = {"revision": case["revision"], "claim_ids": claims}
            context.emit("CAMPUS_DISPUTE_RECORD_REVIEWED", "核对了已承接委托的逾期记录；原因与责任仍需听取双方意见。",
                actor_ids=[actor], visibility="private", knowledge_tags=["dispute", "evidence"], payload={"case_id": case_id, "claim_ids": claims})
            return TransactionOutcome(True, True, "success", "公开委托记录已核对并进入调查笔记；这不是故意违约的证明。", commit=True,
                payload={"case": next(r for r in dispute_view(state, actor) if r["case_id"] == case_id)})
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
        if any(r["kind"] == "expired_commitment" for r in case.get("source_refs", [])) and case.get("record_reviews", {}).get(actor, {}).get("revision") != case["revision"]:
            return fail("public_record_required", "请先核对原委托的公开记录，再讨论处理方式。")
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
            if any(r["kind"] == "expired_commitment" for r in case.get("source_refs", [])):
                text += "原委托仍为逾期，未将工作标为完成，也没有补发任务奖励。"
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
        append_structured_phone_message(context, first, actor, "我们有一件还没说清的分歧。你认识我们双方，方便分别听听并核对已有记录，再帮忙沟通吗？", messaging_policy, source="dispute_help_request")
        base = SimulationCommand(f"npc-mediation:{case['case_id']}:{_tick(state)}", actor, "ASK_NPC_DISPUTE", state.revision,
            issued_day=state.clock.day, issued_phase=state.clock.phase, source="rule")
        for party in case["parties"]:
            handler(context, replace(base, parameters={"case_id": case["case_id"], "npc_id": party}))
        if any(r["kind"] == "expired_commitment" for r in case.get("source_refs", [])):
            handler(context, replace(base, action_id="REVIEW_DISPUTE_RECORD", parameters={"case_id": case["case_id"]}))
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
                    or case["location_id"] not in state.places or not (case["source_interaction_ids"] or case.get("source_refs")) or len(case["source_interaction_ids"]) > 12
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
            sources = case.get("source_refs", [])
            if len(sources) > 12 or len({r["source_id"] for r in sources}) != len(sources):
                yield "invalid dispute sources"
            for source in sources:
                if source["kind"] not in {"confrontation", "expired_commitment"} or not isinstance(source["summary"], str):
                    yield "invalid dispute source"
                if source["kind"] == "expired_commitment":
                    task = state.tasks.get(source["task_id"], {})
                    if task.get("forum") != "surface" or task.get("state") != "expired" or set((task.get("issuer_id"), task.get("assignee_id"))) != set(parties):
                        yield "invalid dispute task source"
            for reviewer, row in case.get("record_reviews", {}).items():
                if reviewer not in state.population or reviewer in parties or not 1 <= row["revision"] <= case["revision"] or any(c not in state.knowledge["claims"] for c in row["claim_ids"]):
                    yield "invalid dispute record review"
    except (KeyError, TypeError, AttributeError, ValueError):
        yield "malformed dispute ledger"
