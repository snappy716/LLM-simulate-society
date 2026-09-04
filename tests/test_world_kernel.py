from __future__ import annotations

import unittest

from simulation.actions import SimulationCommand
from simulation.domain import WorldState
from simulation.systems import (
    DeterministicRngPool,
    DuplicateCommandError,
    RevisionConflictError,
    TransactionOutcome,
    WorldKernel,
)


class RecordingSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events = []

    def append_batch(self, events) -> None:
        if self.fail:
            raise OSError("disk unavailable")
        self.events.extend(events)


def command(command_id: str, revision: int = 1, *, amount: int = 3) -> SimulationCommand:
    return SimulationCommand(
        command_id=command_id,
        actor_id="player",
        action_id="TEST_CREDIT",
        expected_world_revision=revision,
        parameters={"amount": amount},
    )


def credit_handler(context, request):
    amount = int(request.parameters["amount"])
    wallet = context.state.inventories.setdefault("player", {"money": 0})
    wallet["money"] += amount
    roll = context.rng.stream("economy").randint(1, 100)
    context.emit(
        "TEST_CREDITED",
        f"player received {amount}",
        actor_ids=[request.actor_id],
        payload={"amount": amount, "roll": roll},
    )
    return TransactionOutcome(True, True, "success", "credited", commit=True)


class WorldKernelTests(unittest.TestCase):
    def make_kernel(self, *, sink=None) -> WorldKernel:
        state = WorldState(inventories={"player": {"money": 10}})
        kernel = WorldKernel(state, event_sink=sink)
        kernel.register_handler("TEST_CREDIT", credit_handler)
        return kernel

    def test_commits_state_event_and_rng_exactly_once(self):
        sink = RecordingSink()
        kernel = self.make_kernel(sink=sink)
        result = kernel.execute(command("cmd-1"))

        self.assertTrue(result.success)
        self.assertEqual(2, result.world_revision)
        self.assertEqual(13, kernel.state.inventories["player"]["money"])
        self.assertEqual("evt:0000000001", result.events[0].event_id)
        self.assertEqual(result.events, tuple(sink.events))

        replay = kernel.execute(command("cmd-1"))
        self.assertTrue(replay.replayed)
        self.assertEqual(result.events, replay.events)
        self.assertEqual(2, kernel.state.revision)
        self.assertEqual(13, kernel.state.inventories["player"]["money"])

    def test_reusing_command_id_with_different_payload_is_rejected(self):
        kernel = self.make_kernel()
        kernel.execute(command("cmd-1"))
        with self.assertRaises(DuplicateCommandError):
            kernel.execute(command("cmd-1", amount=99))

    def test_stale_world_revision_is_rejected_before_handler(self):
        kernel = self.make_kernel()
        with self.assertRaises(RevisionConflictError):
            kernel.execute(command("stale", revision=2))
        self.assertEqual(10, kernel.state.inventories["player"]["money"])

    def test_non_committing_outcome_discards_draft_mutations(self):
        kernel = WorldKernel(WorldState(inventories={"player": {"money": 10}}))

        def decline(context, _request):
            context.state.inventories["player"]["money"] = 0
            context.rng.stream("economy").random()
            return TransactionOutcome(False, False, "declined", "not performed")

        kernel.register_handler("TEST_CREDIT", decline)
        result = kernel.execute(command("declined"))
        self.assertFalse(result.performed)
        self.assertEqual(1, result.world_revision)
        self.assertEqual(10, kernel.state.inventories["player"]["money"])
        self.assertEqual({}, kernel.rng_snapshot["streams"])
        replay = kernel.execute(command("declined"))
        self.assertTrue(replay.replayed)

    def test_handler_exception_rolls_back_state_and_rng(self):
        kernel = WorldKernel(WorldState(inventories={"player": {"money": 10}}))

        def explode(context, _request):
            context.state.inventories["player"]["money"] = 999
            context.rng.stream("economy").randint(1, 100)
            raise RuntimeError("boom")

        kernel.register_handler("TEST_CREDIT", explode)
        with self.assertRaisesRegex(RuntimeError, "boom"):
            kernel.execute(command("explode"))
        self.assertEqual(10, kernel.state.inventories["player"]["money"])
        self.assertEqual({}, kernel.rng_snapshot["streams"])

    def test_invariant_failure_rolls_back_transaction(self):
        kernel = self.make_kernel()
        kernel.add_invariant(
            lambda state: ["money ceiling exceeded"]
            if state.inventories["player"]["money"] > 11 else []
        )
        with self.assertRaisesRegex(ValueError, "money ceiling exceeded"):
            kernel.execute(command("invalid"))
        self.assertEqual(1, kernel.state.revision)
        self.assertEqual(10, kernel.state.inventories["player"]["money"])
        self.assertEqual({}, kernel.rng_snapshot["streams"])

    def test_event_sink_failure_prevents_commit(self):
        kernel = self.make_kernel(sink=RecordingSink(fail=True))
        with self.assertRaisesRegex(OSError, "disk unavailable"):
            kernel.execute(command("sink-failure"))
        self.assertEqual(1, kernel.state.revision)
        self.assertEqual(10, kernel.state.inventories["player"]["money"])

    def test_committed_block_event_can_be_unperformed_failure(self):
        kernel = WorldKernel(WorldState())

        def blocked(context, request):
            context.emit("ACTION_BLOCKED", "door is locked", actor_ids=[request.actor_id])
            return TransactionOutcome(False, False, "locked", "door is locked", commit=True)

        kernel.register_handler("TEST_CREDIT", blocked)
        result = kernel.execute(command("blocked"))
        self.assertFalse(result.performed)
        self.assertFalse(result.success)
        self.assertEqual(2, result.world_revision)
        self.assertEqual("ACTION_BLOCKED", result.events[0].event_type)

    def test_state_property_is_a_defensive_copy(self):
        kernel = self.make_kernel()
        leaked = kernel.state
        leaked.inventories["player"]["money"] = -100
        self.assertEqual(10, kernel.state.inventories["player"]["money"])

    def test_project_view_returns_a_defensive_small_projection(self):
        kernel = self.make_kernel()
        view = kernel.project_view(
            lambda state: {"money": state.inventories["player"]}
        )
        view["money"]["money"] = -100
        self.assertEqual(10, kernel.state.inventories["player"]["money"])


class DeterministicRngPoolTests(unittest.TestCase):
    def test_named_streams_are_reproducible_and_independent(self):
        first = DeterministicRngPool(42)
        expected = [first.stream("npc_decision").randint(1, 100) for _ in range(3)]

        second = DeterministicRngPool(42)
        second.stream("combat").randint(1, 100)
        actual = [second.stream("npc_decision").randint(1, 100) for _ in range(3)]
        self.assertEqual(expected, actual)

    def test_snapshot_round_trip_continues_same_sequence(self):
        first = DeterministicRngPool(7)
        first.stream("tasks").random()
        restored = DeterministicRngPool.from_snapshot(first.snapshot())
        self.assertEqual(first.stream("tasks").random(), restored.stream("tasks").random())


if __name__ == "__main__":
    unittest.main()
