"""Four-phase clock and independent per-actor major-action budgets."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable

from simulation.actions.commands import SimulationCommand
from simulation.domain.action_economy import ActionEconomyPolicy, build_action_economy_policy
from simulation.domain.entities import PHASES, Phase
from simulation.domain.world_state import WorldState
from simulation.systems.content_registry import ContentRegistry
from simulation.systems.transactions import TransactionOutcome


def next_phase(phase: Phase) -> tuple[Phase, bool]:
    """Return the next phase and whether the day rolled over."""
    index = PHASES.index(phase)
    if index == len(PHASES) - 1:
        return PHASES[0], True
    return PHASES[index + 1], False


@dataclass(frozen=True)
class MajorActionResult:
    success: bool
    code: str
    message: str
    payload: Dict[str, Any] = field(default_factory=dict)


def load_action_economy_policy(registry: ContentRegistry) -> ActionEconomyPolicy:
    document = registry.document("actions/action_economy.json")
    phases = document.get("phases")
    if not isinstance(phases, list):
        raise ValueError("action economy content must contain a phases array")
    return build_action_economy_policy(phases)


def _new_actor_budget(state: WorldState, policy: ActionEconomyPolicy) -> Dict[str, Any]:
    rule = policy.rule(state.clock.phase)
    return {
        "day": state.clock.day,
        "phase": state.clock.phase,
        "major_remaining": rule.major_actions,
    }


def install_action_economy(state: WorldState, policy: ActionEconomyPolicy) -> None:
    """Give every persistent actor its own major-action allowance."""
    if state.action_economy:
        raise ValueError("world action economy aggregate is already initialized")
    state.action_economy.update({
        "policy": policy.to_dict(),
        "actors": {
            actor_id: _new_actor_budget(state, policy)
            for actor_id, actor in state.population.items()
            if isinstance(actor, dict)
        },
    })


def ensure_actor_budget(
    state: WorldState,
    policy: ActionEconomyPolicy,
    actor_id: str,
) -> Dict[str, Any]:
    actors = state.action_economy.setdefault("actors", {})
    budget = actors.get(actor_id)
    if not isinstance(budget, dict) or (
        budget.get("day") != state.clock.day
        or budget.get("phase") != state.clock.phase
    ):
        budget = _new_actor_budget(state, policy)
        actors[actor_id] = budget
    return budget


def consume_major_action(
    state: WorldState,
    policy: ActionEconomyPolicy,
    command: SimulationCommand,
) -> MajorActionResult:
    """Consume one major action; free actions never call this function."""
    if command.issued_day != state.clock.day or command.issued_phase != state.clock.phase:
        return MajorActionResult(
            False,
            "command_clock_mismatch",
            "行动指令所属的日期或时段已经过期。",
        )
    if command.actor_id not in state.population:
        return MajorActionResult(False, "unknown_actor", "行动者不存在。")
    budget = ensure_actor_budget(state, policy, command.actor_id)
    if int(budget["major_remaining"]) <= 0:
        return MajorActionResult(
            False,
            "major_action_exhausted",
            "当前时段已没有可用的主要行动次数。",
            {"major_remaining": 0},
        )
    budget["major_remaining"] = int(budget["major_remaining"]) - 1
    return MajorActionResult(
        True,
        "success",
        "已消耗一次主要行动。",
        {"major_remaining": int(budget["major_remaining"])},
    )


def reset_all_actor_budgets(state: WorldState, policy: ActionEconomyPolicy) -> None:
    state.action_economy["actors"] = {
        actor_id: _new_actor_budget(state, policy)
        for actor_id, actor in state.population.items()
        if isinstance(actor, dict)
    }


def action_economy_invariant(state: WorldState) -> Iterable[str]:
    economy = state.action_economy
    if not economy:
        return ()
    errors: list[str] = []
    stored_policy = economy.get("policy")
    actors = economy.get("actors")
    phase_rules = stored_policy.get("phases") if isinstance(stored_policy, dict) else None
    if not isinstance(stored_policy, dict):
        errors.append("action_economy.policy must be a mapping")
    elif not isinstance(phase_rules, dict) or set(phase_rules) != {item.value for item in PHASES}:
        errors.append("action_economy.policy must define all four phases")
    if not isinstance(actors, dict):
        return [*errors, "action_economy.actors must be a mapping"]
    missing = set(state.population) - set(actors)
    extra = set(actors) - set(state.population)
    if missing:
        errors.append("action budgets missing actors: " + ", ".join(sorted(missing)))
    if extra:
        errors.append("action budgets reference unknown actors: " + ", ".join(sorted(extra)))
    for actor_id, budget in actors.items():
        if not isinstance(budget, dict):
            errors.append(f"action budget for {actor_id} must be a mapping")
            continue
        if budget.get("day") != state.clock.day or budget.get("phase") != state.clock.phase:
            errors.append(f"action budget clock mismatch for {actor_id}")
        remaining = budget.get("major_remaining")
        if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining < 0:
            errors.append(f"action budget {actor_id}.major_remaining must be non-negative")
        elif isinstance(phase_rules, dict):
            current_rule = phase_rules.get(state.clock.phase, {})
            maximum = current_rule.get("major_actions") if isinstance(current_rule, dict) else None
            if isinstance(maximum, int) and remaining > maximum:
                errors.append(f"action budget {actor_id}.major_remaining exceeds phase maximum")
    return errors


def make_advance_phase_handler(policy: ActionEconomyPolicy):
    def advance(context, command):
        if command.actor_id not in context.state.population:
            return TransactionOutcome(False, False, "unknown_actor", "行动者不存在。")
        if command.issued_day != context.state.clock.day or command.issued_phase != context.state.clock.phase:
            return TransactionOutcome(
                False, False, "command_clock_mismatch", "推进时段的指令已经过期。"
            )
        previous_day = context.state.clock.day
        previous_phase = context.state.clock.phase
        context.state.clock.advance_phase()
        reset_all_actor_budgets(context.state, policy)
        rule = policy.rule(context.state.clock.phase)
        context.emit(
            "WORLD_PHASE_ADVANCED",
            f"时间从第 {previous_day} 天 {previous_phase} 推进到第 {context.state.clock.day} 天 {context.state.clock.phase}。",
            actor_ids=[command.actor_id],
            payload={
                "previous_day": previous_day,
                "previous_phase": previous_phase,
                "day": context.state.clock.day,
                "phase": context.state.clock.phase,
                "day_rolled_over": context.state.clock.day != previous_day,
                "major_actions": rule.major_actions,
                "optional": rule.optional,
            },
            knowledge_tags=["time", "phase"],
        )
        return TransactionOutcome(
            True,
            True,
            "success",
            "时段推进完成。",
            commit=True,
            payload={
                "day": context.state.clock.day,
                "phase": context.state.clock.phase,
                "minute": context.state.clock.minute,
                "major_remaining": rule.major_actions,
            },
        )

    return advance


__all__ = [
    "PHASES",
    "Phase",
    "MajorActionResult",
    "action_economy_invariant",
    "consume_major_action",
    "ensure_actor_budget",
    "install_action_economy",
    "load_action_economy_policy",
    "make_advance_phase_handler",
    "next_phase",
    "reset_all_actor_budgets",
]
