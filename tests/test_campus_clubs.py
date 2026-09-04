from __future__ import annotations

import unittest

from simulation.api.server import CampusKernelBridge


def execute(bridge: CampusKernelBridge, action_id: str, parameters=None, actor_id="player"):
    snapshot = bridge.snapshot()
    clock = snapshot["clock"]
    return bridge.execute({
        "command_id": f"club-{action_id}-{actor_id}-{snapshot['revision']}",
        "actor_id": actor_id,
        "action_id": action_id,
        "target_ids": [],
        "parameters": parameters or {},
        "expected_world_revision": snapshot["revision"],
        "issued_day": clock["day"],
        "issued_phase": clock["phase"],
        "issued_minute": clock["minute"],
        "source": "player" if actor_id == "player" else "rule",
    })


def enter_club_room_in_afternoon(bridge: CampusKernelBridge) -> None:
    advanced = execute(bridge, "ADVANCE_PHASE")
    assert advanced["ok"], advanced
    travelled = execute(bridge, "FAST_TRAVEL_CAMPUS", {"destination_id": "student_life_region"})
    assert travelled["ok"], travelled
    for passage_id in ("parent:student_center", "parent:club_room_pool"):
        moved = execute(bridge, "TRAVERSE_LOCATION_PASSAGE", {"passage_id": passage_id})
        assert moved["ok"], moved


