from __future__ import annotations

import unittest
from copy import deepcopy

from simulation.api.server import CampusKernelBridge
from simulation.systems import campus_combat_invariant
from tests.test_campus_combat_deployment import enter_with_owned_night_task, execute
from tests.test_campus_combat_rounds import deploy_and_start


class CampusRetreatTests(unittest.TestCase):
    def _retreat(self, bridge: CampusKernelBridge, battle: dict, marker: str = "retreat") -> dict:
        return execute(bridge, "RETREAT_CARD_COMBAT", {
            "battle_id": battle["battle_id"],
            "expected_battle_revision": battle["revision"],
        }, marker=marker)

    def test_survivors_take_pursuit_damage_and_reopen_unexpired_task(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        task_id = battle["situation_id"]
        before_health = bridge.kernel._state.population["player"]["vitals"]["health"]
        before_clock = vars(bridge.kernel._state.clock).copy()
        before_inventory = deepcopy(bridge.kernel._state.inventories["actors"]["player"])
        before_pollution = bridge.kernel._state.situations["night_world"][
            "actor_states"
        ]["player"]["pollution"]

        result = self._retreat(bridge, battle)
        task = bridge.kernel._state.tasks[task_id]

        self.assertTrue(result["ok"], result)
        self.assertEqual("escaped", result["result"]["payload"]["result"])
        self.assertEqual(before_clock, vars(bridge.kernel._state.clock))
        self.assertLess(
            bridge.kernel._state.population["player"]["vitals"]["health"], before_health
        )
        persistent_pollution = bridge.kernel._state.situations["night_world"][
            "actor_states"
        ]["player"]["pollution"]
        self.assertGreater(persistent_pollution, before_pollution)
        self.assertEqual(
            persistent_pollution,
            bridge.kernel._state.battles[battle["battle_id"]]["pollution"]["player"],
        )
        self.assertEqual(before_inventory, bridge.kernel._state.inventories["actors"]["player"])
        self.assertEqual("open", task["state"])
        self.assertIsNone(task["assignee_id"])
        self.assertNotIn("active_forum_task_id", bridge.kernel._state.population["player"])
        self.assertIsNone(result["snapshot"]["combat"]["active_battle"])
        self.assertEqual("surface", result["snapshot"]["night_world"]["current_layer"])
        stored = bridge.kernel._state.battles[battle["battle_id"]]
        self.assertEqual("resolved", stored["phase"])
        self.assertEqual("escaped", stored["result"])
        self.assertTrue(any(
            event["event_type"] == "COMBAT_PARTY_RETREATED"
            for event in result["result"]["events"]
        ))
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel.state)))

    def test_expired_task_is_not_reopened_after_retreat(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        task_id = battle["situation_id"]
        task = bridge.kernel._state.tasks[task_id]
        task["expires_day"] = 1
        bridge.kernel._state.clock.day = 2
        from simulation.systems.campus_forum_attention import _ledger
        _ledger(bridge.kernel._state)  # Keep this explicit time-jump fixture coherent.
        for budget in bridge.kernel._state.action_economy["actors"].values():
            budget["day"] = 2
        for actor in bridge.kernel._state.population.values():
            for field in ("current_activity", "current_decision"):
                if isinstance(actor.get(field), dict):
                    actor[field]["day"] = 2

        result = self._retreat(bridge, battle, "retreat-expired")
        task = bridge.kernel._state.tasks[task_id]

        self.assertTrue(result["ok"], result)
        self.assertEqual("expired", task["state"])
        self.assertIsNone(task["assignee_id"])
        self.assertFalse(result["result"]["payload"]["task_reopened"])

    def test_pursuit_defeat_uses_existing_overnight_rescue(self):
        bridge = CampusKernelBridge(42)
        battle = deploy_and_start(bridge)
        task_id = battle["situation_id"]
        bridge.kernel._state.population["player"]["vitals"]["health"] = 1
        before_inventory = deepcopy(bridge.kernel._state.inventories["actors"]["player"])

        result = self._retreat(bridge, battle, "retreat-defeat")
        task = bridge.kernel._state.tasks[task_id]

        self.assertTrue(result["ok"], result)
        self.assertEqual("defeat", result["result"]["payload"]["result"])
        self.assertEqual(2, result["snapshot"]["clock"]["day"])
        self.assertEqual("morning", result["snapshot"]["clock"]["phase"])
        self.assertEqual("failed", task["state"])
        player = bridge.kernel._state.population["player"]
        self.assertEqual(player["vitals"]["max_health"], player["vitals"]["health"])
        self.assertEqual(player["vitals"]["max_focus"], player["vitals"]["focus"])
        self.assertEqual(before_inventory, bridge.kernel._state.inventories["actors"]["player"])
        self.assertEqual(player["home_location_id"], player["current_location_id"])
        self.assertEqual([], list(campus_combat_invariant(bridge.kernel.state)))

    def test_wrong_phase_rejects_retreat_without_partial_mutation(self):
        bridge = CampusKernelBridge(42)
        task = enter_with_owned_night_task(bridge)
        prepared = execute(
            bridge, "START_BATTLE_PREPARATION", {"task_id": task["task_id"]},
            marker="retreat-prepare-only",
        )
        stored = prepared["snapshot"]["combat"]["active_battle"]
        before_clock = vars(bridge.kernel.state.clock).copy()
        before_revision = bridge.kernel.state.battles[stored["battle_id"]]["revision"]
        before_task = bridge.kernel.state.tasks[stored["situation_id"]]["state"]

        blocked = self._retreat(bridge, stored, "retreat-wrong-phase")

        self.assertFalse(blocked["ok"])
        self.assertEqual("wrong_battle_phase", blocked["result"]["code"])
        self.assertEqual(before_clock, vars(bridge.kernel.state.clock))
        self.assertEqual(
            before_revision, bridge.kernel.state.battles[stored["battle_id"]]["revision"]
        )
        self.assertEqual(before_task, bridge.kernel.state.tasks[stored["situation_id"]]["state"])


if __name__ == "__main__":
    unittest.main()
