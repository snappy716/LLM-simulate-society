from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simulation.actions import SimulationCommand
from simulation.domain import WorldState
from simulation.persistence import (
    CheckpointError,
    KernelEventJournal,
    build_kernel_checkpoint,
    load_kernel_checkpoint,
    save_kernel_checkpoint,
)
from simulation.systems import ContentRegistry, DeterministicRngPool, TransactionOutcome, WorldKernel


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


def register_credit(kernel: WorldKernel) -> None:
    def handler(context, command):
        context.state.inventories.setdefault("player", {"money": 0})["money"] += 1
        context.rng.stream("economy").randint(1, 100)
        context.emit("CREDIT", "credit committed", actor_ids=[command.actor_id])
        return TransactionOutcome(True, True, "success", "credited", commit=True)

    kernel.register_handler("CREDIT", handler)


def credit_command(command_id: str, revision: int) -> SimulationCommand:
    return SimulationCommand(command_id, "player", "CREDIT", revision)


class KernelCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")

    def test_round_trip_preserves_world_rng_content_and_idempotency(self):
        state = WorldState(
            content_version=self.registry.content_version,
            inventories={"player": {"money": 10}},
        )
        journal = KernelEventJournal(self.root / "events.jsonl")
        kernel = WorldKernel(state, event_sink=journal)
        register_credit(kernel)
        result = kernel.execute(credit_command("cmd-1", 1))
        path = self.root / "save.json"
        save_kernel_checkpoint(
            path,
            kernel.state,
            DeterministicRngPool.from_snapshot(kernel.rng_snapshot),
            content_manifest=self.registry.manifest,
        )

        loaded = load_kernel_checkpoint(
            path, expected_content_version=self.registry.content_version
        )
        restored = WorldKernel(loaded.state, rng=loaded.rng)
        register_credit(restored)
        replay = restored.execute(credit_command("cmd-1", 1))
        self.assertTrue(replay.replayed)
        self.assertEqual(result.events, replay.events)
        self.assertEqual(11, restored.state.inventories["player"]["money"])
        self.assertEqual(self.registry.manifest, loaded.content_manifest)

    def test_rng_continues_from_checkpoint(self):
        state = WorldState(content_version="test")
        rng = DeterministicRngPool(42)
        rng.stream("npc_decision").random()
        path = self.root / "save.json"
        save_kernel_checkpoint(path, state, rng)
        loaded = load_kernel_checkpoint(path)
        self.assertEqual(
            rng.stream("npc_decision").random(),
            loaded.rng.stream("npc_decision").random(),
        )

    def test_non_committing_result_remains_idempotent_after_load(self):
        state = WorldState(content_version="test")
        kernel = WorldKernel(state)

        def blocked(_context, _command):
            return TransactionOutcome(False, False, "blocked", "not allowed")

        kernel.register_handler("CREDIT", blocked)
        original = kernel.execute(credit_command("blocked", 1))
        self.assertEqual(1, original.world_revision)
        path = self.root / "save.json"
        save_kernel_checkpoint(
            path,
            kernel.state,
            DeterministicRngPool.from_snapshot(kernel.rng_snapshot),
        )
        loaded = load_kernel_checkpoint(path)
        restored = WorldKernel(loaded.state, rng=loaded.rng)
        register_credit(restored)
        replay = restored.execute(credit_command("blocked", 1))
        self.assertTrue(replay.replayed)
        self.assertFalse(replay.performed)
        self.assertEqual({}, restored.state.inventories)

    def test_checksum_detects_tampering(self):
        path = self.root / "save.json"
        save_kernel_checkpoint(path, WorldState(), DeterministicRngPool(42))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["world"]["revision"] = 999
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(CheckpointError, "checksum mismatch"):
            load_kernel_checkpoint(path)

    def test_content_mismatch_is_explicit(self):
        path = self.root / "save.json"
        save_kernel_checkpoint(
            path,
            WorldState(content_version="old-content"),
            DeterministicRngPool(42),
        )
        with self.assertRaisesRegex(CheckpointError, "content version mismatch"):
            load_kernel_checkpoint(path, expected_content_version="new-content")

    def test_atomic_save_leaves_no_temporary_file(self):
        path = self.root / "save.json"
        save_kernel_checkpoint(path, WorldState(), DeterministicRngPool(42))
        self.assertTrue(path.is_file())
        self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_built_checkpoint_has_no_machine_absolute_paths(self):
        payload = build_kernel_checkpoint(WorldState(), DeterministicRngPool(42))
        encoded = json.dumps(payload)
        self.assertNotIn(str(REPOSITORY_DIR), encoded)


class KernelEventJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "events.jsonl"

    def test_journal_appends_across_sessions_without_truncation(self):
        first = KernelEventJournal(self.path)
        kernel = WorldKernel(WorldState(), event_sink=first)
        register_credit(kernel)
        one = kernel.execute(credit_command("one", 1))
        two = kernel.execute(credit_command("two", 2))

        reopened = KernelEventJournal(self.path)
        self.assertEqual([*one.events, *two.events], reopened.read_events())

    def test_corrupt_journal_is_rejected(self):
        self.path.write_text("{not-json}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid event journal line 1"):
            KernelEventJournal(self.path)


if __name__ == "__main__":
    unittest.main()
