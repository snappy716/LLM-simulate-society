from __future__ import annotations

import unittest
from pathlib import Path

from simulation.actions import SimulationCommand
from simulation.domain import WorldState
from simulation.systems import (
    ContentRegistry,
    TransactionOutcome,
    WorldKernel,
    action_economy_invariant,
    consume_major_action,
    install_action_economy,
    load_action_economy_policy,
    make_advance_phase_handler,
)


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class ActionEconomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        cls.policy = load_action_economy_policy(cls.registry)

    def make_kernel(self) -> WorldKernel:
        state = WorldState(
            content_version=self.registry.content_version,
            population={"player": {}, "npc:test": {}},
        )
        install_action_economy(state, self.policy)
        kernel = WorldKernel(state)
        kernel.add_invariant(action_economy_invariant)

        def study(context, command):
            spent = consume_major_action(context.state, self.policy, command)
            if not spent.success:
                return TransactionOutcome(
                    False, False, spent.code, spent.message, payload=spent.payload
                )
            context.emit("MAJOR_ACTIVITY_COMPLETED", "完成一次主要活动。", actor_ids=[command.actor_id])
            return TransactionOutcome(
                True, True, "success", "主要活动完成。", commit=True, payload=spent.payload
            )

        kernel.register_handler("STUDY", study)
        kernel.register_handler("ADVANCE_PHASE", make_advance_phase_handler(self.policy))
        return kernel

    @staticmethod
    def command(
        command_id: str,
        action_id: str,
        revision: int,
        *,
        actor_id: str = "player",
        day: int = 1,
        phase: str = "morning",
    ) -> SimulationCommand:
        return SimulationCommand(
            command_id=command_id,
            actor_id=actor_id,
            action_id=action_id,
            expected_world_revision=revision,
            issued_day=day,
            issued_phase=phase,
        )

    def test_every_actor_starts_each_phase_with_one_major_action(self):
        kernel = self.make_kernel()
        budgets = kernel.state.action_economy["actors"]
        self.assertEqual(1, budgets["player"]["major_remaining"])
        self.assertEqual(1, budgets["npc:test"]["major_remaining"])

    def test_second_major_action_is_rejected_without_partial_commit(self):
        kernel = self.make_kernel()
        first = kernel.execute(self.command("study-1", "STUDY", 1))
        self.assertTrue(first.success)
        self.assertEqual(0, kernel.state.action_economy["actors"]["player"]["major_remaining"])
        second = kernel.execute(self.command("study-2", "STUDY", 2))
        self.assertFalse(second.success)
        self.assertEqual("major_action_exhausted", second.code)
        self.assertEqual(2, kernel.state.revision)

    def test_npc_and_player_have_independent_major_actions(self):
        kernel = self.make_kernel()
        kernel.execute(self.command("player-study", "STUDY", 1))
        npc = kernel.execute(
            self.command("npc-study", "STUDY", 2, actor_id="npc:test")
        )
        self.assertTrue(npc.success)
        budgets = kernel.state.action_economy["actors"]
        self.assertEqual(0, budgets["player"]["major_remaining"])
        self.assertEqual(0, budgets["npc:test"]["major_remaining"])

    def test_advancing_phase_resets_all_budgets_and_late_night_rolls_day(self):
        kernel = self.make_kernel()
        kernel.execute(self.command("study", "STUDY", 1))
        advance = kernel.execute(self.command("advance-a", "ADVANCE_PHASE", 2))
        self.assertTrue(advance.success)
        self.assertEqual("afternoon", kernel.state.clock.phase)
        self.assertEqual(0, kernel.state.clock.minute)
        self.assertTrue(all(
            budget["major_remaining"] == 1
            and budget["phase"] == "afternoon"
            for budget in kernel.state.action_economy["actors"].values()
        ))

        revision = kernel.state.revision
        for phase, next_phase in (
            ("afternoon", "evening"),
            ("evening", "late_night"),
            ("late_night", "morning"),
        ):
            result = kernel.execute(self.command(
                f"advance-{phase}", "ADVANCE_PHASE", revision,
                day=kernel.state.clock.day, phase=phase,
            ))
            self.assertTrue(result.success)
            self.assertEqual(next_phase, kernel.state.clock.phase)
            revision += 1
        self.assertEqual(2, kernel.state.clock.day)

    def test_stale_phase_command_is_rejected(self):
        kernel = self.make_kernel()
        kernel.execute(self.command("advance", "ADVANCE_PHASE", 1))
        stale = kernel.execute(self.command("stale", "STUDY", 2))
        self.assertFalse(stale.success)
        self.assertEqual("command_clock_mismatch", stale.code)
        self.assertEqual(2, kernel.state.revision)


if __name__ == "__main__":
    unittest.main()
