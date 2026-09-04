"""Rule-authoritative player proposals carried by in-person or phone dialogue."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, Dict, Iterable, Mapping

from simulation.domain.world_state import WorldState
from simulation.systems.campus_interactions import (
    CampusInteractionPolicy,
    _acceptance_score,
    _apply_emotions,
    _create_outcome_claims,
    _legal_intents,
    _open_hook,
    _pair_key,
    _region_id,
    _regions_share_coarse_scene,
)
from simulation.systems.campus_messaging import (
    CampusMessagingPolicy,
    append_structured_phone_exchange,
    are_phone_contacts,
)
from simulation.systems.campus_parties import party_for_actor
from simulation.systems.campus_social import adjust_relationship
from simulation.systems.campus_tasks import phase_index
from simulation.systems.transactions import TransactionOutcome


PLAYER_PROPOSAL_ACTION_ID = "MAKE_SOCIAL_PROPOSAL"
PLAYER_PROPOSAL_TYPES = {
    "party_invite": {
        "intent_id": "party_invite",
        "name": "邀请加入行动小队",
        "request": "我想邀请你加入我的行动小队，你愿意吗？",
    },
    "task_help": {
        "intent_id": "ask_task_help",
        "name": "请求协助当前任务",
        "request": "我正在处理一项任务，想请你协助其中一部分，你愿意吗？",
    },
    "meet_up": {
        "intent_id": "plan_meet_up",
        "name": "约定稍后见面",
        "request": "我们可以约个时间再见面，把这件事继续聊完吗？",
    },
    "follow_up": {
        "intent_id": "follow_up_promise",
        "name": "兑现已有约定",
        "request": "我们之前约好的事情，现在可以一起落实吗？",
    },
}


def install_campus_proposals(state: WorldState) -> None:
    interactions = state.cognition.get("interactions")
    if not isinstance(interactions, dict):
        raise ValueError("campus interactions must be installed before proposals")
    if "proposals" in interactions:
        raise ValueError("campus proposals are already installed")
    interactions.update({
        "proposal_sequence": 0,
        "proposals": [],
        "proposal_last_phase": {},
    })


def _same_scene(
    state: WorldState,
    first_id: str,
    second_id: str,
    policy: CampusInteractionPolicy,
) -> bool:
    first = state.population[first_id]
    second = state.population[second_id]
    return _regions_share_coarse_scene(
        _region_id(state, first.get("current_location_id")),
        _region_id(state, second.get("current_location_id")),
        policy,
    )


def _rule_reply(proposal_type: str, accepted: bool) -> str:
    replies = {
        "party_invite": (
            "可以，我愿意加入你的行动小队。具体安排我们再确认。",
            "谢谢你想到我，但我现在不愿意加入这次行动。",
        ),
        "task_help": (
            "可以。把任务现状和需要我负责的部分发给我，我会帮忙。",
            "抱歉，我现在没有余力接下这件事。",
        ),
        "meet_up": (
            "可以，我们先把这次见面记下来，之后再确认具体安排。",
            "我近期不太方便作这个约定，之后再说吧。",
        ),
        "follow_up": (
            "我还记得之前的约定，现在就一起把它落实。",
            "我记得这件事，但现在还不能兑现。",
        ),
    }
    return replies[proposal_type][0 if accepted else 1]


def _request_text(proposal_type: str, note: str) -> str:
    base = str(PLAYER_PROPOSAL_TYPES[proposal_type]["request"])
    return f"{base} 补充：{note}" if note else base


def _proposal_key(target_id: str, proposal_type: str) -> str:
    return f"{_pair_key('player', target_id)}|{proposal_type}"


def _recent_phone_messages(state: WorldState, target_id: str) -> list[Dict[str, Any]]:
    messaging = state.cognition.get("messaging", {})
    thread_id = f"phone_thread:{'|'.join(sorted(('player', target_id)))}"
    thread = messaging.get("threads", {}).get(thread_id, {})
    messages = messaging.get("messages", {})
    return [
        messages[message_id]
        for message_id in thread.get("message_ids", ())[-6:]
        if isinstance(messages.get(message_id), dict)
    ]


def _create_proposal_hook(
    state: WorldState,
    target_id: str,
    hook_type: str,
    policy: CampusInteractionPolicy,
    now: int,
    linked_task_id: str | None = None,
) -> str | None:
    interactions = state.cognition["interactions"]
    active = [
        hook for hook in interactions["hooks"]
        if hook.get("state") in {"open", "task_posted"}
    ]
    if len(active) >= policy.max_open_hooks:
        return None
    if any(
        hook.get("state") == "open"
        and hook.get("actor_id") == target_id
        and hook.get("target_id") == "player"
        and hook.get("hook_type") == hook_type
        and hook.get("linked_task_id") == linked_task_id
        for hook in active
    ):
        return None
    interactions["hook_sequence"] += 1
    hook_id = f"social_hook:{interactions['hook_sequence']:06d}"
    record = {
        "hook_id": hook_id,
        "hook_type": hook_type,
        "actor_id": target_id,
        "target_id": "player",
        "created_day": state.clock.day,
        "created_phase": state.clock.phase,
        "expires_phase_index": now + policy.hook_lifetime_phases,
        "state": "open",
    }
    if linked_task_id:
        record["linked_task_id"] = linked_task_id
    interactions["hooks"].append(record)
    return hook_id


def make_player_proposal_handler(
    interaction_policy: CampusInteractionPolicy,
    messaging_policy: CampusMessagingPolicy,
    party_handler,
    cognition_runtime=None,
):
    """Create one explicit accept/decline boundary for consequential dialogue."""
    def handle(context, command) -> TransactionOutcome:
        state = context.state
        if command.actor_id != "player":
            return TransactionOutcome(False, False, "player_only", "目前只有玩家可以主动发起结构化提议。")
        target_id = str(command.parameters.get("target_id", ""))
        if target_id not in state.population or target_id == "player":
            return TransactionOutcome(False, False, "invalid_proposal_target", "提议对象不存在。")
        proposal_type = str(command.parameters.get("proposal_type", ""))
        if proposal_type not in PLAYER_PROPOSAL_TYPES:
            return TransactionOutcome(False, False, "invalid_proposal_type", "不支持这种提议。")
        channel = str(command.parameters.get("channel", "in_person"))
        if channel not in {"in_person", "phone"}:
            return TransactionOutcome(False, False, "invalid_proposal_channel", "提议渠道无效。")
        if channel == "in_person" and not _same_scene(state, "player", target_id, interaction_policy):
            return TransactionOutcome(False, False, "target_not_present", "需要与对方处于同一校园场景才能当面提议。")
        if channel == "phone" and not are_phone_contacts(state, "player", target_id):
            return TransactionOutcome(False, False, "not_a_contact", "需要先见面并交换联系方式。")
        note = str(command.parameters.get("note", "")).strip()
        if len(note) > interaction_policy.player_max_text_length:
            return TransactionOutcome(False, False, "proposal_note_too_long", "提议补充不能超过 240 个字符。")
        request_text = _request_text(proposal_type, note)
        if channel == "phone" and len(request_text) > messaging_policy.max_text_length:
            return TransactionOutcome(False, False, "proposal_note_too_long", "提议和补充内容合计不能超过 240 个字符。")

        interactions = state.cognition["interactions"]
        now = phase_index(state.clock.day, state.clock.phase)
        last_phase = interactions["proposal_last_phase"].get(_proposal_key(target_id, proposal_type))
        if last_phase == now:
            return TransactionOutcome(False, False, "proposal_cooldown", "本时段已经向对方提出过同类请求。")

        definition_meta = PLAYER_PROPOSAL_TYPES[proposal_type]
        intent_id = str(definition_meta["intent_id"])
        hook_id = None
        hook_transition = None
        subject_id = None
        relationship_deltas: Dict[str, Any] = {"actor": {}, "target": {}}
        emotion_deltas: Dict[str, Any] = {"actor": {}, "target": {}}
        outcome_claim_ids: list[str] = []

        if proposal_type == "party_invite":
            party = party_for_actor(state, "player")
            subject_id = str(party.get("party_id")) if isinstance(party, dict) else None
            delegated = party_handler(
                context,
                replace(
                    command,
                    action_id="INVITE_PARTY_MEMBER",
                    parameters={"target_id": target_id},
                ),
            )
            if not delegated.performed:
                return delegated
            accepted = bool(delegated.success)
            assessment = delegated.payload.get("assessment", {})
            acceptance_score = float(assessment.get("score", -1000))
            threshold = float(assessment.get("threshold", 0))
            relationship_deltas = deepcopy(delegated.payload.get("relationship_changes", relationship_deltas))
        else:
            legal = {
                item["intent_id"]: item
                for item in _legal_intents(state, "player", target_id, interaction_policy)
            }
            if intent_id not in legal:
                messages = {
                    "task_help": "需要先接取一项进行中的任务，才能请求具体协助。",
                    "follow_up": "你们之间目前没有可以兑现的未完成约定。",
                }
                return TransactionOutcome(
                    False, False, "proposal_precondition_failed",
                    messages.get(proposal_type, "当前情境不支持这个提议。"),
                )
            definition = interaction_policy.intents[intent_id]
            if proposal_type == "task_help":
                subject_id = str(state.population["player"].get("active_forum_task_id", "")) or None
                task = state.tasks.get(str(subject_id), {})
                if not isinstance(task, dict) or task.get("assignee_id") != "player":
                    return TransactionOutcome(False, False, "invalid_active_task", "当前没有由你负责的有效任务。")
            open_hook = _open_hook(state, "player", target_id)
            if proposal_type == "follow_up" and open_hook is not None:
                subject_id = str(open_hook["hook_id"])
            acceptance_score = _acceptance_score(
                state, "player", target_id, intent_id,
                context.rng.stream("player_proposal_outcome"),
            )
            threshold = float(definition.get("acceptance_threshold", 0))
            accepted = acceptance_score >= threshold
            outcome_key = "accept" if accepted else "reject"
            relationship = definition.get(f"relationship_on_{outcome_key}", {})
            relationship_deltas = {
                "actor": adjust_relationship(state, "player", target_id, relationship.get("initiator", {})),
                "target": adjust_relationship(state, target_id, "player", relationship.get("target", {})),
            }
            emotions = definition.get("emotion_on_accept", {}) if accepted else definition.get("emotion_on_reject", {})
            emotion_deltas = {
                "actor": _apply_emotions(state.population["player"], emotions.get("initiator", {})),
                "target": _apply_emotions(state.population[target_id], emotions.get("target", {})),
            }
            if definition.get("resolves_hook") and open_hook is not None:
                open_hook["state"] = "completed" if accepted else "broken"
                open_hook["resolved_day"] = state.clock.day
                open_hook["resolved_phase"] = state.clock.phase
                hook_id = str(open_hook["hook_id"])
                hook_transition = "completed" if accepted else "broken"
            elif accepted and definition.get("creates_hook"):
                hook_type = (
                    "task_support_commitment"
                    if proposal_type == "task_help"
                    else str(definition["creates_hook"])
                )
                hook_id = _create_proposal_hook(
                    state, target_id, hook_type, interaction_policy, now,
                    str(subject_id) if proposal_type == "task_help" and subject_id else None,
                )
                if hook_id is None:
                    return TransactionOutcome(
                        False, False, "proposal_commitment_unavailable",
                        "双方已经有同类约定，或当前可追踪约定数量已满。",
                    )
                hook_transition = "created" if hook_id else None
                subject_id = subject_id or hook_id
                if proposal_type == "task_help" and hook_id and subject_id:
                    task = state.tasks[str(subject_id)]
                    if target_id not in task.setdefault("helper_ids", []):
                        task["helper_ids"].append(target_id)

        status = "accepted" if accepted else "declined"
        interactions["proposal_sequence"] += 1
        proposal_id = f"proposal:{interactions['proposal_sequence']:08d}"
        verified_summary = (
            f"{state.population[target_id].get('display_name', target_id)}"
            f"{'接受' if accepted else '拒绝'}了玩家提出的“{definition_meta['name']}”。"
        )
        if proposal_type != "party_invite":
            outcome_claim_ids = _create_outcome_claims(
                state,
                actor_id="player",
                target_id=target_id,
                interaction_id=proposal_id,
                intent_id=intent_id,
                outcome="accepted" if accepted else "rejected",
                summary=verified_summary,
                hook_id=hook_id,
                hook_transition=hook_transition,
            )
        reply_text = _rule_reply(proposal_type, accepted)
        wording_source = "rule"
        if cognition_runtime is not None:
            context_payload = {
                "intent_id": intent_id,
                "intent_name": definition_meta["name"],
                "proposal_type": proposal_type,
                "outcome": "accepted" if accepted else "rejected",
                "verified_summary": verified_summary,
                "hook_transition": hook_transition,
                "consequence_applied": True,
                "location_id": state.population["player"].get("current_location_id"),
            }
            if channel == "phone":
                dialogue = cognition_runtime.compose_phone_reply(
                    state, target_id, "player", request_text,
                    _recent_phone_messages(state, target_id), [], context_payload,
                )
            else:
                dialogue = cognition_runtime.compose_player_in_person_reply(
                    state, target_id, "player", request_text, context_payload,
                    [item for item in interactions.get("player_dialogues", ()) if item.get("target_id") == target_id],
                    [],
                )
            if dialogue is not None:
                reply_text = str(dialogue["utterance"])
                wording_source = "llm"

        phone_exchange = None
        if channel == "phone":
            phone_exchange = append_structured_phone_exchange(
                context, "player", target_id, request_text, reply_text, messaging_policy
            )
        record = {
            "proposal_id": proposal_id,
            "day": state.clock.day,
            "phase": state.clock.phase,
            "channel": channel,
            "player_id": "player",
            "target_id": target_id,
            "proposal_type": proposal_type,
            "intent_id": intent_id,
            "subject_id": subject_id,
            "status": status,
            "acceptance_score": acceptance_score,
            "acceptance_threshold": threshold,
            "note": note,
            "request_text": request_text,
            "reply_text": reply_text,
            "wording_source": wording_source,
            "hook_id": hook_id,
            "hook_transition": hook_transition,
            "relationship_deltas": relationship_deltas,
            "emotion_deltas": emotion_deltas,
            "outcome_claim_ids": outcome_claim_ids,
            "phone_exchange": phone_exchange,
            "action_class": "free",
        }
        interactions["proposals"].append(record)
        del interactions["proposals"][:-interaction_policy.max_recent_interactions]
        interactions["proposal_last_phase"][_proposal_key(target_id, proposal_type)] = now
        context.emit(
            "SOCIAL_PROPOSAL_RESOLVED",
            verified_summary,
            actor_ids=["player"],
            target_ids=[target_id],
            scene_id=(
                str(state.population["player"].get("current_location_id", "")) or None
                if channel == "in_person" else None
            ),
            payload=deepcopy(record),
            visibility="private",
            severity=3,
            knowledge_tags=["social", "proposal", "relationship", proposal_type, channel],
        )
        return TransactionOutcome(
            True,
            accepted,
            "success" if accepted else "proposal_declined",
            "对方接受了提议。" if accepted else "对方明确拒绝了提议。",
            commit=True,
            payload=deepcopy(record),
        )

    return handle


def campus_proposal_invariant(state: WorldState) -> Iterable[str]:
    interactions = state.cognition.get("interactions")
    if not isinstance(interactions, dict) or "proposals" not in interactions:
        return ()
    errors: list[str] = []
    proposals = interactions.get("proposals")
    if not isinstance(proposals, list):
        return ("campus proposals must be a list",)
    ids: set[str] = set()
    for record in proposals:
        if not isinstance(record, dict):
            errors.append("campus proposal record must be a mapping")
            continue
        proposal_id = record.get("proposal_id")
        if not isinstance(proposal_id, str) or not proposal_id or proposal_id in ids:
            errors.append("campus proposal id is invalid or duplicated")
        else:
            ids.add(proposal_id)
        if record.get("player_id") != "player" or record.get("target_id") not in state.population:
            errors.append("campus proposal references an invalid participant")
        if record.get("proposal_type") not in PLAYER_PROPOSAL_TYPES:
            errors.append("campus proposal has an invalid type")
        if record.get("channel") not in {"in_person", "phone"}:
            errors.append("campus proposal has an invalid channel")
        if record.get("status") not in {"accepted", "declined"}:
            errors.append("campus proposal has an invalid status")
        if record.get("wording_source") not in {"rule", "llm"}:
            errors.append("campus proposal has an invalid wording source")
        if record.get("action_class") != "free":
            errors.append("campus proposal must remain a free action")
        if not isinstance(record.get("outcome_claim_ids"), list) or any(
            claim_id not in state.knowledge.get("claims", {})
            for claim_id in record.get("outcome_claim_ids", ())
        ):
            errors.append("campus proposal references an invalid outcome claim")
    if not isinstance(interactions.get("proposal_last_phase"), dict):
        errors.append("campus proposal cooldown index must be a mapping")
    return errors


__all__ = [
    "PLAYER_PROPOSAL_ACTION_ID", "PLAYER_PROPOSAL_TYPES",
    "campus_proposal_invariant", "install_campus_proposals",
    "make_player_proposal_handler",
]
