from __future__ import annotations

import unittest

from simulation.api.server import CampusKernelBridge


def execute(bridge: CampusKernelBridge, action_id: str, parameters=None, command_id=None):
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": command_id or f"social-{action_id}-{snapshot['revision']}",
        "actor_id": "player",
        "action_id": action_id,
        "target_ids": [],
        "parameters": parameters or {},
        "expected_world_revision": snapshot["revision"],
        "issued_day": clock["day"],
        "issued_phase": clock["phase"],
        "issued_minute": clock["minute"],
        "source": "player",
    })


def claim(bridge: CampusKernelBridge, task: dict) -> None:
    viewed = execute(bridge, "VIEW_FORUM_TASK", {"task_id": task["task_id"]})
    assert viewed["ok"], viewed
    current = bridge.snapshot()["tasks"][task["task_id"]]
    claimed = execute(bridge, "CLAIM_FORUM_TASK", {
        "task_id": task["task_id"],
        "expected_task_revision": current["lock_revision"],
    })
    assert claimed["ok"], claimed


def travel_and_complete(bridge: CampusKernelBridge, task: dict) -> dict:
    travelled = execute(
        bridge,
        "FAST_TRAVEL_CAMPUS",
        {"destination_id": task["execution_region_id"]},
    )
    assert travelled["ok"], travelled
    return execute(bridge, "COMPLETE_FORUM_TASK", {"task_id": task["task_id"]})


class CampusSocialConsequenceTests(unittest.TestCase):
    def test_clubs_install_members_and_private_reputation_ledgers(self):
        bridge = CampusKernelBridge(42)
        state = bridge.kernel.state
        self.assertEqual(12, len(state.organizations))
        self.assertEqual(set(state.population), set(state.relationships))
        for organization_id, organization in state.organizations.items():
            for actor_id in organization["member_ids"]:
                self.assertIn(organization_id, state.population[actor_id]["club_ids"])
        self.assertEqual({}, bridge.snapshot()["social"]["player_organizations"])

    def test_completed_task_atomically_changes_issuer_relation_and_club_reputation(self):
        bridge = CampusKernelBridge(3)
        task = next(
            task for task in bridge.snapshot()["tasks"].values()
            if task.get("organization_id") and "morning" in task["allowed_phases"]
        )
        claim(bridge, task)
        result = travel_and_complete(bridge, task)
        self.assertTrue(result["ok"], result)
        final = bridge.snapshot()
        completed = final["tasks"][task["task_id"]]
        self.assertEqual("completed", completed["state"])
        social_result = completed["social_result"]
        self.assertEqual(5, social_result["relationship_delta"]["trust"])
        self.assertEqual(4, social_result["organization"]["reputation_delta"])
        issuer_relation = final["social"]["player_relationships"][task["issuer_id"]]
        self.assertEqual(55, issuer_relation["trust"])
        organization = final["social"]["player_organizations"][task["organization_id"]]
        self.assertEqual(4, organization["reputation"])
        self.assertEqual(1, organization["completed_task_count"])
        self.assertEqual(social_result, result["result"]["payload"]["social_result"])

    def test_abandon_reopens_task_but_records_social_cost(self):
        bridge = CampusKernelBridge(3)
        task = next(
            task for task in bridge.snapshot()["tasks"].values()
            if task.get("organization_id")
        )
        claim(bridge, task)
        abandoned = execute(bridge, "ABANDON_FORUM_TASK", {"task_id": task["task_id"]})
        self.assertTrue(abandoned["ok"], abandoned)
        final = bridge.snapshot()
        reopened = final["tasks"][task["task_id"]]
        self.assertEqual("open", reopened["state"])
        relation = final["social"]["player_relationships"][task["issuer_id"]]
        self.assertEqual(46, relation["trust"])
        self.assertEqual(3, relation["suspicion"])
        organization = final["social"]["player_organizations"][task["organization_id"]]
        self.assertEqual(-2, organization["reputation"])

    def test_completed_parent_guarantees_single_run_follow_up_next_morning(self):
        bridge = CampusKernelBridge(3)
        task = next(
            task for task in bridge.snapshot()["tasks"].values()
            if task["template_id"] == "library_shelf_help"
        )
        claim(bridge, task)
        completed = travel_and_complete(bridge, task)
        self.assertTrue(completed["ok"], completed)
        self.assertEqual(
            ["archive_damage_follow_up"],
            completed["result"]["payload"]["unlocked_follow_up_template_ids"],
        )
        for index in range(4):
            advanced = execute(bridge, "ADVANCE_PHASE", command_id=f"social-next-{index}")
            self.assertTrue(advanced["ok"], advanced)
        follow_ups = [
            value for value in bridge.snapshot()["tasks"].values()
            if value["template_id"] == "archive_damage_follow_up"
        ]
        self.assertEqual(1, len(follow_ups))
        self.assertEqual("library_shelf_help", follow_ups[0]["chain_parent_template_id"])

    def test_npc_task_completions_also_leave_social_history(self):
        bridge = CampusKernelBridge(42)
        for index in range(8):
            advanced = execute(bridge, "ADVANCE_PHASE", command_id=f"npc-social-{index}")
            self.assertTrue(advanced["ok"], advanced)
        state = bridge.kernel.state
        completed = [task for task in state.tasks.values() if task.get("state") == "completed"]
        self.assertTrue(completed)
        self.assertTrue(all(task.get("social_result") for task in completed))
        self.assertTrue(any(
            organization.get("reputation_by_actor")
            for organization in state.organizations.values()
        ))


if __name__ == "__main__":
    unittest.main()
