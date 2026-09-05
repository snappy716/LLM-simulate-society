#!/usr/bin/env python3
"""Persistent local bridge between the simulation package and Godot."""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

REPOSITORY_DIR = Path(__file__).resolve().parents[2]
GAME_DIR = REPOSITORY_DIR / "game"
sys.path.insert(0, str(REPOSITORY_DIR))

from simulation.api.commands import (  # noqa: E402
    CommandParseError,
    command_result_view,
    parse_simulation_command,
)
from simulation.api.views import campus_world_view, npc_chronicle_view  # noqa: E402
from simulation.domain import WorldState  # noqa: E402
from simulation.systems.campus_vitals import (  # noqa: E402
    install_campus_vitals, campus_vitals_invariant, make_field_recovery_handler,
)
from simulation.systems.campus_inventory import (  # noqa: E402
    CAMPUS_ITEM_ACTIONS, install_campus_inventory,
    campus_inventory_invariant, make_campus_inventory_handler,
)
from simulation.systems.campus_trade import (
    TRADE_ACTIONS, install_campus_trade, make_campus_trade_handler,
    advance_campus_trade, make_procurement_selector,
)
from simulation.systems.campus_supply import install_campus_supply, receive_campus_supply, review_campus_supply
from simulation.systems import (  # noqa: E402
    CampusPopulationGenerator,
    ContentRegistry,
    DeterministicRngPool,
    WorldKernel,
    DuplicateCommandError,
    RevisionConflictError,
    install_campus_places,
    install_action_economy,
    install_campus_population,
    install_campus_abilities,
    install_campus_schedules,
    load_action_economy_policy,
    load_campus_location_graph,
    load_campus_schedule_templates,
    make_advance_phase_handler,
    make_fast_travel_handler,
    make_traverse_location_handler,
    action_economy_invariant,
    campus_schedule_invariant,
    campus_activity_invariant,
    campus_activity_effect_invariant,
    advance_campus_phase_upkeep,
    load_campus_activity_definitions,
    make_campus_activity_handler,
    make_scheduled_npc_phase_executor,
    campus_decision_invariant,
    load_campus_decision_policy,
    make_campus_npc_decision_selector,
    complete_assigned_task,
    install_campus_forums,
    load_campus_forum_policy,
    load_surface_task_templates,
    make_campus_task_invariant,
    make_forum_task_handler,
    make_surface_forum_phase_upkeep,
    make_task_aware_decision_selector,
    campus_social_invariant,
    install_campus_social_state,
    campus_intelligence_invariant,
    install_campus_intelligence,
    load_campus_intelligence_policy,
    install_campus_clubs,
    load_campus_club_policy,
    make_campus_club_handler,
    settle_club_activity,
    advance_club_upkeep,
    campus_club_invariant,
    validate_club_activity,
    club_has_activity,
    advance_party_commitments,
    campus_party_invariant,
    install_campus_parties,
    load_campus_party_policy,
    make_campus_party_handler,
    campus_ability_invariant,
    load_campus_ability_definitions,
    install_chronicles,
    project_chronicle_events,
    chronicle_invariant,
    CognitionRuntime,
    advance_cognition_phase,
    cognition_invariant,
    install_campus_cognition,
    load_cognition_policy,
    make_awaken_npc_handler,
    make_cognition_decision_selector,
    project_cognition_events,
    advance_campus_interactions,
    campus_interaction_invariant,
    install_campus_interactions,
    load_campus_interaction_policy,
    make_player_dialogue_handler,
    advance_campus_phone_messages,
    campus_messaging_invariant,
    install_campus_messaging,
    load_campus_messaging_policy,
    make_campus_messaging_handler,
    campus_proposal_invariant,
    install_campus_proposals,
    advance_npc_player_proposals,
    make_npc_player_proposal_response_handler,
    make_player_proposal_handler,
    NIGHT_WORLD_ACTION_IDS,
    advance_campus_night_world,
    campus_night_world_invariant,
    install_campus_night_world,
    load_campus_night_world_policy,
    make_campus_night_world_handler,
    advance_campus_night_forum,
    campus_night_task_invariant,
    load_night_task_templates,
    COMBAT_ACTION_IDS,
    advance_campus_combat,
    campus_combat_invariant,
    install_campus_combat,
    load_combat_deployment_policy,
    load_combat_round_policy,
    make_campus_combat_handler,
)