class CampusClubRuntimeTests(unittest.TestCase):
    def test_all_clubs_install_a_leader_memberships_and_resource_ledger(self):
        bridge = CampusKernelBridge(42)
        state = bridge.kernel.state
        self.assertEqual(12, len(state.organizations))
        for club in state.organizations.values():
            self.assertEqual(set(club["member_ids"]), set(club["memberships"]))
            self.assertIn(club["leader_id"], club["member_ids"])
            self.assertEqual("leader", club["memberships"][club["leader_id"]]["rank"])
            self.assertEqual(40, club["resources"]["current"])
            self.assertEqual(1, sum(
                record["rank"] == "leader" for record in club["memberships"].values()
            ))

    def test_club_view_and_membership_expose_contract_fields(self):
        bridge = CampusKernelBridge(42)
        view = bridge.snapshot()["clubs"]
        club_fields = {
            "organization_id", "name", "category", "member_count",
            "leader_id", "leader_name", "resources", "surface_skill", "team_tactic",
            "viewer_membership", "admission", "activity_slots", "activity_open_now",
        }
        membership_fields = {
            "actor_id", "rank", "contribution", "attendance_count", "absence_count",
            "joined_day", "last_attendance_marker", "promotion_history",
        }
        self.assertEqual(12, len(view))
        for payload in view.values():
            self.assertEqual(club_fields, set(payload))
        for club in bridge.kernel.state.organizations.values():
            for membership in club["memberships"].values():
                self.assertEqual(membership_fields, set(membership))

    def test_player_joins_and_club_activity_atomically_settles_attendance(self):
        bridge = CampusKernelBridge(42)
        enter_club_room_in_afternoon(bridge)
        joined = execute(bridge, "JOIN_CAMPUS_CLUB", {"club_id": "psychology_reading"})
        self.assertTrue(joined["ok"], joined)
        activity = execute(bridge, "CLUB_ACTIVITY", {
            "location_id": "club_room_pool", "club_id": "psychology_reading",
        })
        self.assertTrue(activity["ok"], activity)
        club_effect = activity["result"]["payload"]["effects"]["club"]
        self.assertTrue(club_effect["club_activity"])
        self.assertGreaterEqual(club_effect["contribution_gain"], 4)
        organization = bridge.kernel.state.organizations["psychology_reading"]
        membership = organization["memberships"]["player"]
        self.assertEqual(1, membership["attendance_count"])
        self.assertEqual(club_effect["contribution"], membership["contribution"])
        self.assertIn("CLUB_MEMBER_JOINED", [e["event_type"] for e in joined["result"]["events"]])
        self.assertIn("CLUB_ACTIVITY_ATTENDED", [e["event_type"] for e in activity["result"]["events"]])

    def test_team_tactic_requires_two_members_and_spends_shared_resources(self):
        bridge = CampusKernelBridge(42)
        enter_club_room_in_afternoon(bridge)
        club_id = "psychology_reading"
        self.assertTrue(execute(bridge, "JOIN_CAMPUS_CLUB", {"club_id": club_id})["ok"])
        club = bridge.kernel.state.organizations[club_id]
        core_id = next(
            actor_id for actor_id, record in club["memberships"].items()
            if record["rank"] in {"core_member", "leader"}
        )
        before = club["resources"]["current"]
        result = execute(bridge, "USE_CLUB_TEAM_TACTIC", {
            "club_id": club_id, "participant_ids": [core_id],
        })
        self.assertTrue(result["ok"], result)
        self.assertEqual(before - 8, result["result"]["payload"]["resource_remaining"])
        entries = bridge.chronicle(core_id, filter_name="important", limit=20)["items"]
        self.assertTrue(any(entry["event_type"] == "CLUB_TEAM_TACTIC_PREPARED" for entry in entries))

    def test_daily_upkeep_tracks_absence_and_resource_cost(self):
        bridge = CampusKernelBridge(42)
        before = {
            club_id: club["resources"]["current"]
            for club_id, club in bridge.kernel.state.organizations.items()
        }
        for _ in range(4):
            self.assertTrue(execute(bridge, "ADVANCE_PHASE")["ok"])
        state = bridge.kernel.state
        self.assertEqual(2, state.clock.day)
        for club_id, club in state.organizations.items():
            self.assertGreaterEqual(club["resources"]["current"], before[club_id] - 4)
            self.assertEqual(4, club["resources"]["spent_total"])
            self.assertEqual(2, club["last_upkeep_day"])
        self.assertTrue(any(
            record["absence_count"] >= 1
            for record in state.organizations["psychology_reading"]["memberships"].values()
        ))
        self.assertTrue(all(
            record["absence_count"] == 0
            for record in state.organizations["astronomy"]["memberships"].values()
        ))

    def test_clubs_autonomously_recruit_and_write_a_chronicle(self):
        bridge = CampusKernelBridge(42)
        before = sum(len(club["member_ids"]) for club in bridge.kernel.state.organizations.values())
        last = None
        for _ in range(4):
            last = execute(bridge, "ADVANCE_PHASE")
            self.assertTrue(last["ok"], last)
        after = sum(len(club["member_ids"]) for club in bridge.kernel.state.organizations.values())
        self.assertGreater(after, before)
        recruited_events = [
            event for event in last["result"]["events"]
            if event["event_type"] == "CLUB_MEMBER_RECRUITED"
        ]
        self.assertGreater(len(recruited_events), 1)
        recruited = recruited_events[0]
        actor_id = recruited["actor_ids"][0]
        entries = bridge.chronicle(actor_id, filter_name="important", limit=20)["items"]
        self.assertTrue(any(entry["event_type"] == "CLUB_MEMBER_RECRUITED" for entry in entries))

    def test_player_can_join_more_than_two_clubs_without_a_hard_cap(self):
        bridge = CampusKernelBridge(42)
        enter_club_room_in_afternoon(bridge)
        for club_id in ("psychology_reading", "debate", "volunteer_service"):
            joined = execute(bridge, "JOIN_CAMPUS_CLUB", {"club_id": club_id})
            self.assertTrue(joined["ok"], joined)
        self.assertEqual(
            ["psychology_reading", "debate", "volunteer_service"],
            bridge.kernel.state.population["player"]["club_ids"],
        )

    def test_explicit_activity_obeys_each_clubs_weekly_slots(self):
        bridge = CampusKernelBridge(42)
        club = bridge.kernel.state.organizations["astronomy"]
        leader_id = club["leader_id"]
        actor = bridge.kernel.state.population[leader_id]
        before_revision = bridge.snapshot()["revision"]
        result = execute(bridge, "CLUB_ACTIVITY", {
            "club_id": "astronomy", "location_id": actor["current_location_id"],
        }, actor_id=leader_id)
        self.assertFalse(result["ok"])
        self.assertEqual("club_activity_not_scheduled", result["result"]["code"])
        self.assertEqual(before_revision, bridge.snapshot()["revision"])

    def test_leader_can_atomically_transfer_role_to_a_core_member(self):
        bridge = CampusKernelBridge(42)
        club_id = "astronomy"
        club = bridge.kernel.state.organizations[club_id]
        leader_id = club["leader_id"]
        target_id = next(
            actor_id for actor_id, membership in club["memberships"].items()
            if membership["rank"] == "core_member"
        )
        result = execute(
            bridge,
            "TRANSFER_CLUB_LEADERSHIP",
            {"club_id": club_id, "new_leader_id": target_id},
            actor_id=leader_id,
        )
        self.assertTrue(result["ok"], result)
        final = bridge.kernel.state.organizations[club_id]
        self.assertEqual(target_id, final["leader_id"])
        self.assertEqual("leader", final["memberships"][target_id]["rank"])
        self.assertEqual("core_member", final["memberships"][leader_id]["rank"])


if __name__ == "__main__":
    unittest.main()
