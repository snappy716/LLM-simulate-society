from __future__ import annotations

import json
import unittest
from pathlib import Path

from simulation.api.server import CampusKernelBridge
from simulation.systems import (
    ContentRegistry,
    campus_night_world_invariant,
    load_campus_night_world_policy,
    moon_phase_for_day,
)


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


def execute(bridge: CampusKernelBridge, action_id: str, actor_id: str, marker: str) -> dict:
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"night-{marker}-{snapshot['revision']}",
        "actor_id": actor_id,
        "action_id": action_id,
        "target_ids": [],
        "parameters": {},
        "expected_world_revision": snapshot["revision"],
        "issued_day": clock["day"],
        "issued_phase": clock["phase"],
        "issued_minute": clock["minute"],
        "source": "player" if actor_id == "player" else "rule",
    })


class CampusNightWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        cls.policy = load_campus_night_world_policy(cls.registry)

    def test_moon_content_covers_demo_and_wraps_after_day_28(self):
        ids = [moon_phase_for_day(self.policy, day)["id"] for day in range(1, 29)]
        self.assertEqual("thin_crescent", ids[0])
        self.assertEqual("polluted_full_moon", ids[-1])
        self.assertEqual(100, moon_phase_for_day(self.policy, 28)["intensity"])
        self.assertEqual("thin_crescent", moon_phase_for_day(self.policy, 29)["id"])

    def test_player_entry_is_night_only_free_and_reversible(self):
        bridge = CampusKernelBridge(101)
        rejected = execute(bridge, "ENTER_NIGHT_WORLD", "player", "morning")
        self.assertFalse(rejected["ok"])
        self.assertEqual("invalid_phase", rejected["result"]["code"])
        execute(bridge, "ADVANCE_PHASE", "player", "afternoon")
        execute(bridge, "ADVANCE_PHASE", "player", "evening")
        before = bridge.snapshot()["player"]["action_budget"]["major_remaining"]
        entered = execute(bridge, "ENTER_NIGHT_WORLD", "player", "enter")
        self.assertTrue(entered["ok"])
        self.assertEqual("night", entered["snapshot"]["night_world"]["current_layer"])
        self.assertEqual(2, entered["snapshot"]["night_world"]["pollution"])
        self.assertEqual("free", entered["result"]["payload"]["action_class"])
        self.assertEqual(before, entered["snapshot"]["player"]["action_budget"]["major_remaining"])
        exited = execute(bridge, "EXIT_NIGHT_WORLD", "player", "exit")
        self.assertTrue(exited["ok"])
        self.assertEqual("surface", exited["snapshot"]["night_world"]["current_layer"])
        self.assertEqual(2, exited["snapshot"]["night_world"]["pollution"])

    def test_exposure_auto_exit_and_surface_recovery_share_one_state(self):
        bridge = CampusKernelBridge(103)
        execute(bridge, "ADVANCE_PHASE", "player", "afternoon")
        execute(bridge, "ADVANCE_PHASE", "player", "evening")
        execute(bridge, "ENTER_NIGHT_WORLD", "player", "enter")
        late = execute(bridge, "ADVANCE_PHASE", "player", "late")
        self.assertEqual("night", late["snapshot"]["night_world"]["current_layer"])
        self.assertEqual(3, late["snapshot"]["night_world"]["pollution"])
        morning = execute(bridge, "ADVANCE_PHASE", "player", "morning")
        self.assertEqual("surface", morning["snapshot"]["night_world"]["current_layer"])
        self.assertEqual(1, morning["snapshot"]["night_world"]["pollution"])
        phase_execution = morning["result"]["payload"]["phase_execution"]
        self.assertGreaterEqual(phase_execution["night_auto_exit_count"], 1)
        self.assertGreaterEqual(phase_execution["pollution_recovery_count"], 1)
        self.assertEqual([], list(campus_night_world_invariant(bridge.kernel.state)))

    def test_npc_entry_requires_capable_or_willing_access(self):
        bridge = CampusKernelBridge(105)
        execute(bridge, "ADVANCE_PHASE", "player", "afternoon")
        execute(bridge, "ADVANCE_PHASE", "player", "evening")
        state = bridge.kernel._state
        sensitive_id = next(
            actor_id for actor_id, actor in state.population.items()
            if actor_id != "player" and actor.get("night_access") == "sensitive"
        )
        capable_id = next(
            actor_id for actor_id, actor in state.population.items()
            if actor_id != "player" and actor.get("night_access") == "capable"
        )
        blocked = execute(bridge, "ENTER_NIGHT_WORLD", sensitive_id, "sensitive")
        self.assertFalse(blocked["ok"])
        self.assertEqual("insufficient_night_access", blocked["result"]["code"])
        entered = execute(bridge, "ENTER_NIGHT_WORLD", capable_id, "capable")
        self.assertTrue(entered["ok"])
        self.assertEqual(
            "night",
            bridge.kernel._state.situations["night_world"]["actor_states"][capable_id]["layer"],
        )

    def test_pollution_lock_and_contract_shape(self):
        bridge = CampusKernelBridge(107)
        aggregate = bridge.kernel._state.situations["night_world"]
        aggregate["actor_states"]["player"]["pollution"] = self.policy.pollution_lock_threshold
        execute(bridge, "ADVANCE_PHASE", "player", "afternoon")
        execute(bridge, "ADVANCE_PHASE", "player", "evening")
        blocked = execute(bridge, "ENTER_NIGHT_WORLD", "player", "pollution")
        self.assertFalse(blocked["ok"])
        self.assertEqual("pollution_lock", blocked["result"]["code"])
        schema = json.loads(
            (REPOSITORY_DIR / "contracts/night_world_state.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), set(aggregate))


if __name__ == "__main__":
    unittest.main()
