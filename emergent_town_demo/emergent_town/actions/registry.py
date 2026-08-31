from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ActionResult:
    success: bool
    outcome: str
    message: str
    event_id: Optional[str] = None
    produced_intel_ids: List[str] = field(default_factory=list)
    produced_trace_ids: List[str] = field(default_factory=list)
    state_changes: Dict[str, int] = field(default_factory=dict)


@dataclass
class ActionDefinition:
    id: str
    category: str
    satisfies: List[str]
    executor: Callable[..., ActionResult]
    required_target: Optional[str] = None
    required_skills: List[str] = field(default_factory=list)
    energy_cost: int = 0
    time_cost: int = 1
    legal_risk: int = 0
    allowed_layers: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    validator: Optional[Callable[..., Optional[str]]] = None


class ActionRegistry:
    def __init__(self):
        self._actions: Dict[str, ActionDefinition] = {}

    def register(self, definition: ActionDefinition):
        if definition.id in self._actions:
            raise ValueError(f"duplicate action: {definition.id}")
        if not callable(definition.executor):
            raise ValueError(f"action has no executor: {definition.id}")
        self._actions[definition.id] = definition
        return definition

    def get(self, action_id: str) -> Optional[ActionDefinition]:
        return self._actions.get(action_id)

    def ids(self) -> List[str]:
        return sorted(self._actions)

    def available(self, npc, context=None) -> List[ActionDefinition]:
        result = []
        for definition in self._actions.values():
            if definition.allowed_layers and npc.layer not in definition.allowed_layers:
                continue
            if npc.states.get("energy", 70) < definition.energy_cost:
                continue
            if definition.validator and definition.validator(npc, context):
                continue
            result.append(definition)
        return result

    def execute(self, action_id: str, *, npc, context=None, **kwargs) -> ActionResult:
        definition = self._actions.get(action_id)
        if not definition:
            return ActionResult(False, "invalid_action", f"未注册行为：{action_id}")
        if definition.allowed_layers and npc.layer not in definition.allowed_layers:
            return ActionResult(False, "forbidden", f"{npc.name} 的身份不能执行 {action_id}")
        if npc.states.get("energy", 70) < definition.energy_cost:
            return ActionResult(False, "exhausted", f"{npc.name} 精力不足，无法执行 {action_id}")
        if definition.validator:
            reason = definition.validator(npc, context)
            if reason:
                return ActionResult(False, "precondition_failed", reason)
        result = definition.executor(npc=npc, context=context, **kwargs)
        if result.success and definition.energy_cost:
            npc.states["energy"] = max(0, npc.states.get("energy", 70)-definition.energy_cost)
        if result.success and definition.legal_risk:
            npc.states["legal_risk"] = min(100, npc.states.get("legal_risk", 0)+definition.legal_risk)
        return result

    def validate(self) -> List[str]:
        errors = []
        for action_id, definition in self._actions.items():
            if not callable(definition.executor):
                errors.append(f"{action_id}: missing executor")
            if definition.time_cost < 1:
                errors.append(f"{action_id}: invalid time cost")
        return errors
