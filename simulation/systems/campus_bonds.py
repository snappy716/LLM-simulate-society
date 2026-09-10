"""Participant-owned consensual bonds, independent of directional affinity.

No exclusive-partner cap. Neither chat text nor a completed date is consent.
An optional ledger keeps old saves readable without a migration or model call.
"""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

from simulation.systems.campus_messaging import are_phone_contacts, append_structured_phone_message
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems.transactions import TransactionOutcome

ACTIONS = ("PROPOSE_CAMPUS_BOND", "ACCEPT_CAMPUS_BOND", "DECLINE_CAMPUS_BOND",
           "CANCEL_CAMPUS_BOND", "END_CAMPUS_BOND")
KINDS = {"friendship": "好友", "romance": "恋人"}
STATUSES = {"pending", "active", "declined", "cancelled", "ended", "expired"}


def records(state):
    return state.situations.get("campus_bonds", {}).get("records", {})


def pair(row):
    return (row["proposer_id"], row["recipient_id"])


def shared_experiences(state, first, second, kind=None):
    from simulation.systems.campus_outings import records as outings, participants
    return [r for r in outings(state).values() if r["status"] == "completed" and r["receipt"]
        and set(participants(r)) == {first, second} and (kind is None or r["kind"] == kind)]


def willing(state, actor, other, kind):
    """Conservative first-pass NPC response, not a model-generated fact.

    Uses only the actor's own attitude and shared experiences. Personality changes
    readiness; another existing partner is NOT a veto. Player choice is explicit.
    """
    person = state.population[actor]
    r = {**DEFAULT_RELATIONSHIP, **state.relationships.get(actor, {}).get(other, {})}
    if r["suspicion"] >= 35 or r["conflict"] >= 25 or r["fear"] >= 40:
        return False
    if max(person.get("needs", {}).get(k, 0) for k in ("rest", "food", "safety")) >= 90:
        return False
    caution = (person.get("personality", {}).get("emotional_sensitivity", 50) - 50) / 10
    if kind == "romance":
        return (r["trust"] >= 65 + caution and r["closeness"] >= 55 + caution
            and r["familiarity"] >= 40 and len(shared_experiences(state, actor, other, "date")) >= 2)
    return (r["trust"] >= 55 + caution and r["closeness"] >= 25
        and r["familiarity"] >= 20 and bool(shared_experiences(state, actor, other)))


def _transition(context, row, status, sender, policy, reason):
    row.update(status=status, revision=row["revision"] + 1, reason=reason,
        updated_day=context.state.clock.day, updated_phase=context.state.clock.phase)
    row["history"].append({"status": status, "actor_id": sender, "day": row["updated_day"],
        "phase": row["updated_phase"], "reason": reason})
    other = next(who for who in pair(row) if who != sender)
    message = append_structured_phone_message(context, sender, other, reason, policy, source="campus_bond")
    row["message_ids"].append(message["message_id"])
    context.emit("CAMPUS_BOND_UPDATED", reason, actor_ids=pair(row), visibility="private",
        knowledge_tags=["relationship"], payload={"bond_id": row["bond_id"], "status": status, "kind": row["kind"]})