class CampusKernelBridge:
    """Godot bridge for the authoritative campus kernel."""

    def __init__(self, master_seed: int) -> None:
        registry = ContentRegistry.load_default(REPOSITORY_DIR / "content")
        self.registry = registry
        self.operation_lock = threading.RLock()
        graph = load_campus_location_graph(registry)
        rng_pool = DeterministicRngPool(master_seed)
        state = WorldState(content_version=registry.content_version, master_seed=master_seed)
        install_campus_places(state, graph)
        records = CampusPopulationGenerator(registry, graph, rng_pool).generate()
        install_campus_population(state, records)
        install_campus_vitals(state)
        install_campus_inventory(state, registry)
        install_campus_supply(state, registry)
        install_campus_trade(state)
        ability_definitions = load_campus_ability_definitions(registry)
        install_campus_abilities(state, ability_definitions, registry.all("college"))
        install_campus_social_state(state, registry.all("club"))
        intelligence_policy = load_campus_intelligence_policy(registry)
        install_campus_intelligence(
            state, registry.all("college"), registry.all("club")
        )
        club_policy = load_campus_club_policy(registry)
        install_campus_clubs(state, registry.all("club"), club_policy)
        party_policy = load_campus_party_policy(registry)
        install_campus_parties(state, party_policy)
        schedule_templates = load_campus_schedule_templates(registry, graph)
        install_campus_schedules(state, graph, schedule_templates)
        action_policy = load_action_economy_policy(registry)
        install_action_economy(state, action_policy)
        install_chronicles(state)
        cognition_policy = load_cognition_policy(registry)
        install_campus_cognition(state, cognition_policy)
        interaction_policy = load_campus_interaction_policy(registry)
        install_campus_interactions(state)
        messaging_policy = load_campus_messaging_policy(registry)
        install_campus_messaging(state, messaging_policy)
        install_campus_proposals(state)
        night_world_policy = load_campus_night_world_policy(registry)
        install_campus_night_world(state, night_world_policy)
        combat_policy = load_combat_deployment_policy(registry)
        combat_round_policy = load_combat_round_policy(registry)
        install_campus_combat(
            state,
            combat_policy,
            combat_round_policy,
            registry.all("enemy_archetype"),
        )
        self.cognition_runtime = CognitionRuntime(cognition_policy)
        activity_definitions = load_campus_activity_definitions(registry)
        activity_handler = make_campus_activity_handler(
            activity_definitions,
            action_policy,
            lambda context, command, definition: settle_club_activity(
                context, command, definition, club_policy
            ),
            validate_club_activity,
        )
        decision_policy = load_campus_decision_policy(
            registry, activity_definitions, graph
        )
        base_decision_selector = make_cognition_decision_selector(
            self.cognition_runtime, graph, activity_definitions, decision_policy
        )
        def decision_selector(context, actor_id, schedule_plan, destination_occupancy):
            plan = base_decision_selector(
                context, actor_id, schedule_plan, destination_occupancy
            )
            actor = context.state.population.get(actor_id, {})
            if (
                plan
                and plan.get("activity_id") == "CLUB_ACTIVITY"
                and not any(
                    club_has_activity(
                        context.state, club_id,
                        context.state.clock.day, context.state.clock.phase,
                    )
                    for club_id in actor.get("club_ids", ())
                )
            ):
                return schedule_plan
            return plan
        task_templates = load_surface_task_templates(registry)
        for task_template in task_templates.values():
            task_template["allowed_phases"] = list(
                activity_definitions[task_template["activity_id"]].allowed_phases
            )
        forum_policy = load_campus_forum_policy(registry)
        install_campus_forums(state, task_templates, forum_policy, rng_pool)
        night_task_templates = load_night_task_templates(registry)
        for task_template in night_task_templates.values():
            task_template["allowed_phases"] = list(
                activity_definitions[task_template["activity_id"]].allowed_phases
            )
        decision_selector = make_task_aware_decision_selector(
            decision_selector,
            activity_definitions,
            graph,
            forum_policy,
        )
        decision_selector = make_procurement_selector(decision_selector, graph, decision_policy.protected_schedule_priority)
        def campus_phase_upkeep(context):
            summary = receive_campus_supply(context)
            summary.update(advance_campus_phase_upkeep(context))
            summary.update(advance_campus_combat(context))
            summary.update(advance_campus_night_world(context, night_world_policy))
            summary.update(advance_campus_night_forum(
                context,
                graph,
                night_task_templates,
                night_world_policy,
                forum_policy.social_consequences,
            ))
            summary.update(advance_club_upkeep(context, club_policy))
            summary.update(advance_party_commitments(context, party_policy))
            self.cognition_runtime.publish_status(context.state)
            summary.update(advance_cognition_phase(context, cognition_policy))
            return summary

        phase_upkeep = make_surface_forum_phase_upkeep(
            graph,
            task_templates,
            forum_policy,
            campus_phase_upkeep,
        )
        self.kernel = WorldKernel(state, rng=rng_pool)
        self.kernel.add_invariant(campus_vitals_invariant)
        self.kernel.register_handler("USE_RECOVERY_SKILL", make_field_recovery_handler())
        self.kernel.add_invariant(campus_inventory_invariant)
        inventory_handler = make_campus_inventory_handler()
        for action_id in CAMPUS_ITEM_ACTIONS:
            self.kernel.register_handler(action_id, inventory_handler)
        for action_id in TRADE_ACTIONS:
            self.kernel.register_handler(action_id, make_campus_trade_handler())
        def scheduled_activity_handler(context, command):
            if command.action_id == "BUY_ITEM":
                return inventory_handler(context, command)
            return activity_handler(context, command)
        self.kernel.add_event_projector(project_chronicle_events)
        self.kernel.add_event_projector(project_cognition_events)
        self.kernel.add_invariant(chronicle_invariant)
        self.kernel.add_invariant(cognition_invariant)
        self.kernel.add_invariant(campus_interaction_invariant)
        self.kernel.add_invariant(campus_messaging_invariant)
        self.kernel.add_invariant(campus_proposal_invariant)
        self.kernel.add_invariant(action_economy_invariant)
        self.kernel.add_invariant(campus_schedule_invariant)
        self.kernel.add_invariant(campus_activity_invariant)
        self.kernel.add_invariant(campus_ability_invariant)
        self.kernel.add_invariant(campus_activity_effect_invariant)
        self.kernel.add_invariant(campus_decision_invariant)
        self.kernel.add_invariant(campus_social_invariant)
        self.kernel.add_invariant(campus_intelligence_invariant)
        self.kernel.add_invariant(campus_club_invariant)
        self.kernel.add_invariant(campus_party_invariant)
        self.kernel.add_invariant(campus_night_world_invariant)
        self.kernel.add_invariant(campus_night_task_invariant)
        self.kernel.add_invariant(campus_combat_invariant)
        self.kernel.add_invariant(make_campus_task_invariant(activity_definitions))
        traverse_handler = make_traverse_location_handler(graph)
        self.kernel.register_handler(
            "TRAVERSE_LOCATION_PASSAGE",
            traverse_handler,
        )
        self.kernel.register_handler(
            "FAST_TRAVEL_CAMPUS",
            make_fast_travel_handler(graph),
        )
        self.kernel.register_handler(
            "ADVANCE_PHASE",
            make_advance_phase_handler(
                action_policy,
                make_scheduled_npc_phase_executor(
                    graph,
                    action_policy,
                    traverse_handler,
                    scheduled_activity_handler,
                    phase_upkeep,
                    decision_selector,
                    complete_assigned_task,
                    lambda context: {
                        **advance_campus_trade(context),
                        **review_campus_supply(context),
                        **advance_campus_interactions(
                            context, interaction_policy, intelligence_policy,
                            self.cognition_runtime,
                        ),
                        **advance_campus_phone_messages(
                            context, messaging_policy, intelligence_policy,
                        ),
                        **advance_npc_player_proposals(
                            context, interaction_policy, messaging_policy,
                            self.cognition_runtime,
                        ),
                    },
                ),
            ),
        )
        for activity_id in sorted(activity_definitions):
            self.kernel.register_handler(activity_id, activity_handler)
        task_handler = make_forum_task_handler(activity_handler)
        for action_id in (
            "VIEW_FORUM_TASK",
            "CLAIM_FORUM_TASK",
            "ABANDON_FORUM_TASK",
            "COMPLETE_FORUM_TASK",
        ):
            self.kernel.register_handler(action_id, task_handler)
        club_handler = make_campus_club_handler(club_policy)
        for action_id in (
            "JOIN_CAMPUS_CLUB",
            "LEAVE_CAMPUS_CLUB",
            "USE_CLUB_TEAM_TACTIC",
            "TRANSFER_CLUB_LEADERSHIP",
        ):
            self.kernel.register_handler(action_id, club_handler)
        party_handler = make_campus_party_handler(party_policy)
        for action_id in (
            "INVITE_PARTY_MEMBER",
            "DISMISS_PARTY_MEMBER",
            "LEAVE_PARTY",
            "DISBAND_PARTY",
        ):
            self.kernel.register_handler(action_id, party_handler)
        self.kernel.register_handler("AWAKEN_NPC", make_awaken_npc_handler(cognition_policy))
        messaging_handler = make_campus_messaging_handler(
            messaging_policy, intelligence_policy, self.cognition_runtime
        )
        for action_id in ("ADD_PHONE_CONTACT", "SEND_PHONE_MESSAGE", "MARK_PHONE_THREAD_READ"):
            self.kernel.register_handler(action_id, messaging_handler)
        self.kernel.register_handler(
            "TALK_TO_NPC",
            make_player_dialogue_handler(
                interaction_policy, intelligence_policy, self.cognition_runtime
            ),
        )
        self.kernel.register_handler(
            "MAKE_SOCIAL_PROPOSAL",
            make_player_proposal_handler(
                interaction_policy,
                messaging_policy,
                party_handler,
                self.cognition_runtime,
            ),
        )
        self.kernel.register_handler(
            "RESPOND_SOCIAL_PROPOSAL",
            make_npc_player_proposal_response_handler(
                interaction_policy,
                messaging_policy,
                party_handler,
            ),
        )
        night_world_handler = make_campus_night_world_handler(night_world_policy)
        for action_id in NIGHT_WORLD_ACTION_IDS:
            self.kernel.register_handler(action_id, night_world_handler)
        combat_handler = make_campus_combat_handler(combat_policy, combat_round_policy, graph)
        for action_id in COMBAT_ACTION_IDS:
            self.kernel.register_handler(action_id, combat_handler)

    def configure_cognition_interface(self, config: dict) -> None:
        provider = str(config.get("provider", "rule"))
        if provider == "rule":
            self.cognition_runtime.configure_rule()
            return
        if provider == "ollama":
            self.cognition_runtime.configure_ollama(
                str(config.get("base_url", "")).strip().rstrip("/"),
                str(config.get("model", "")).strip(),
            )
            return
        if provider in {"openai_compatible", "deepseek", "deepseek_compatible"}:
            self.cognition_runtime.configure_openai_compatible(
                str(config.get("base_url", "")).strip().rstrip("/"),
                str(config.get("model", "")).strip(),
                str(config.get("api_key", "")).strip(),
            )
            return
        raise ValueError(f"unsupported provider: {provider}")

    def snapshot(self) -> dict:
        view = self.kernel.project_view(campus_world_view)
        view["cognition"]["provider"] = self.cognition_runtime.public_status()
        return view

    def execute(self, payload: dict) -> dict:
        with self.operation_lock:
            command = parse_simulation_command(payload)
            result = self.kernel.execute(command)
            return {"ok": result.success, "result": command_result_view(result), "snapshot": self.snapshot()}

    def persistence(self, store, payload):
        from simulation.persistence.campus_saves import SaveError, PRESENTATION_MAPS
        with self.operation_lock, store.locked():
            if not isinstance(payload, dict):
                raise SaveError("存档请求必须是对象。")
            if set(payload) - {"operation", "slot_id", "expected_world_revision", "expected_token", "confirmed", "backup", "presentation_map_id"}:
                raise SaveError("存档请求含未知字段；不接受文件路径。")
            action = payload.get("operation")
            if action == "list":
                return {"ok": True, "slots": store.listing()}
            if action not in ("save", "load"):
                raise SaveError("未知存档操作。")
            if (type(payload.get("confirmed")) is not bool or not isinstance(payload.get("expected_token"), str)
                    or type(payload.get("backup", False)) is not bool):
                raise SaveError("存档确认、版本或备份选项无效。")
            state, rng = self.kernel.capture_checkpoint()
            revision = payload.get("expected_world_revision")
            if type(revision) is not int or revision != state.revision:
                raise SaveError("世界已改变，请刷新后重新确认。")
            slot = payload.get("slot_id")
            options = {"expected_token": payload.get("expected_token"), "confirmed": payload.get("confirmed")}
            changes = []
            preserved_invalid = False
            if action == "save":
                map_id = payload.get("presentation_map_id", "")
                if map_id not in ("", *PRESENTATION_MAPS):
                    raise SaveError("展示地图无效；不接受场景路径。")
                if map_id:
                    state.metadata["save_presentation_map"] = map_id
                preserved_invalid = store.save(slot, state, rng, self.registry.manifest, **options)
            else:
                backup = payload.get("backup", False)
                if type(backup) is not bool:
                    raise SaveError("备份选项无效。")
                loaded, changes = store.load(slot, backup=backup, content_version=self.registry.content_version, **options)
                self.kernel.restore_checkpoint(loaded.state, loaded.rng, expected_revision=revision)
            return {"ok": True, "operation": action, "slots": store.listing(),
                    "presentation_map_id": state.metadata.get("save_presentation_map", "") if action == "save" else loaded.state.metadata.get("save_presentation_map", ""),
                    "migrations": changes, "preserved_invalid": preserved_invalid, "snapshot": self.snapshot()}

    def chronicle(
        self,
        npc_id: str,
        *,
        cursor: str = "",
        limit: int = 20,
        filter_name: str = "recent",
    ) -> dict:
        return self.kernel.project_view(
            lambda state: npc_chronicle_view(
                state,
                npc_id,
                viewer_id="player",
                cursor=cursor,
                limit=limit,
                filter_name=filter_name,
            )
        )


