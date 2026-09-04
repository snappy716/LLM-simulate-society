"""Atomic command execution for the new authoritative world state."""
from __future__ import annotations

import threading
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Iterable, Optional, Protocol, Tuple

from simulation.actions.commands import CommandResult, SimulationCommand
from simulation.domain.events import EventDraft, SimulationEvent
from simulation.domain.world_state import WorldState
from simulation.systems.randomness import DeterministicRngPool


class RevisionConflictError(RuntimeError):
    pass


class DuplicateCommandError(RuntimeError):
    pass


class EventSink(Protocol):
    def append_batch(self, events: Iterable[SimulationEvent]) -> None: ...


class EventProjector(Protocol):
    def __call__(self, state: WorldState, events: Iterable[SimulationEvent]) -> None: ...


@dataclass
class TransactionOutcome:
    performed: bool
    success: bool
    code: str
    message: str
    commit: bool = False
    payload: Dict[str, Any] = field(default_factory=dict)


class TransactionContext:
    def __init__(
        self,
        state: WorldState,
        rng: DeterministicRngPool,
        command: SimulationCommand,
    ) -> None:
        self.state = state
        self.rng = rng
        self.command = command
        self._event_drafts: list[EventDraft] = []

    @property
    def event_drafts(self) -> Tuple[EventDraft, ...]:
        return tuple(self._event_drafts)

    def emit(
        self,
        event_type: str,
        public_summary: str,
        *,
        actor_ids: Iterable[str] = (),
        target_ids: Iterable[str] = (),
        scene_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        visibility: str = "public",
        severity: int = 1,
        knowledge_tags: Iterable[str] = (),
        causation_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> EventDraft:
        draft = EventDraft(
            event_type=event_type,
            public_summary=public_summary,
            actor_ids=tuple(actor_ids),
            target_ids=tuple(target_ids),
            scene_id=scene_id,
            payload=payload or {},
            visibility=visibility,
            severity=severity,
            knowledge_tags=tuple(knowledge_tags),
            causation_id=causation_id,
            correlation_id=correlation_id,
        )
        self._event_drafts.append(draft)
        return draft


CommandHandler = Callable[[TransactionContext, SimulationCommand], TransactionOutcome]
Invariant = Callable[[WorldState], Iterable[str]]
ReadProjector = Callable[[WorldState], Any]


class WorldKernel:
    """Serializes commands, isolates mutations, validates, and commits once."""

    def __init__(
        self,
        state: WorldState,
        *,
        rng: Optional[DeterministicRngPool] = None,
        event_sink: Optional[EventSink] = None,
    ) -> None:
        state.require_valid()
        self._state = state.clone()
        self._rng = rng or DeterministicRngPool(state.master_seed)
        if self._rng.master_seed != state.master_seed:
            raise ValueError("world state and RNG master seeds differ")
        self._event_sink = event_sink
        self._handlers: Dict[str, CommandHandler] = {}
        self._event_projectors: list[EventProjector] = []
        self._invariants: list[Invariant] = []
        self._lock = threading.RLock()

    @property
    def state(self) -> WorldState:
        return self._state.clone()

    @property
    def rng_snapshot(self) -> Dict[str, Any]:
        return self._rng.snapshot()

    def register_handler(self, action_id: str, handler: CommandHandler) -> None:
        if not action_id:
            raise ValueError("action_id is required")
        if action_id in self._handlers:
            raise ValueError(f"duplicate command handler: {action_id}")
        self._handlers[action_id] = handler

    def add_invariant(self, invariant: Invariant) -> None:
        self._invariants.append(invariant)

    def add_event_projector(self, projector: EventProjector) -> None:
        if projector in self._event_projectors:
            raise ValueError("duplicate event projector")
        self._event_projectors.append(projector)

    def project_view(self, projector: ReadProjector) -> Any:
        """Build a defensive read model without cloning unrelated aggregates."""
        with self._lock:
            return deepcopy(projector(self._state))

    def execute(self, command: SimulationCommand) -> CommandResult:
        with self._lock:
            fingerprint = command.fingerprint()
            duplicate = self._duplicate_result(command.command_id, fingerprint)
            if duplicate is not None:
                return replace(duplicate, replayed=True)

            if command.expected_world_revision != self._state.revision:
                raise RevisionConflictError(
                    f"expected world revision {command.expected_world_revision}, "
                    f"current revision is {self._state.revision}"
                )
            handler = self._handlers.get(command.action_id)
            if handler is None:
                result = CommandResult(
                    command_id=command.command_id,
                    accepted=False,
                    performed=False,
                    success=False,
                    code="unknown_action",
                    message=f"no handler registered for {command.action_id}",
                    world_revision=self._state.revision,
                )
                self._remember_result(self._state, fingerprint, result)
                return result

            draft_state = self._state.clone()
            draft_rng = self._rng.clone()
            context = TransactionContext(draft_state, draft_rng, command)
            try:
                outcome = handler(context, command)
                if not isinstance(outcome, TransactionOutcome):
                    raise TypeError("command handlers must return TransactionOutcome")
                if context.event_drafts and not outcome.commit:
                    raise ValueError("an outcome with events must commit its transaction")
                if not outcome.commit:
                    result = CommandResult(
                        command_id=command.command_id,
                        accepted=True,
                        performed=outcome.performed,
                        success=outcome.success,
                        code=outcome.code,
                        message=outcome.message,
                        world_revision=self._state.revision,
                        payload=outcome.payload,
                    )
                    self._remember_result(self._state, fingerprint, result)
                    return result

                next_revision = self._state.revision + 1
                draft_state.revision = next_revision
                events = self._materialize_events(
                    command, context.event_drafts, draft_state, next_revision
                )
                for projector in self._event_projectors:
                    projector(draft_state, events)
                invariant_errors: list[str] = []
                for invariant in self._invariants:
                    invariant_errors.extend(invariant(draft_state))
                draft_state.require_valid(invariant_errors)
                result = CommandResult(
                    command_id=command.command_id,
                    accepted=True,
                    performed=outcome.performed,
                    success=outcome.success,
                    code=outcome.code,
                    message=outcome.message,
                    world_revision=next_revision,
                    events=events,
                    payload=outcome.payload,
                )
                self._remember_result(draft_state, fingerprint, result)
                if self._event_sink is not None:
                    self._event_sink.append_batch(events)
                self._state = draft_state
                self._rng = draft_rng
                return result
            except Exception:
                # Both draft state and draft RNG are discarded.  The committed
                # state remains byte-for-byte equivalent to its pre-command form.
                raise

    def _duplicate_result(self, command_id: str, fingerprint: str) -> Optional[CommandResult]:
        record = self._state.processed_commands.get(command_id)
        if record is not None:
            if record.get("fingerprint") != fingerprint:
                raise DuplicateCommandError(f"command_id reused with different payload: {command_id}")
            return CommandResult.from_dict(record["result"])
        return None

    @staticmethod
    def _remember_result(
        state: WorldState,
        fingerprint: str,
        result: CommandResult,
    ) -> None:
        state.processed_commands[result.command_id] = {
            "fingerprint": fingerprint,
            "result": result.to_dict(),
        }

    @staticmethod
    def _materialize_events(
        command: SimulationCommand,
        drafts: Iterable[EventDraft],
        state: WorldState,
        next_revision: int,
    ) -> Tuple[SimulationEvent, ...]:
        events: list[SimulationEvent] = []
        for draft in drafts:
            state.event_sequence += 1
            events.append(SimulationEvent(
                event_id=f"evt:{state.event_sequence:010d}",
                event_type=draft.event_type,
                day=state.clock.day,
                phase=state.clock.phase,
                minute=state.clock.minute,
                world_revision=next_revision,
                command_id=command.command_id,
                public_summary=draft.public_summary,
                actor_ids=draft.actor_ids,
                target_ids=draft.target_ids,
                scene_id=draft.scene_id,
                payload=deepcopy(draft.payload),
                visibility=draft.visibility,
                severity=draft.severity,
                knowledge_tags=draft.knowledge_tags,
                causation_id=draft.causation_id,
                correlation_id=draft.correlation_id or command.command_id,
            ))
        return tuple(events)


__all__ = [
    "DuplicateCommandError",
    "EventProjector",
    "ReadProjector",
    "RevisionConflictError",
    "TransactionContext",
    "TransactionOutcome",
    "WorldKernel",
]