def make_bond_handler(policy):
    def handle(context, command):
        state, actor, p = context.state, command.actor_id, command.parameters
        def fail(code, message): return TransactionOutcome(False, False, code, message)
        if actor not in state.population or (command.source == "player" and actor != "player"):
            return fail("actor_not_authorized", "不能代替他人确认关系。")
        if (command.issued_day, command.issued_phase) != (state.clock.day, state.clock.phase):
            return fail("command_clock_mismatch", "时段已变化，请刷新。")
        if command.action_id == "PROPOSE_CAMPUS_BOND":
            other, kind = p.get("target_id"), p.get("kind")
            if not isinstance(other, str) or other == actor or other not in state.population:
                return fail("invalid_recipient", "请选择另一位已有联系人。")
            if not isinstance(kind, str) or kind not in KINDS or not are_phone_contacts(state, actor, other):
                return fail("contact_required", "需要已有联系方式，并明确希望建立的关系。")
            previous = [r for r in records(state).values() if set(pair(r)) == {actor, other} and r["kind"] == kind]
            if any(r["status"] in {"pending", "active"} for r in previous):
                return fail("bond_already_live", "这段关系已有待回应请求或已确认，无需重复。")
            if any(state.clock.day - r["updated_day"] < 3 for r in previous):
                return fail("bond_pair_cooldown", "请给彼此三天空间，不反复催促确认关系。")
            if actor != "player" and not willing(state, actor, other, kind):
                return fail("bond_not_ready", "本人暂时不想推进这段关系。")
            ledger = state.situations.setdefault("campus_bonds", {"schema_version": 1, "records": {}})
            key = f"bond:{len(ledger['records']) + 1}"
            row = {"bond_id": key, "proposer_id": actor, "recipient_id": other, "kind": kind,
                "status": "pending", "revision": 0, "created_day": state.clock.day,
                "created_phase": state.clock.phase, "history": [], "message_ids": []}
            ledger["records"][key] = row
            reason = ("我想和你正式成为恋人。这里不约定排他关系，也不会改变任何已有关系；你可以拒绝，任何一方都可以结束。"
                if kind == "romance" else "我想和你互相确认成为好友。你可以拒绝，不会因此受到惩罚。")
            _transition(context, row, "pending", actor, policy, reason)
            if other != "player":
                accepted = willing(state, other, actor, kind)
                _transition(context, row, "active" if accepted else "declined", other, policy,
                    f"我愿意和你确认{KINDS[kind]}关系；保留各自选择与结束关系的权利。" if accepted else "谢谢你告诉我，但我目前不想确认这段关系。")
        else:
            key = p.get("bond_id")
            row = records(state).get(key) if isinstance(key, str) else None
            if not row or actor not in pair(row):
                return fail("bond_not_visible", "不能操作他人的私人关系。")
            revision = p.get("expected_revision")
            if type(revision) not in (int, float) or revision != row["revision"]:
                return fail("bond_revision_conflict", "关系已变化，请刷新。")
            if command.action_id in ("ACCEPT_CAMPUS_BOND", "DECLINE_CAMPUS_BOND"):
                if actor != row["recipient_id"] or row["status"] != "pending":
                    return fail("recipient_required", "只有收到请求的人可以回应待确认关系。")
                accept = command.action_id == "ACCEPT_CAMPUS_BOND"
                if accept and actor != "player" and not willing(state, actor, row["proposer_id"], row["kind"]):
                    return fail("bond_not_ready", "本人目前不愿确认这段关系。")
                _transition(context, row, "active" if accept else "declined", actor, policy,
                    f"双方确认成为{KINDS[row['kind']]}；这不自动改变其他关系。" if accept else "已婉拒，不扣好感或行动。")
            elif command.action_id in ("CANCEL_CAMPUS_BOND", "END_CAMPUS_BOND"):
                ending = command.action_id == "END_CAMPUS_BOND"
                if row["status"] != ("active" if ending else "pending"):
                    return fail("bond_status_conflict", "这段关系当前不支持此操作。")
                _transition(context, row, "ended" if ending else "cancelled", actor, policy,
                    "已结束这段关系；真实共同经历保留，不影响其他关系，也不惩罚退出。" if ending else "已撤回请求，不再等待回应。")
            else:
                return fail("unsupported_bond_action", "未知关系行动。")
        return TransactionOutcome(True, True, "bond_updated", row["reason"], commit=True,
            payload={"bond": deepcopy(row)})
    return handle


def bond_view(state, actor="player"):
    rows = []
    for original in records(state).values():
        if actor not in pair(original): continue
        row = deepcopy(original)
        other = next(who for who in pair(row) if who != actor)
        row.update(partner_id=other, partner_name=state.population[other].get("display_name", other),
            can_reply=row["status"] == "pending" and row["recipient_id"] == actor,
            can_cancel=row["status"] == "pending", can_end=row["status"] == "active")
        rows.append(row)
    return {"records": rows, "note": "关系需双方确认；不限制正式伴侣数量。不会显示他人的私人关系。聊天与确认免费，相处活动仍消耗主要行动。"}


def own_bond_context(state, actor):
    # Retain the latest refusal/end as well: an old romantic memory must not
    # silently become the only context once the last active bond has ended.
    latest = {}
    for row in sorted(records(state).values(), key=lambda r: r["created_day"]):
        if actor not in pair(row): continue
        other = next(who for who in pair(row) if who != actor)
        latest[(other, row["kind"])] = {"other_id": other, "kind": row["kind"], "status": row["status"]}
    return [latest[key] for key in sorted(latest)]


