#!/usr/bin/env python3
"""Persistent local bridge between the existing simulation and Godot 0.2."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
SIM_DIR = PROJECT_DIR.parent / "emergent_town_demo"
sys.path.insert(0, str(SIM_DIR))

import town_demo as sim  # noqa: E402


class SimulationBridge:
    def __init__(self) -> None:
        settings = sim.load_runtime_settings()
        output_dir = PROJECT_DIR / "data" / "simulation" / "live"
        output_dir.mkdir(parents=True, exist_ok=True)
        self.world = sim.World(sim.Config(
            seed=int(settings.get("seed", 42)), days=0,
            core_npcs=int(settings.get("core_npcs", 20)),
            simple_npcs=int(settings.get("simple_npcs", 180)),
            # Godot play-tests are offline by default. Enable an external planner only
            # through an explicit environment variable, never merely by opening the game.
            llm_mode=os.environ.get("GODOT_SIM_LLM_MODE", "rule"),
            deepseek_url=str(settings.get("deepseek_url", "https://api.deepseek.com")),
            deepseek_model=str(settings.get("deepseek_model", "deepseek-v4-flash")),
            deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY") or settings.get("deepseek_api_key"),
            max_llm_core_npcs=int(settings.get("max_llm_npcs", 20)),
            llm_concurrency=int(settings.get("llm_concurrency", 5)),
            log_dir=str(output_dir), verbose=False,
        ))
        for npc in self.world.npcs.values():
            npc.daily_plan = sim.rule_plan_for_npc(self.world, npc)
        sim.arrange_social_invitations(self.world, self.world.day)
        self.revision = 1
        self.busy = False
        self.lock = threading.Lock()
        self.last_events: list[dict] = []
        self.snapshot_path = output_dir / "current_world.json"
        self._write_snapshot()

    def configure_interface(self, config: dict) -> dict:
        provider = str(config.get("provider", "rule"))
        base_url = str(config.get("base_url", "")).strip().rstrip("/")
        model = str(config.get("model", "")).strip()
        api_key = str(config.get("api_key", "")).strip()
        if provider == "rule":
            self.world.cfg.llm_mode = "rule"
        elif provider == "ollama":
            if not base_url or not model:
                raise ValueError("Ollama requires base_url and model")
            self.world.ollama = sim.OllamaClient(base_url, model, self.world.ledger)
            self.world.cfg.llm_mode = "ollama"
        elif provider in {"deepseek", "deepseek_compatible"}:
            if not base_url or not model or not api_key:
                raise ValueError("DeepSeek-compatible API requires base_url, model, and api_key")
            self.world.deepseek = sim.DeepSeekClient(base_url, model, api_key, self.world.ledger)
            self.world.cfg.llm_mode = "deepseek"
        else:
            raise ValueError(f"unsupported provider: {provider}")
        return {
            "ok": True, "provider": provider, "base_url": base_url,
            "model": model, "api_key_configured": bool(api_key),
            "message": "接口已应用；将在下次日终规划时使用。",
        }

    def _appearance(self, npc_id: str) -> dict:
        digest = hashlib.sha256(f"{self.world.cfg.seed}:{npc_id}".encode()).digest()
        seed = int.from_bytes(digest[:4], "big") & 0x7FFFFFFF
        return {"body_type": "male" if digest[4] % 2 == 0 else "female", "seed": seed}

    def _display_scene(self, npc) -> str:
        plan = npc.daily_plan.get(self.world.phase.value)
        return plan.scene_id if plan and plan.scene_id in self.world.scenes else npc.current_scene

    def snapshot(self) -> dict:
        public_scenes = {
            sid: asdict(scene) for sid, scene in self.world.scenes.items()
            if "private_home" not in scene.tags
        }
        npcs = {}
        for npc_id, npc in self.world.npcs.items():
            meaningful_relations = {
                target_id: asdict(relation)
                for target_id, relation in npc.relationships.items()
                if relation.kinds or relation.trust != 50 or relation.affection != 0
                or relation.suspicion != 0 or relation.fear != 0
            }
            npcs[npc_id] = {
                "id": npc.id, "name": npc.name, "tier": npc.tier,
                "occupation": npc.occupation, "organization": npc.organization,
                "layer": npc.layer, "sequence_pathway": npc.sequence_pathway,
                "sequence_rank": npc.sequence_rank, "faction_ids": npc.faction_ids,
                "current_scene": npc.current_scene, "display_scene": self._display_scene(npc),
                "home_scene": npc.home_scene, "work_scene": npc.work_scene,
                "health": npc.health, "sanity": npc.sanity, "wealth": npc.wealth,
                "alive": npc.alive, "disposition_status": npc.disposition_status,
                "states": npc.states, "special_needs": npc.special_needs,
                "goals": npc.goals, "dominant_desires": [
                    asdict(item) for item in self.world.desire_engine.dominant(npc, self.world)
                ],
                "memories": [asdict(memory) for memory in npc.memories[-20:]],
                "daily_plan": {key: asdict(value) for key, value in npc.daily_plan.items()},
                "relationships": meaningful_relations,
                "long_term_goal_ids": npc.long_term_goal_ids,
                "appearance": self._appearance(npc_id),
            }
        return {
            "schema_version": 1, "revision": self.revision,
            "day": self.world.day, "weekday": (self.world.day - 1) % 7,
            "phase": self.world.phase.value, "busy": self.busy,
            "player_scene": self.world.player_scene,
            "scenes": public_scenes, "npcs": npcs,
            "new_events": self.last_events[-50:],
        }

    def _write_snapshot(self) -> dict:
        data = self.snapshot()
        temporary = self.snapshot_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.snapshot_path)
        return data

    def step(self) -> dict:
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("simulation is already advancing")
        self.busy = True
        try:
            day = self.world.day
            before = len(self.world.events_by_day[day])
            current_phase = self.world.phase
            if current_phase == sim.Phase.MORNING:
                sim.inject_demo_player_commitment(self.world)
            sim.simulate_phase(self.world, current_phase)
            if current_phase == sim.Phase.LATE_NIGHT:
                sim.resolve_end_of_day(self.world)
                night_start = len(self.world.events_by_day[day])
                sim.run_night_fate_events(self.world)
                night_events = self.world.events_by_day[day][night_start:]
                if night_events:
                    sim.write_memories_from_events(self.world, night_events)
                    sim.update_beliefs_from_events(self.world, night_events)
                    sim.update_story_threads_from_events(self.world, night_events)
                    sim.generate_harm_and_report_reactions(self.world, night_events)
                sim.generate_incident_response_drives(self.world, self.world.events_by_day[day])
                sim.sync_long_term_goals(self.world)
                sim.plan_tomorrow(self.world)
                self.world.day += 1
                self.world.phase = sim.Phase.MORNING
            else:
                index = sim.PHASES.index(current_phase)
                self.world.phase = sim.PHASES[index + 1]
            produced = self.world.events_by_day[day][before:]
            self.last_events = [{
                "event_id": event.event_id, "day": event.day, "phase": event.phase,
                "event_type": event.event_type, "scene_id": event.scene_id,
                "actor_ids": event.actor_ids, "message": event.description,
                "tags": event.tags, "level": event.level,
            } for event in produced]
            self.revision += 1
            return self._write_snapshot()
        finally:
            self.busy = False
            self.lock.release()


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
        if self.path in ("/health", "/snapshot"):
            payload = {"ok": True} if self.path == "/health" else self.bridge.snapshot()
            self._reply(200, payload)
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path not in {"/step", "/configure"}:
            self._reply(404, {"error": "not found"})
            return
        try:
            if self.path == "/step":
                self._reply(200, self.bridge.step())
            else:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self._reply(200, self.bridge.configure_interface(payload))
        except Exception as exc:
            self._reply(500, {"error": f"{type(exc).__name__}: {exc}"})

    def log_message(self, _format: str, *_args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    Handler.bridge = SimulationBridge()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"GODOT_SIMULATION_READY http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
