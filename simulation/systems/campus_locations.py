"""Load campus locations and execute authoritative boundary/entrance traversal."""
from __future__ import annotations

from typing import Iterable

from simulation.domain.locations import (
    CampusLocation,
    CampusLocationGraph,
    CampusPassage,
    CampusRegion,
    InteriorTemplate,
)
from simulation.domain.world_state import WorldState
from simulation.systems.transactions import TransactionOutcome
from simulation.systems.content_registry import ContentRegistry


def load_campus_location_graph(registry: ContentRegistry) -> CampusLocationGraph:
    regions = [
        CampusRegion(
            region_id=item["id"],
            name=item["name"],
            map_cell=tuple(item["map_cell"]),
            tags=tuple(item.get("tags", ())),
        )
        for item in registry.all("campus_region").values()
    ]
    templates = [
        InteriorTemplate(
            template_id=item["id"],
            name=item["name"],
            presentation_key=item["presentation_key"],
            interaction_slots=tuple(item.get("interaction_slots", ())),
        )
        for item in registry.all("interior_template").values()
    ]
    locations = [
        CampusLocation(
            location_id=item["id"],
            name=item["name"],
            kind=item["kind"],
            region_id=item["region_id"],
            parent_id=item["parent_id"],
            capacity=int(item["capacity"]),
            entry_minutes=int(item.get("entry_minutes", 2)),
            open_phases=tuple(item["open_phases"]),
            tags=tuple(item.get("tags", ())),
            access_tags=tuple(item.get("access_tags", ())),
            interior_template_id=(
                item.get("interior_template_id")
                or ("building_lobby" if item["kind"] == "building" else None)
            ),
            instance_policy=item.get("instance_policy", "fixed"),
            pool_size=int(item.get("pool_size", 1)),
            supports_night_layer=bool(item.get("supports_night_layer", True)),
            map_cell=tuple(item["map_cell"]) if item.get("map_cell") is not None else None,
            entrance_style=item.get("entrance_style", "level"),
        )
        for item in registry.all("campus_location").values()
    ]
    passages = [
        CampusPassage(
            passage_id=item["id"],
            from_id=item["from_id"],
            to_id=item["to_id"],
            travel_minutes=int(item["travel_minutes"]),
            bidirectional=bool(item.get("bidirectional", True)),
            open_phases=tuple(item.get("open_phases", ("morning", "afternoon", "evening", "late_night"))),
            required_access_tags=tuple(item.get("required_access_tags", ())),
            tags=tuple(item.get("tags", ())),
            transition_kind=item.get("transition_kind", "continuous_boundary"),
            exit_always_allowed=bool(item.get("exit_always_allowed", False)),
            from_anchor_id=item.get(
                "from_anchor_id", f"region:{item['from_id']}:entry:{item['id']}"
            ),
            to_anchor_id=item.get(
                "to_anchor_id", f"region:{item['to_id']}:entry:{item['id']}"
            ),
        )
        for item in registry.all("campus_passage").values()
    ]
    return CampusLocationGraph(regions, locations, templates, passages)


def install_campus_places(state: WorldState, graph: CampusLocationGraph) -> None:
    if state.places:
        raise ValueError("world places aggregate is already initialized")
    state.places.update(graph.state_projection())
    state.metadata["campus_passages"] = {
        passage_id: {
            "passage_id": passage.passage_id,
            "from_id": passage.from_id,
            "to_id": passage.to_id,
            "travel_minutes": passage.travel_minutes,
            "bidirectional": passage.bidirectional,
            "open_phases": list(passage.open_phases),
            "required_access_tags": list(passage.required_access_tags),
            "tags": list(passage.tags),
            "transition_kind": passage.transition_kind,
            "exit_always_allowed": passage.exit_always_allowed,
            "from_anchor_id": passage.from_anchor_id,
            "to_anchor_id": passage.to_anchor_id,
        }
        for passage_id, passage in graph.passages.items()
    }
    state.metadata["interior_templates"] = {
        template_id: {
            "template_id": template.template_id,
            "name": template.name,
            "presentation_key": template.presentation_key,
            "interaction_slots": list(template.interaction_slots),
        }
        for template_id, template in graph.templates.items()
    }