class SimulationBridge:
    """Production service: one authoritative campus and no hidden town World."""

    def __init__(self, output_dir: Path | None = None, save_dir: Path | None = None) -> None:
        from simulation.settings import load_runtime_settings
        from simulation.persistence.campus_saves import CampusSaveStore
        settings = load_runtime_settings()
        output_dir = output_dir or GAME_DIR / "data" / "simulation" / "live"
        self.campus_saves = CampusSaveStore(save_dir or output_dir / "campus_saves")
        self.campus = CampusKernelBridge(int(settings.get("seed", 42)))

    def configure_interface(self, config: dict) -> dict:
        if not isinstance(config, dict):
            raise ValueError("接口配置必须是对象")
        provider = config.get("provider", "rule")
        for field in ("base_url", "model", "api_key"):
            if not isinstance(config.get(field, ""), str):
                raise ValueError("接口字段必须是文本")
        if provider == "ollama" and not all(config.get(key, "").strip() for key in ("base_url", "model")):
            raise ValueError("Ollama requires base_url and model")
        if provider in ("openai_compatible", "deepseek", "deepseek_compatible") and not all(
                config.get(key, "").strip() for key in ("base_url", "model", "api_key")):
            raise ValueError("OpenAI-compatible API requires base_url, model, and api_key")
        with self.campus.operation_lock:
            self.campus.configure_cognition_interface(config)
            status = self.campus.cognition_runtime.public_status()
        return {"ok": True, "provider": config.get("provider", "rule"),
                "base_url": str(config.get("base_url", "")).strip().rstrip("/"),
                "model": str(config.get("model", "")).strip(),
                "api_key_configured": bool(str(config.get("api_key", "")).strip()),
                "status": status, "message": "接口已应用；配置本身不调用模型，校园对话与决策使用此接口。"}

    def campus_snapshot(self) -> dict:
        return self.campus.snapshot()

    def campus_command(self, payload: dict) -> dict:
        return self.campus.execute(payload)

    def campus_chronicle(self, npc_id: str, **options) -> dict:
        return self.campus.chronicle(npc_id, **options)


