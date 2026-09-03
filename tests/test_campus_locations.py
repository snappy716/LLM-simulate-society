from __future__ import annotations

import unittest
from pathlib import Path

from simulation.actions import SimulationCommand
from simulation.domain import ClockState, InstancePolicy, TransitionKind, WorldState
from simulation.systems import (
    ContentRegistry,
    WorldKernel,
    install_campus_places,
    load_campus_location_graph,
    make_fast_travel_handler,
    make_traverse_location_handler,
)


REPOSITORY_DIR = Path(__file__).resolve().parents[1]


class CampusLocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        cls.graph = load_campus_location_graph(cls.registry)

    def test_large_map_has_regions_buildings_and_enterable_interiors(self):
        self.assertEqual(10, len(self.graph.regions))
        self.assertEqual(53, len(self.graph.locations))
        self.assertEqual(16, len(self.graph.templates))
        self.assertGreaterEqual(
            len([item for item in self.graph.locations.values() if item.kind == "building"]),
            20,
        )
        self.assertGreaterEqual(
            len([item for item in self.graph.locations.values() if item.interior_template_id]),
            30,
        )

    def test_classrooms_and_dorm_rooms_exist_as_pooled_enterable_groups(self):
        for location_id in (
            "humanities_classroom_pool",
            "science_classroom_pool",
            "east_dorm_room_pool",
            "west_dorm_room_pool",
        ):
            location = self.graph.locations[location_id]
            self.assertEqual(InstancePolicy.POOLED.value, location.instance_policy)
            self.assertGreater(location.pool_size, 1)
            self.assertIsNotNone(location.interior_template_id)

    def test_region_roads_are_continuous_and_buildings_are_scene_entrances(self):
        road = self.graph.passages["road_gate_to_student_life"]
        self.assertEqual(TransitionKind.CONTINUOUS_BOUNDARY.value, road.transition_kind)
        entrance = self.graph.passages["parent:humanities_psychology_building"]
        self.assertEqual(TransitionKind.BUILDING_ENTRANCE.value, entrance.transition_kind)
        self.assertEqual("stairs", self.graph.locations["humanities_psychology_building"].entrance_style)
        self.assertEqual(
            "outside:humanities_psychology_building:entrance",
            entrance.from_anchor_id,
        )
        self.assertEqual(
            "inside:humanities_psychology_building:entrance",
            entrance.to_anchor_id,
        )
        room_door = self.graph.passages["parent:humanities_classroom_pool"]
        self.assertEqual(TransitionKind.INTERIOR_DOOR.value, room_door.transition_kind)

    def test_outdoor_regions_form_a_connected_walkable_map(self):
        for destination_id in self.graph.regions:
            route = self.graph.shortest_route(
                "south_gate_region",
                destination_id,
                phase="morning",
                access_tags=["campus_member"],
            )
            self.assertIsNotNone(route, destination_id)

    def test_open_hours_and_access_tags_gate_entry_but_never_trap_actor(self):
        no_access = self.graph.shortest_route(
            "university_library",
            "library_special_archive",
            phase="morning",
        )
        self.assertIsNone(no_access)
        allowed = self.graph.shortest_route(
            "university_library",
            "library_special_archive",
            phase="morning",
            access_tags=["archive_access"],
        )
        self.assertIsNotNone(allowed)

        closed_entry = self.graph.shortest_route(
            "administration_building",
            "registrar_office",
            phase="evening",
        )
        self.assertIsNone(closed_entry)
        exit_route = self.graph.shortest_route(
            "registrar_office",
            "central_region",
            phase="evening",
        )
        self.assertIsNotNone(exit_route)

    def test_fixed_route_minutes_are_deterministic(self):
        route = self.graph.shortest_route(
            "south_gate_region",
            "psychology_support_room",
            phase="morning",
            access_tags=["campus_member"],
        )
        self.assertIsNotNone(route)
        assert route is not None
        self.assertEqual(25, route.total_minutes)
        self.assertEqual(
            "building_entrance",
            self.graph.passages[route.steps[-2].passage_id].transition_kind,
        )
        self.assertEqual("interior_door", self.graph.passages[route.steps[-1].passage_id].transition_kind)

    def test_graph_projects_to_authoritative_world_state(self):
        state = WorldState(content_version=self.registry.content_version)
        install_campus_places(state, self.graph)
        state.require_valid()
        self.assertEqual(63, len(state.places))
        self.assertEqual("region", state.places["central_region"]["node_type"])
        self.assertEqual("location", state.places["campus_hospital"]["node_type"])
        self.assertIn("parent:campus_hospital", state.metadata["campus_passages"])
        self.assertEqual(
            "interior_building_lobby",
            state.metadata["interior_templates"]["building_lobby"]["presentation_key"],
        )


class CampusTraversalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        cls.graph = load_campus_location_graph(registry)
        cls.content_version = registry.content_version

    def make_kernel(self, location_id: str, *, minute: int = 0, access_tags=()):
        state = WorldState(
            content_version=self.content_version,
            clock=ClockState(day=1, phase="morning", minute=minute),
            population={
                "player": {
                    "current_location_id": location_id,
                    "access_tags": list(access_tags),
                }
            },
        )
        install_campus_places(state, self.graph)
        kernel = WorldKernel(state)
        kernel.register_handler(
            "TRAVERSE_LOCATION_PASSAGE",
            make_traverse_location_handler(self.graph),
        )
        return kernel

    @staticmethod
    def request(
        command_id: str,
        passage_id: str,
        revision: int = 1,
        *,
        day: int = 1,
        phase: str = "morning",
    ):
        return SimulationCommand(
            command_id=command_id,
            actor_id="player",
            action_id="TRAVERSE_LOCATION_PASSAGE",
            expected_world_revision=revision,
            parameters={"passage_id": passage_id},
            issued_day=day,
            issued_phase=phase,
        )

    def test_crossing_road_keeps_outdoor_scene_continuous(self):
        kernel = self.make_kernel("south_gate_region")
        result = kernel.execute(self.request("road", "road_gate_to_student_life"))
        self.assertTrue(result.success)
        self.assertEqual("student_life_region", kernel.state.population["player"]["current_location_id"])
        self.assertEqual(0, kernel.state.clock.minute)
        self.assertEqual("continuous_boundary", result.payload["transition_kind"])
        self.assertFalse(result.payload["requires_scene_change"])
        self.assertEqual("campus_outdoor", result.payload["presentation_key"])

    def test_campus_map_fast_travel_uses_graph_and_remains_free(self):
        kernel = self.make_kernel("south_gate_region")
        kernel.register_handler("FAST_TRAVEL_CAMPUS", make_fast_travel_handler(self.graph))
        command = SimulationCommand(
            command_id="map-to-west-dorm",
            actor_id="player",
            action_id="FAST_TRAVEL_CAMPUS",
            expected_world_revision=1,
            parameters={"destination_id": "west_dorm_region"},
            issued_day=1,
            issued_phase="morning",
        )
        result = kernel.execute(command)
        self.assertTrue(result.success)
        self.assertTrue(result.payload["free_movement"])
        self.assertGreater(len(result.payload["route"]), 1)
        self.assertEqual("west_dorm_region", kernel.state.population["player"]["current_location_id"])
        self.assertEqual(0, kernel.state.clock.minute)

    def test_campus_map_rejects_interior_as_direct_destination(self):
        kernel = self.make_kernel("south_gate_region")
        kernel.register_handler("FAST_TRAVEL_CAMPUS", make_fast_travel_handler(self.graph))
        command = SimulationCommand(
            command_id="map-to-archive",
            actor_id="player",
            action_id="FAST_TRAVEL_CAMPUS",
            expected_world_revision=1,
            parameters={"destination_id": "library_special_archive"},
            issued_day=1,
            issued_phase="morning",
        )
        result = kernel.execute(command)
        self.assertFalse(result.success)
        self.assertEqual("invalid_map_destination", result.code)
        self.assertEqual(1, kernel.state.revision)

    def test_stairs_entrance_requests_building_scene(self):
        kernel = self.make_kernel("humanities_psychology_region")
        result = kernel.execute(
            self.request("stairs", "parent:humanities_psychology_building")
        )
        self.assertTrue(result.success)
        self.assertEqual("building_entrance", result.payload["transition_kind"])
        self.assertTrue(result.payload["requires_scene_change"])
        self.assertEqual("interior_building_lobby", result.payload["presentation_key"])
        self.assertEqual(
            "inside:humanities_psychology_building:entrance",
            result.payload["arrival_anchor_id"],
        )

    def test_room_group_uses_reusable_interior_template(self):
        kernel = self.make_kernel(
            "humanities_psychology_building", access_tags=["campus_member"]
        )
        result = kernel.execute(
            self.request("classroom", "parent:humanities_classroom_pool")
        )
        self.assertTrue(result.success)
        self.assertEqual("pooled", result.payload["instance_policy"])
        self.assertEqual("interior_classroom_standard", result.payload["presentation_key"])

    def test_closed_or_unauthorized_entry_does_not_commit(self):
        state = WorldState(
            content_version=self.content_version,
            clock=ClockState(day=1, phase="evening", minute=0),
            population={"player": {"current_location_id": "administration_building", "access_tags": []}},
        )
        install_campus_places(state, self.graph)
        kernel = WorldKernel(state)
        kernel.register_handler("TRAVERSE_LOCATION_PASSAGE", make_traverse_location_handler(self.graph))
        closed = kernel.execute(self.request(
            "closed", "parent:registrar_office", phase="evening"
        ))
        self.assertFalse(closed.success)
        self.assertEqual("location_closed", closed.code)
        self.assertEqual(1, kernel.state.revision)

        archive_kernel = self.make_kernel("university_library")
        denied = archive_kernel.execute(
            self.request("denied", "parent:library_special_archive")
        )
        self.assertEqual("access_denied", denied.code)
        self.assertEqual("university_library", archive_kernel.state.population["player"]["current_location_id"])

    def test_actor_can_exit_after_location_closes(self):
        state = WorldState(
            content_version=self.content_version,
            clock=ClockState(day=1, phase="evening", minute=0),
            population={"player": {"current_location_id": "registrar_office", "access_tags": []}},
        )
        install_campus_places(state, self.graph)
        kernel = WorldKernel(state)
        kernel.register_handler("TRAVERSE_LOCATION_PASSAGE", make_traverse_location_handler(self.graph))
        result = kernel.execute(self.request(
            "exit", "parent:registrar_office", phase="evening"
        ))
        self.assertTrue(result.success)
        self.assertEqual("administration_building", kernel.state.population["player"]["current_location_id"])
        self.assertEqual(
            "outside:registrar_office:entrance",
            result.payload["arrival_anchor_id"],
        )

    def test_free_movement_does_not_consume_phase_time_and_remote_passage_is_rejected(self):
        late = self.make_kernel("south_gate_region", minute=355)
        result = late.execute(self.request("late", "road_gate_to_student_life"))
        self.assertTrue(result.success)
        self.assertEqual(355, late.state.clock.minute)

        remote = self.make_kernel("central_region")
        result = remote.execute(self.request("remote", "road_gate_to_student_life"))
        self.assertEqual("passage_absent", result.code)

    def test_stale_phase_movement_is_rejected_without_commit(self):
        kernel = self.make_kernel("south_gate_region")
        stale = self.request(
            "stale-road", "road_gate_to_student_life", phase="afternoon"
        )
        result = kernel.execute(stale)
        self.assertEqual("command_clock_mismatch", result.code)
        self.assertEqual("south_gate_region", kernel.state.population["player"]["current_location_id"])
        self.assertEqual(1, kernel.state.revision)


if __name__ == "__main__":
    unittest.main()