def make_traverse_location_handler(graph: CampusLocationGraph):
    """Build the shared player/NPC handler for a mapped Godot transition trigger."""

    def traverse(context, command):
        actor = context.state.population.get(command.actor_id)
        if not isinstance(actor, dict):
            return TransactionOutcome(False, False, "unknown_actor", "行动者不存在。")
        active_battle_id = context.state.metadata.get("campus_combat", {}).get(
            "active_battle_by_actor", {}
        ).get(command.actor_id)
        active_battle = context.state.battles.get(str(active_battle_id or ""), {})
        if active_battle_id and isinstance(active_battle, dict) and active_battle.get("phase") != "resolved":
            return TransactionOutcome(
                False, False, "combat_active", "请先取消战斗准备或完成当前战斗。"
            )
        if (
            command.issued_day != context.state.clock.day
            or command.issued_phase != context.state.clock.phase
        ):
            return TransactionOutcome(
                False, False, "command_clock_mismatch", "移动指令所属的日期或时段已经过期。"
            )
        passage_id = command.parameters.get("passage_id")
        if not isinstance(passage_id, str) or not passage_id:
            return TransactionOutcome(False, False, "missing_passage", "通行命令缺少 passage_id。")
        passage = graph.passages.get(passage_id)
        if passage is None:
            return TransactionOutcome(False, False, "unknown_passage", "没有找到这个道路边界或入口。")
        current_id = actor.get("current_location_id")
        if current_id == passage.from_id:
            destination_id = passage.to_id
            forward = True
        elif current_id == passage.to_id and passage.bidirectional:
            destination_id = passage.from_id
            forward = False
        else:
            return TransactionOutcome(False, False, "passage_absent", "行动者不在这个入口或边界旁。")

        access_tags = set(actor.get("access_tags", ()))
        normally_allowed = (
            context.state.clock.phase in passage.open_phases
            and set(passage.required_access_tags).issubset(access_tags)
            and graph.is_open(destination_id, context.state.clock.phase)
        )
        if not normally_allowed and not (not forward and passage.exit_always_allowed):
            if not set(passage.required_access_tags).issubset(access_tags):
                return TransactionOutcome(False, False, "access_denied", "行动者没有进入该地点的权限。")
            return TransactionOutcome(False, False, "location_closed", "该入口目前关闭。")
        actor["current_location_id"] = destination_id
        destination = graph.locations.get(destination_id)
        presentation_key = "campus_outdoor"
        instance_policy = "fixed"
        if destination is not None:
            instance_policy = destination.instance_policy
            if destination.interior_template_id:
                presentation_key = graph.templates[destination.interior_template_id].presentation_key
        requires_scene_change = passage.transition_kind != "continuous_boundary"
        arrival_anchor_id = passage.to_anchor_id if forward else passage.from_anchor_id
        context.emit(
            "ACTOR_LOCATION_CHANGED",
            f"{command.actor_id} 前往 {destination_id}。",
            actor_ids=[command.actor_id],
            scene_id=destination_id,
            payload={
                "passage_id": passage_id,
                "from_id": current_id,
                "to_id": destination_id,
                "travel_minutes": passage.travel_minutes,
                "transition_kind": passage.transition_kind,
                "requires_scene_change": requires_scene_change,
                "presentation_key": presentation_key,
                "instance_policy": instance_policy,
                "direction": "forward" if forward else "reverse",
                "arrival_anchor_id": arrival_anchor_id,
            },
            knowledge_tags=["location", *passage.tags],
        )
        return TransactionOutcome(
            True,
            True,
            "success",
            "地点切换完成。",
            commit=True,
            payload={
                "current_location_id": destination_id,
                "transition_kind": passage.transition_kind,
                "requires_scene_change": requires_scene_change,
                "presentation_key": presentation_key,
                "instance_policy": instance_policy,
                "arrival_anchor_id": arrival_anchor_id,
            },
        )

    return traverse


