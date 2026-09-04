"""Persistent, location-independent campus phone conversations."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping

from simulation.actions.commands import SimulationCommand
from simulation.domain.world_state import WorldState
from simulation.systems.campus_intelligence import (
    CampusIntelligencePolicy,
    disclosable_known_claims,
    share_known_claim,
    share_specific_known_claim,
)
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP, adjust_relationship
from simulation.systems.campus_tasks import phase_index
from simulation.systems.transactions import TransactionOutcome


CAMPUS_MESSAGING_SCHEMA_VERSION = 1
PHONE_ACTION_IDS = {"ADD_PHONE_CONTACT", "SEND_PHONE_MESSAGE", "MARK_PHONE_THREAD_READ"}


@dataclass(frozen=True)
class CampusMessagingPolicy:
    max_text_length: int
    max_messages_per_thread: int
    max_autonomous_conversations_per_phase: int
    pair_cooldown_phases: int
    autonomous_social_need_threshold: int
    player_auto_reply: bool

    def __post_init__(self) -> None:
        positive = (
            self.max_text_length,
            self.max_messages_per_thread,
            self.max_autonomous_conversations_per_phase,
            self.pair_cooldown_phases,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in positive):
            raise ValueError("campus messaging limits must be positive integers")
        if not 0 <= self.autonomous_social_need_threshold <= 100:
            raise ValueError("autonomous social need threshold must be between zero and one hundred")


def load_campus_messaging_policy(registry) -> CampusMessagingPolicy:
    payload = registry.get("configuration", "campus_messaging")
    return CampusMessagingPolicy(
        max_text_length=int(payload.get("max_text_length", 240)),
        max_messages_per_thread=int(payload.get("max_messages_per_thread", 80)),
        max_autonomous_conversations_per_phase=int(
            payload.get("max_autonomous_conversations_per_phase", 3)
        ),
        pair_cooldown_phases=int(payload.get("pair_cooldown_phases", 1)),
        autonomous_social_need_threshold=int(
            payload.get("autonomous_social_need_threshold", 68)
        ),
        player_auto_reply=bool(payload.get("player_auto_reply", True)),
    )


def install_campus_messaging(state: WorldState, policy: CampusMessagingPolicy) -> None:
    if not state.cognition:
        raise ValueError("campus cognition must be installed before messaging")
    if "messaging" in state.cognition:
        raise ValueError("campus messaging is already installed")
    contacts_by_actor = {actor_id: [] for actor_id in state.population}

    def connect(first_id: str, second_id: str) -> None:
        if first_id == second_id:
            return
        if second_id not in contacts_by_actor[first_id]:
            contacts_by_actor[first_id].append(second_id)
        if first_id not in contacts_by_actor[second_id]:
            contacts_by_actor[second_id].append(first_id)

    # Persistent NPCs begin with a small social graph rather than knowing the
    # entire campus. Adjacent peers in each college and club exchange details.
    for field_name in ("college_id",):
        groups: Dict[str, list[str]] = {}
        for actor_id, actor in state.population.items():
            if actor_id == "player" or not isinstance(actor, dict):
                continue
            group_id = str(actor.get(field_name, ""))
            if group_id:
                groups.setdefault(group_id, []).append(actor_id)
        for member_ids in groups.values():
            members = sorted(member_ids)
            for index in range(len(members) - 1):
                connect(members[index], members[index + 1])
    club_groups: Dict[str, list[str]] = {}
    for actor_id, actor in state.population.items():
        if actor_id == "player" or not isinstance(actor, dict):
            continue
        for club_id in actor.get("club_ids", ()):
            club_groups.setdefault(str(club_id), []).append(actor_id)
    for member_ids in club_groups.values():
        members = sorted(set(member_ids))
        for index in range(len(members) - 1):
            connect(members[index], members[index + 1])

    # The demo begins after registration, so the player already knows one
    # orientation peer, one student assistant, and one psychology staff member.
    player_candidates = [
        sorted(
            actor_id for actor_id, actor in state.population.items()
            if actor_id != "player" and isinstance(actor, dict) and predicate(actor)
        )
        for predicate in (
            lambda actor: actor.get("college_id") == "psychology" and actor.get("occupation_id") == "undergraduate",
            lambda actor: actor.get("college_id") == "psychology" and actor.get("occupation_id") == "student_assistant",
            lambda actor: actor.get("college_id") == "psychology" and actor.get("role_kind") != "student",
        )
    ]
    for candidates in player_candidates:
        if candidates:
            connect("player", candidates[0])
    for actor_contacts in contacts_by_actor.values():
        actor_contacts.sort()

    state.cognition["messaging"] = {
        "schema_version": CAMPUS_MESSAGING_SCHEMA_VERSION,
        "policy": {
            "max_text_length": policy.max_text_length,
            "max_messages_per_thread": policy.max_messages_per_thread,
            "max_autonomous_conversations_per_phase": policy.max_autonomous_conversations_per_phase,
            "pair_cooldown_phases": policy.pair_cooldown_phases,
            "autonomous_social_need_threshold": policy.autonomous_social_need_threshold,
            "player_auto_reply": policy.player_auto_reply,
        },
        "message_sequence": 0,
        "contacts_by_actor": contacts_by_actor,
        "initial_player_contact_ids": list(contacts_by_actor["player"]),
        "threads": {},
        "messages": {},
        "pair_last_autonomous_phase": {},
    }


def _pair_key(first_id: str, second_id: str) -> str:
    return "|".join(sorted((first_id, second_id)))


def _thread_id(first_id: str, second_id: str) -> str:
    return f"phone_thread:{_pair_key(first_id, second_id)}"


def _actor_name(state: WorldState, actor_id: str) -> str:
    actor = state.population.get(actor_id, {})
    return str(actor.get("display_name", actor_id)) if isinstance(actor, dict) else actor_id


def _region_id(state: WorldState, location_id: Any) -> str:
    location = state.places.get(str(location_id), {})
    if not isinstance(location, dict):
        return ""
    if location.get("node_type") == "region":
        return str(location_id)
    return str(location.get("region_id", ""))


def _ensure_thread(state: WorldState, first_id: str, second_id: str) -> Dict[str, Any]:
    messaging = state.cognition["messaging"]
    thread_id = _thread_id(first_id, second_id)
    thread = messaging["threads"].get(thread_id)
    if isinstance(thread, dict):
        return thread
    participants = sorted((first_id, second_id))
    thread = {
        "thread_id": thread_id,
        "participant_ids": participants,
        "message_ids": [],
        "unread_by_actor": {actor_id: 0 for actor_id in participants},
        "created_day": state.clock.day,
        "created_phase": state.clock.phase,
        "last_message_day": state.clock.day,
        "last_message_phase": state.clock.phase,
        "last_message_id": None,
    }
    messaging["threads"][thread_id] = thread
    return thread


def _are_contacts(state: WorldState, first_id: str, second_id: str) -> bool:
    contacts = state.cognition["messaging"].get("contacts_by_actor", {})
    return (
        second_id in contacts.get(first_id, ())
        and first_id in contacts.get(second_id, ())
    )


def _add_contact(state: WorldState, first_id: str, second_id: str) -> None:
    contacts = state.cognition["messaging"]["contacts_by_actor"]
    for owner_id, target_id in ((first_id, second_id), (second_id, first_id)):
        owner_contacts = contacts.setdefault(owner_id, [])
        if target_id not in owner_contacts:
            owner_contacts.append(target_id)
            owner_contacts.sort()


def _append_message(
    state: WorldState,
    sender_id: str,
    receiver_id: str,
    text: str,
    policy: CampusMessagingPolicy,
    *,
    source: str,
    reply_to_message_id: str | None = None,
    shared_claim_id: str | None = None,
) -> Dict[str, Any]:
    messaging = state.cognition["messaging"]
    thread = _ensure_thread(state, sender_id, receiver_id)
    messaging["message_sequence"] += 1
    message_id = f"phone_message:{messaging['message_sequence']:08d}"
    message = {
        "message_id": message_id,
        "thread_id": thread["thread_id"],
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "day": state.clock.day,
        "phase": state.clock.phase,
        "minute": state.clock.minute,
        "text": text[:policy.max_text_length],
        "source": source,
        "reply_to_message_id": reply_to_message_id,
        "shared_claim_id": shared_claim_id,
    }
    messaging["messages"][message_id] = message
    thread["message_ids"].append(message_id)
    thread["unread_by_actor"][receiver_id] = int(
        thread["unread_by_actor"].get(receiver_id, 0)
    ) + 1
    thread["last_message_day"] = state.clock.day
    thread["last_message_phase"] = state.clock.phase
    thread["last_message_id"] = message_id
    while len(thread["message_ids"]) > policy.max_messages_per_thread:
        removed_id = thread["message_ids"].pop(0)
        messaging["messages"].pop(removed_id, None)
        for actor_id in thread["participant_ids"]:
            thread["unread_by_actor"][actor_id] = min(
                int(thread["unread_by_actor"].get(actor_id, 0)),
                len(thread["message_ids"]),
            )
    return message


def _emit_message_event(context, message: Mapping[str, Any]) -> None:
    sender_id = str(message["sender_id"])
    receiver_id = str(message["receiver_id"])
    context.emit(
        "PHONE_MESSAGE_SENT",
        f"{_actor_name(context.state, sender_id)}向{_actor_name(context.state, receiver_id)}发送了一条手机消息。",
        actor_ids=[sender_id],
        target_ids=[receiver_id],
        payload=deepcopy(dict(message)),
        visibility="private",
        severity=1,
        knowledge_tags=["phone", "message", "social"],
    )


def _relation(state: WorldState, owner_id: str, target_id: str) -> Mapping[str, int]:
    value = state.relationships.get(owner_id, {}).get(target_id)
    return value if isinstance(value, dict) else DEFAULT_RELATIONSHIP


def _rule_reply(state: WorldState, sender_id: str, receiver_id: str) -> str:
    """Choose safe wording without inventing a world fact."""
    relation = _relation(state, sender_id, receiver_id)
    sender = state.population[sender_id]
    if int(relation.get("suspicion", 0)) >= 55 or int(relation.get("conflict", 0)) >= 55:
        return "消息看到了。如果有必要，我们之后再谈。"
    hooks = state.cognition.get("interactions", {}).get("hooks", ())
    if any(
        hook.get("state") in {"open", "task_posted"}
        and {hook.get("actor_id"), hook.get("target_id")} == {sender_id, receiver_id}
        for hook in hooks if isinstance(hook, dict)
    ):
        return "收到。之前说的那件事我还记得，我们保持联系。"
    if int(sender.get("needs", {}).get("commitment_pressure", 0)) >= 70:
        return "收到，我现在还有些事情要处理，稍后有空再细说。"
    if int(relation.get("closeness", 0)) >= 45:
        return "看到啦。你愿意联系我，我很高兴。"
    return "收到消息了，有需要可以继续告诉我。"


def make_campus_messaging_handler(
    policy: CampusMessagingPolicy,
    intelligence_policy: CampusIntelligencePolicy | None = None,
    cognition_runtime=None,
):
    def handle(context, command: SimulationCommand) -> TransactionOutcome:
        if command.actor_id not in context.state.population:
            return TransactionOutcome(False, False, "unknown_actor", "发送者不存在。")
        target_id = str(command.parameters.get("target_id", ""))
        if target_id not in context.state.population or target_id == command.actor_id:
            return TransactionOutcome(False, False, "invalid_message_target", "联系人不存在。")
        if command.action_id == "ADD_PHONE_CONTACT":
            if command.actor_id != "player":
                return TransactionOutcome(False, False, "player_only", "目前只有玩家可以主动添加联系人。")
            actor = context.state.population[command.actor_id]
            target = context.state.population[target_id]
            if _region_id(context.state, actor.get("current_location_id")) != _region_id(
                context.state, target.get("current_location_id")
            ):
                return TransactionOutcome(False, False, "contact_not_met", "需要先在同一校园区域与对方见面。")
            if _are_contacts(context.state, command.actor_id, target_id):
                return TransactionOutcome(False, True, "already_contact", "对方已经在联系人中。")
            _add_contact(context.state, command.actor_id, target_id)
            adjust_relationship(context.state, command.actor_id, target_id, {"familiarity": 1})
            adjust_relationship(context.state, target_id, command.actor_id, {"familiarity": 1})
            context.emit(
                "PHONE_CONTACT_ADDED",
                f"{_actor_name(context.state, command.actor_id)}与{_actor_name(context.state, target_id)}交换了联系方式。",
                actor_ids=[command.actor_id], target_ids=[target_id],
                visibility="private", severity=1,
                knowledge_tags=["phone", "contact", "social"],
            )
            return TransactionOutcome(
                True, True, "success", "已交换联系方式。", commit=True,
                payload={"target_id": target_id, "action_class": "free"},
            )
        if not _are_contacts(context.state, command.actor_id, target_id):
            return TransactionOutcome(False, False, "not_a_contact", "需要先见面并交换联系方式。")
        thread = _ensure_thread(context.state, command.actor_id, target_id)
        if command.action_id == "MARK_PHONE_THREAD_READ":
            unread = int(thread["unread_by_actor"].get(command.actor_id, 0))
            if unread == 0:
                return TransactionOutcome(False, True, "already_read", "当前没有未读消息。")
            thread["unread_by_actor"][command.actor_id] = 0
            return TransactionOutcome(
                True, True, "success", "消息已读。", commit=True,
                payload={"thread_id": thread["thread_id"], "read_count": unread},
            )
        if command.action_id != "SEND_PHONE_MESSAGE":
            return TransactionOutcome(False, False, "unsupported_message_action", "不支持的通讯操作。")
        text = str(command.parameters.get("text", "")).strip()
        if not text:
            return TransactionOutcome(False, False, "empty_message", "消息内容不能为空。")
        if len(text) > policy.max_text_length:
            return TransactionOutcome(False, False, "message_too_long", "消息不能超过 240 个字符。")
        sent = _append_message(
            context.state, command.actor_id, target_id, text, policy,
            source=command.source,
        )
        thread["unread_by_actor"][command.actor_id] = 0
        _emit_message_event(context, sent)
        replies: list[Dict[str, Any]] = []
        information_shares: list[Dict[str, Any]] = []
        if command.actor_id == "player" and target_id != "player" and policy.player_auto_reply:
            reply_text = _rule_reply(context.state, target_id, "player")
            reply_source = "rule"
            fact_ids_used: list[str] = []
            if cognition_runtime is not None and intelligence_policy is not None:
                allowed_facts = disclosable_known_claims(
                    context.state, target_id, "player", intelligence_policy
                )
                dialogue = cognition_runtime.compose_phone_reply(
                    context.state,
                    target_id,
                    "player",
                    text,
                    [
                        context.state.cognition["messaging"]["messages"][message_id]
                        for message_id in thread["message_ids"][:-1]
                        if message_id in context.state.cognition["messaging"]["messages"]
                    ],
                    allowed_facts,
                )
                if dialogue is not None:
                    reply_text = str(dialogue["utterance"])
                    reply_source = "llm"
                    fact_ids_used = list(dialogue.get("fact_ids_used", ()))
                    for claim_id in fact_ids_used:
                        receipt = share_specific_known_claim(
                            context.state,
                            sender_id=target_id,
                            receiver_id="player",
                            claim_id=claim_id,
                            interaction_id=sent["message_id"],
                            intent_id="phone_reply",
                            policy=intelligence_policy,
                            acquisition_method="phone_statement",
                        )
                        if receipt is not None:
                            information_shares.append(receipt)
            reply = _append_message(
                context.state, target_id, "player",
                reply_text, policy,
                source=reply_source, reply_to_message_id=sent["message_id"],
                shared_claim_id=fact_ids_used[0] if fact_ids_used else None,
            )
            adjust_relationship(context.state, target_id, "player", {"familiarity": 1})
            adjust_relationship(context.state, "player", target_id, {"familiarity": 1})
            _emit_message_event(context, reply)
            for receipt in information_shares:
                context.emit(
                    "NPC_INFORMATION_SHARED",
                    str(receipt["dialogue_summary"]),
                    actor_ids=[target_id], target_ids=["player"],
                    payload=deepcopy(receipt), visibility="private", severity=2,
                    knowledge_tags=["phone", "dialogue", "information"],
                    correlation_id=sent["message_id"],
                )
            replies.append(reply)
        return TransactionOutcome(
            True, True, "success", "消息已发送。", commit=True,
            payload={
                "thread_id": thread["thread_id"],
                "sent_message": deepcopy(sent),
                "reply_messages": deepcopy(replies),
                "information_shares": deepcopy(information_shares),
                "action_class": "free",
            },
        )

    return handle


def _shared_clubs(first: Mapping[str, Any], second: Mapping[str, Any]) -> list[str]:
    return sorted(set(first.get("club_ids", ())) & set(second.get("club_ids", ())))


def _pair_score(state: WorldState, sender_id: str, receiver_id: str, rng) -> float:
    sender = state.population[sender_id]
    receiver = state.population[receiver_id]
    relation = _relation(state, sender_id, receiver_id)
    hooks = state.cognition.get("interactions", {}).get("hooks", ())
    has_hook = any(
        isinstance(hook, dict) and hook.get("state") in {"open", "task_posted"}
        and {hook.get("actor_id"), hook.get("target_id")} == {sender_id, receiver_id}
        for hook in hooks
    )
    return (
        int(sender.get("needs", {}).get("social", 0)) * 0.35
        + int(sender.get("personality", {}).get("extraversion", 50)) * 0.12
        + int(relation.get("familiarity", 0)) * 0.18
        + int(relation.get("trust", 50)) * 0.08
        - int(relation.get("conflict", 0)) * 0.2
        + (30 if has_hook else 0)
        + (14 if _shared_clubs(sender, receiver) else 0)
        + (8 if sender.get("college_id") == receiver.get("college_id") else 0)
        + rng.uniform(-5.0, 5.0)
    )


def _autonomous_text(state: WorldState, sender_id: str, receiver_id: str) -> str:
    sender = state.population[sender_id]
    receiver = state.population[receiver_id]
    hooks = state.cognition.get("interactions", {}).get("hooks", ())
    if any(
        isinstance(hook, dict) and hook.get("state") in {"open", "task_posted"}
        and {hook.get("actor_id"), hook.get("target_id")} == {sender_id, receiver_id}
        for hook in hooks
    ):
        return "关于我们之前说的那件事，你现在方便保持联系吗？"
    shared = _shared_clubs(sender, receiver)
    if shared:
        return "最近社团的安排你有关注吗？之后有空可以一起讨论。"
    if sender.get("college_id") == receiver.get("college_id"):
        return "今天学院里的安排还顺利吗？有空聊聊近况。"
    return "你今天还好吗？我刚好想找个人聊聊。"


def advance_campus_phone_messages(
    context,
    policy: CampusMessagingPolicy,
    intelligence_policy: CampusIntelligencePolicy,
) -> Dict[str, Any]:
    """Run a few justified remote NPC conversations after phase activities."""
    state = context.state
    messaging = state.cognition["messaging"]
    now = phase_index(state.clock.day, state.clock.phase)
    rng = context.rng.stream("campus_phone_messaging")
    npc_ids = [
        actor_id for actor_id, actor in sorted(state.population.items())
        if actor_id != "player" and isinstance(actor, dict)
    ]
    candidates: list[tuple[float, str, str]] = []
    for sender_id in npc_ids:
        sender = state.population[sender_id]
        has_open_hook = any(
            isinstance(hook, dict) and hook.get("state") in {"open", "task_posted"}
            and sender_id in {hook.get("actor_id"), hook.get("target_id")}
            for hook in state.cognition.get("interactions", {}).get("hooks", ())
        )
        if (
            int(sender.get("needs", {}).get("social", 0))
            < policy.autonomous_social_need_threshold
            and not has_open_hook
        ):
            continue
        for receiver_id in npc_ids:
            if receiver_id <= sender_id:
                continue
            receiver = state.population[receiver_id]
            if not _are_contacts(state, sender_id, receiver_id):
                continue
            if sender.get("current_location_id") == receiver.get("current_location_id"):
                continue
            pair_key = _pair_key(sender_id, receiver_id)
            last = messaging["pair_last_autonomous_phase"].get(pair_key)
            if isinstance(last, int) and now - last <= policy.pair_cooldown_phases:
                continue
            candidates.append((_pair_score(state, sender_id, receiver_id, rng), sender_id, receiver_id))
    selected: list[tuple[str, str]] = []
    used: set[str] = set()
    for _, first_id, second_id in sorted(candidates, reverse=True):
        if first_id in used or second_id in used:
            continue
        sender_id, receiver_id = (
            (first_id, second_id)
            if int(state.population[first_id].get("needs", {}).get("social", 0))
            >= int(state.population[second_id].get("needs", {}).get("social", 0))
            else (second_id, first_id)
        )
        selected.append((sender_id, receiver_id))
        used.update((sender_id, receiver_id))
        if len(selected) >= policy.max_autonomous_conversations_per_phase:
            break
    shared_count = 0
    for sender_id, receiver_id in selected:
        pair_key = _pair_key(sender_id, receiver_id)
        messaging["pair_last_autonomous_phase"][pair_key] = now
        interaction_id = f"phone_exchange:{now}:{pair_key}"
        information = share_known_claim(
            state,
            sender_id=sender_id,
            receiver_id=receiver_id,
            interaction_id=interaction_id,
            intent_id="exchange_ideas",
            policy=intelligence_policy,
            rng=context.rng.stream("campus_phone_information"),
        )
        text = (
            str(information["dialogue_summary"]).split("：“", 1)[-1].rstrip("”")
            if information else _autonomous_text(state, sender_id, receiver_id)
        )
        sent = _append_message(
            state, sender_id, receiver_id, text, policy, source="rule",
            shared_claim_id=str(information["claim_id"]) if information else None,
        )
        _emit_message_event(context, sent)
        reply = _append_message(
            state, receiver_id, sender_id,
            _rule_reply(state, receiver_id, sender_id), policy,
            source="rule", reply_to_message_id=sent["message_id"],
        )
        _emit_message_event(context, reply)
        adjust_relationship(state, sender_id, receiver_id, {"familiarity": 1})
        adjust_relationship(state, receiver_id, sender_id, {"familiarity": 1})
        sender = state.population[sender_id]
        receiver = state.population[receiver_id]
        sender["needs"]["social"] = max(0, int(sender["needs"].get("social", 0)) - 5)
        receiver["needs"]["social"] = max(0, int(receiver["needs"].get("social", 0)) - 2)
        shared_count += int(information is not None)
    return {
        "phone_conversation_count": len(selected),
        "phone_message_count": len(selected) * 2,
        "phone_information_share_count": shared_count,
    }


def campus_messaging_invariant(state: WorldState) -> Iterable[str]:
    aggregate = state.cognition.get("messaging")
    if aggregate is None:
        return ()
    errors: list[str] = []
    if not isinstance(aggregate, dict):
        return ["campus messaging must be a mapping"]
    if aggregate.get("schema_version") != CAMPUS_MESSAGING_SCHEMA_VERSION:
        errors.append("campus messaging schema_version is unsupported")
    threads = aggregate.get("threads")
    messages = aggregate.get("messages")
    contacts = aggregate.get("contacts_by_actor")
    if not isinstance(threads, dict) or not isinstance(messages, dict) or not isinstance(contacts, dict):
        return [*errors, "campus messaging contacts, threads, and messages must be mappings"]
    if set(contacts) != set(state.population):
        errors.append("campus messaging contact owners do not match population")
    for actor_id, actor_contacts in contacts.items():
        if not isinstance(actor_contacts, list) or len(actor_contacts) != len(set(actor_contacts)):
            errors.append(f"phone contacts for {actor_id} are invalid")
            continue
        for target_id in actor_contacts:
            if target_id not in state.population or actor_id not in contacts.get(target_id, ()):
                errors.append(f"phone contact {actor_id} -> {target_id} is invalid or not reciprocal")
    max_length = int(aggregate.get("policy", {}).get("max_text_length", 240))
    max_messages = int(aggregate.get("policy", {}).get("max_messages_per_thread", 80))
    for thread_id, thread in threads.items():
        if not isinstance(thread, dict) or thread.get("thread_id") != thread_id:
            errors.append(f"invalid phone thread {thread_id}")
            continue
        participants = thread.get("participant_ids")
        if (
            not isinstance(participants, list) or len(participants) != 2
            or len(set(participants)) != 2
            or any(actor_id not in state.population for actor_id in participants)
        ):
            errors.append(f"phone thread {thread_id} has invalid participants")
            continue
        if not _are_contacts(state, participants[0], participants[1]):
            errors.append(f"phone thread {thread_id} participants are not contacts")
        message_ids = thread.get("message_ids")
        unread = thread.get("unread_by_actor")
        if not isinstance(message_ids, list) or len(message_ids) > max_messages:
            errors.append(f"phone thread {thread_id} has invalid message index")
            continue
        if not isinstance(unread, dict) or set(unread) != set(participants):
            errors.append(f"phone thread {thread_id} has invalid unread counters")
        elif any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in unread.values()
        ):
            errors.append(f"phone thread {thread_id} has invalid unread value")
        for message_id in message_ids:
            message = messages.get(message_id)
            if not isinstance(message, dict) or message.get("message_id") != message_id:
                errors.append(f"phone thread {thread_id} references unknown message {message_id}")
                continue
            if message.get("thread_id") != thread_id:
                errors.append(f"phone message {message_id} references wrong thread")
            if {message.get("sender_id"), message.get("receiver_id")} != set(participants):
                errors.append(f"phone message {message_id} has invalid participants")
            if not isinstance(message.get("text"), str) or not message["text"] or len(message["text"]) > max_length:
                errors.append(f"phone message {message_id} has invalid text")
    indexed = {message_id for thread in threads.values() if isinstance(thread, dict) for message_id in thread.get("message_ids", ())}
    if indexed != set(messages):
        errors.append("campus messaging contains unindexed messages")
    return errors


__all__ = [
    "CAMPUS_MESSAGING_SCHEMA_VERSION", "PHONE_ACTION_IDS", "CampusMessagingPolicy",
    "advance_campus_phone_messages", "campus_messaging_invariant",
    "install_campus_messaging", "load_campus_messaging_policy",
    "make_campus_messaging_handler",
]