class Handler(BaseHTTPRequestHandler):
    bridge: SimulationBridge

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/snapshot":
            self._reply(410, {"error": "旧城镇接口已下线，请使用 /kernel/campus-snapshot", "code": "town_retired"})
        elif path in ("/health", "/kernel/campus-snapshot"):
            if path == "/health":
                payload = {"ok": True, "world_kind": "campus"}
            else:
                payload = self.bridge.campus_snapshot()
            self._reply(200, payload)
        elif path.startswith("/kernel/npcs/") and path.endswith("/chronicle"):
            npc_id = unquote(path[len("/kernel/npcs/"):-len("/chronicle")]).strip("/")
            query = parse_qs(parsed_url.query)
            try:
                payload = self.bridge.campus_chronicle(
                    npc_id,
                    cursor=query.get("cursor", [""])[0],
                    limit=int(query.get("limit", ["20"])[0]),
                    filter_name=query.get("filter", ["recent"])[0],
                )
            except ValueError as exc:
                self._reply(400, {"error": str(exc), "code": "invalid_chronicle_query"})
                return
            self._reply(200, payload)
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path in {"/step", "/trade", "/use-item", "/action"}:
            self._reply(410, {"error": "旧城镇接口已下线，请使用校园统一行动", "code": "town_retired"})
            return
        if self.path not in {
            "/configure", "/kernel/command", "/kernel/saves"
        }:
            self._reply(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if self.path == "/configure":
                self._reply(200, self.bridge.configure_interface(payload))
            elif self.path == "/kernel/command":
                self._reply(200, self.bridge.campus_command(payload))
            else:
                try:
                    result = self.bridge.campus.persistence(self.bridge.campus_saves, payload)
                except (ValueError, OSError) as exc:
                    self._reply(400, {"ok": False, "error": str(exc), "code": "save_rejected"})
                    return
                self._reply(200, result)
        except CommandParseError as exc:
            self._reply(400, {"error": exc.message, "code": exc.code})
        except (DuplicateCommandError, RevisionConflictError) as exc:
            self._reply(409, {"error": str(exc), "code": type(exc).__name__})
        except ValueError as exc:
            self._reply(400, {"error": str(exc), "code": "invalid_request"})
        except Exception as exc:
            self._reply(500, {"error": f"{type(exc).__name__}: {exc}"})

    def log_message(self, _format: str, *_args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--save-dir", type=Path)
    args = parser.parse_args()
    Handler.bridge = SimulationBridge(save_dir=args.save_dir)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"GODOT_SIMULATION_READY http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