def make_fast_travel_handler(graph: CampusLocationGraph):
    """Build free campus-map travel without bypassing the authoritative graph."""

    def fast_travel(context, command):
        actor = context.state.population.get(command.actor_id)
        if not isinstance(actor, dict):
            return TransactionOutcome(False, False, "unknown_actor", "行动者不存在。")
        active_battle_id = context.state.metadata.get("campus_combat", {}).get(
            "active_battle_by_actor", {}
        ).get(command.actor_id)
        active_battle = context.state.battles.get(str(active_battle_id or ""), {})
        if active_battle_id and isinstance(active_battle, dict) and active_battle.get("phase") != "resolved":
            return TransactionOutcome(
                False, False, "combat_active", "请先取消战斗准备或完成当前战斗。"
            )
        if (
            command.issued_day != context.state.clock.day
            or command.issued_phase != context.state.clock.phase
        ):
            return TransactionOutcome(
                False, False, "command_clock_mismatch", "移动指令所属的日期或时段已经过期。"
            )
        destination_id = command.parameters.get("destination_id")
        if not isinstance(destination_id, str) or not destination_id:
            return TransactionOutcome(False, False, "missing_destination", "校园地图没有指定目的地。")
        if destination_id not in graph.regions:
            return TransactionOutcome(False, False, "invalid_map_destination", "校园地图只能前往室外区域。")
        current_id = actor.get("current_location_id")
        if not isinstance(current_id, str) or current_id not in graph.node_ids:
            return TransactionOutcome(False, False, "unknown_location", "行动者当前地点无效。")
        route = graph.shortest_route(
            current_id,
            destination_id,
            phase=context.state.clock.phase,
            access_tags=actor.get("access_tags", ()),
        )
        if route is None:
            return TransactionOutcome(False, False, "no_available_route", "当前时段没有可用路线。")
        if not route.steps:
            return TransactionOutcome(
                False,
                True,
                "already_there",
                "已经在这个校园区域。",
                payload={
                    "current_location_id": destination_id,
                    "presentation_key": "campus_outdoor",
                    "route": [],
                    "free_movement": True,
                },
            )

        for index, step in enumerate(route.steps):
            passage = graph.passages[step.passage_id]
            actor["current_location_id"] = step.to_id
            context.emit(
                "ACTOR_LOCATION_CHANGED",
                f"{command.actor_id} 经校园地图前往 {step.to_id}。",
                actor_ids=[command.actor_id],
                scene_id=step.to_id,
                payload={
                    "passage_id": step.passage_id,
                    "from_id": step.from_id,
                    "to_id": step.to_id,
                    "travel_minutes": step.travel_minutes,
                    "transition_kind": passage.transition_kind,
                    "requires_scene_change": False,
                    "presentation_key": "campus_outdoor",
                    "route_index": index,
                    "free_movement": True,
                },
                knowledge_tags=["location", "campus_map", *passage.tags],
            )
        return TransactionOutcome(
            True,
            True,
            "success",
            "已通过校园地图到达目的区域。",
            commit=True,
            payload={
                "current_location_id": destination_id,
                "presentation_key": "campus_outdoor",
                "route": [
                    {
                        "passage_id": step.passage_id,
                        "from_id": step.from_id,
                        "to_id": step.to_id,
                    }
                    for step in route.steps
                ],
                "route_cost_minutes": route.total_minutes,
                "free_movement": True,
            },
        )

    return fast_travel


__all__ = [
    "install_campus_places",
    "load_campus_location_graph",
    "make_fast_travel_handler",
    "make_traverse_location_handler",
]