def advance_bonds(context, handler, policy):
    """Once at dawn, offline NPC initiative; no intraday or additional LLM call.

    Date choices remain in the existing daily candidate planner. This first-pass
    formal relationship initiative is explicitly rule-driven, not model evidence.
    """
    state = context.state
    if state.clock.phase != "morning" or state.cognition.get("bonds_prepared_day") == state.clock.day:
        return
    state.cognition["bonds_prepared_day"] = state.clock.day
    for row in list(records(state).values()):
        if row["status"] == "pending" and state.clock.day - row["created_day"] >= 3:
            _transition(context, row, "expired", row["proposer_id"], policy, "三天未获回应，这次请求已结束；不惩罚未回应。")
    for actor in sorted(state.population):
        if actor == "player": continue
        # Stable, distinct initiative windows. No dependence on frame speed.
        person = state.population[actor]
        initiative = 0.15 + person.get("personality", {}).get("extraversion", 50) / 500
        sample = int.from_bytes(sha256(f"bond:{actor}:{state.clock.day}".encode()).digest()[:4], "big") / 2**32
        if sample >= initiative: continue
        contacts = sorted(state.relationships.get(actor, {}), key=lambda who: (-state.relationships[actor][who].get("closeness", 0), who))
        for other in contacts:
            if other not in state.population or not are_phone_contacts(state, actor, other): continue
            kind = "romance" if willing(state, actor, other, "romance") else "friendship"
            if not willing(state, actor, other, kind): continue
            command = replace(context.command, command_id=f"daily-bond:{state.clock.day}:{actor}:{other}",
                actor_id=actor, action_id="PROPOSE_CAMPUS_BOND", source="rule",
                issued_day=state.clock.day, issued_phase=state.clock.phase,
                parameters={"target_id": other, "kind": kind})
            if handler(context, command).success: break


def bonds_invariant(state):
    ledger = state.situations.get("campus_bonds")
    if ledger is None: return []
    try:
        if type(ledger["schema_version"]) is not int or ledger["schema_version"] != 1:
            return ["invalid bond ledger version"]
        live = set()
        phases = ("morning", "afternoon", "evening", "late_night")
        transitions = {"pending": {"active", "declined", "cancelled", "expired"}, "active": {"ended"}}
        for key, row in ledger["records"].items():
            if (key != row["bond_id"] or len(set(pair(row))) != 2 or not set(pair(row)) <= state.population.keys()
                    or row["kind"] not in KINDS or row["status"] not in STATUSES
                    or type(row["revision"]) is not int or row["revision"] < 1
                    or any(type(row[k]) is not int for k in ("created_day", "updated_day"))
                    or not 1 <= row["created_day"] <= row["updated_day"] <= state.clock.day
                    or row["created_phase"] not in phases or row["updated_phase"] not in phases
                    or len(row["history"]) != row["revision"] or len(row["message_ids"]) != row["revision"]
                    or len(set(row["message_ids"])) != len(row["message_ids"])
                    or row["history"][-1]["status"] != row["status"]):
                return ["invalid bond record"]
            initial = row["history"][0]
            final = row["history"][-1]
            if (initial["status"] != "pending" or initial["actor_id"] != row["proposer_id"]
                    or (initial["day"], initial["phase"]) != (row["created_day"], row["created_phase"])
                    or (final["day"], final["phase"], final["reason"]) != (row["updated_day"], row["updated_phase"], row["reason"])):
                return ["inconsistent bond history"]
            prior = None
            prior_tick = 0
            for event in row["history"]:
                if type(event["day"]) is not int or event["phase"] not in phases or event["day"] < 1:
                    return ["invalid bond history clock"]
                tick = event["day"] * 4 + phases.index(event["phase"])
                if tick < prior_tick or tick > state.clock.day * 4 + phases.index(state.clock.phase):
                    return ["invalid bond history chronology"]
                if prior and event["status"] not in transitions.get(prior, set()):
                    return ["invalid bond transition"]
                if event["status"] in {"active", "declined"} and event["actor_id"] != row["recipient_id"]:
                    return ["bond requires recipient response"]
                prior, prior_tick = event["status"], tick
            if row["status"] in {"pending", "active"}:
                identity = (*sorted(pair(row)), row["kind"])
                if identity in live: return ["duplicate live bond pair"]
                live.add(identity)
            if row["status"] == "active" and row["history"][-1]["actor_id"] != row["recipient_id"]:
                return ["bond requires recipient consent"]
            if any(h["actor_id"] not in pair(row) for h in row["history"]):
                return ["outsider in bond history"]
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return ["malformed bond ledger"]
    return []
