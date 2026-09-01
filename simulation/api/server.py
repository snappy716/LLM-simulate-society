#!/usr/bin/env python3
"""Persistent local bridge between the simulation package and Godot."""
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

REPOSITORY_DIR = Path(__file__).resolve().parents[2]
GAME_DIR = REPOSITORY_DIR / "game"
sys.path.insert(0, str(REPOSITORY_DIR))

from simulation import runtime as sim  # noqa: E402
from simulation.persistence import atomic_write_json  # noqa: E402


class SimulationBridge:
    def __init__(self, output_dir: Path | None = None) -> None:
        settings = sim.load_runtime_settings()
        output_dir = output_dir or GAME_DIR / "data" / "simulation" / "live"
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
                "inventory": self.world.economy.public_inventory(npc_id),
                "item_effects": npc.item_effects,
                "item_effect_records":[asdict(effect) for effect in npc.item_effect_records],
                "equipped_item_ids": npc.equipped_item_ids,
                "equipment_slots":npc.equipment_slots,
                "recent_trade_memories": [
                    asdict(memory) for memory in self.world.economy.recent_memories(npc_id, 12)
                ],
                "appearance": self._appearance(npc_id),
            }
        shops = {}
        for shop_id, shop in self.world.shops.items():
            stock = []
            for entry in self.world.economy.public_inventory(shop.inventory_id):
                item = self.world.item_catalog[entry["id"]]
                stock.append({
                    **entry,
                    "buy_price": self.world.economy._unit_price(shop, item, "buy"),
                    "sell_price": self.world.economy._unit_price(shop, item, "sell"),
                })
            keeper = self.world.npcs.get(shop.keeper_id) if shop.keeper_id else None
            shops[shop_id] = {
                **asdict(shop),
                "keeper_name": keeper.name if keeper else "无人值守",
                "is_open": self.world.phase.value in shop.open_phases,
                "stock": stock,
            }
        player_inventory = self.world.inventories["player"]
        scene_inventories = {
            scene_id:self.world.economy.public_inventory(f"scene:{scene_id}")
            for scene_id in public_scenes
        }
        container_inventories = {
            object_id:self.world.economy.public_inventory(f"container:{object_id}")
            for object_id,obj in self.world.objects.items()
            if obj.object_type=="container"
        }
        return {
            "schema_version": 2, "revision": self.revision,
            "day": self.world.day, "weekday": (self.world.day - 1) % 7,
            "phase": self.world.phase.value, "busy": self.busy,
            "player_scene": self.world.player_scene,
            "player": {
                "id": "player", "wealth": self.world.player_wealth,
                "health": self.world.player_health, "sanity": self.world.player_sanity,
                "states": self.world.player_states,
                "item_effects": self.world.player_item_effects,
                "item_effect_records":[asdict(effect) for effect in self.world.player_item_effect_records],
                "equipped_item_ids": self.world.player_equipped_item_ids,
                "equipment_slots":self.world.player_equipment_slots,
                "knowledge": self.world.player_knowledge,
                "skills":self.world.player_skills,
                "currency": self.world.economy.currency,
                "inventory_weight": player_inventory.total_weight(self.world.item_catalog),
                "inventory_capacity": player_inventory.max_weight,
                "inventory": self.world.economy.public_inventory("player"),
            },
            "items": {item_id: asdict(item) for item_id, item in self.world.item_catalog.items()},
            "item_uses": {item_id: asdict(definition)
                          for item_id, definition in self.world.item_uses.definitions.items()},
            "item_instances":self.world.item_instances.public_instances(),
            "scene_inventories":scene_inventories,
            "container_inventories":container_inventories,
            "passages":{passage_id:asdict(passage)
                        for passage_id,passage in self.world.passages.passages.items()},
            "available_actions":self.world.action_registry.ids(),
            "player_intelligence":[
                asdict(fact) for fact in self.world.intelligence.known_facts("player")
            ],
            "shops": shops,
            "peer_trade_offers": {
                offer_id: asdict(offer)
                for offer_id, offer in self.world.economy.peer_offers.items()
            },
            "recent_trade_memories": [
                asdict(memory) for memory in self.world.economy.trade_memories[-200:]
            ],
            "peer_trade_daily_counts": dict(self.world.economy.peer_trade_daily_counts),
            "scenes": public_scenes, "npcs": npcs,
            "new_events": self.last_events[-50:],
        }

    def _write_snapshot(self) -> dict:
        data = self.snapshot()
        atomic_write_json(self.snapshot_path, data)
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

    def trade(self, payload: dict) -> dict:
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("simulation is already advancing")
        self.busy = True
        try:
            day = self.world.day
            before = len(self.world.events_by_day[day])
            receipt = sim.execute_trade(
                self.world,
                actor_id=str(payload.get("actor_id", "player")),
                shop_id=str(payload.get("shop_id", "")),
                item_id=str(payload.get("item_id", "")),
                quantity=payload.get("quantity", 1),
                direction=str(payload.get("direction", "buy")),
            )
            if receipt.success:
                produced = self.world.events_by_day[day][before:]
                self.last_events = [{
                    "event_id": event.event_id, "day": event.day, "phase": event.phase,
                    "event_type": event.event_type, "scene_id": event.scene_id,
                    "actor_ids": event.actor_ids, "message": event.description,
                    "tags": event.tags, "level": event.level,
                } for event in produced]
                self.revision += 1
                snapshot = self._write_snapshot()
            else:
                snapshot = self.snapshot()
            return {"ok": receipt.success, "trade": asdict(receipt), "snapshot": snapshot}
        finally:
            self.busy = False
            self.lock.release()

    def use_item(self, payload: dict) -> dict:
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("simulation is already advancing")
        self.busy = True
        try:
            day = self.world.day
            before = len(self.world.events_by_day[day])
            receipt = sim.execute_item_use(
                self.world,
                actor_id=str(payload.get("actor_id", "player")),
                item_id=str(payload.get("item_id", "")),
            )
            if receipt.success:
                produced = self.world.events_by_day[day][before:]
                self.last_events = [{
                    "event_id": event.event_id, "day": event.day, "phase": event.phase,
                    "event_type": event.event_type, "scene_id": event.scene_id,
                    "actor_ids": event.actor_ids, "message": event.description,
                    "tags": event.tags, "level": event.level,
                } for event in produced]
                self.revision += 1
                snapshot = self._write_snapshot()
            else:
                snapshot = self.snapshot()
            return {"ok": receipt.success, "item_use": asdict(receipt), "snapshot": snapshot}
        finally:
            self.busy = False
            self.lock.release()

    def action(self,payload: dict) -> dict:
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("simulation is already advancing")
        self.busy=True
        try:
            day=self.world.day
            before=len(self.world.events_by_day[day])
            action_id=str(payload.get("action_id",""))
            actor_id=str(payload.get("actor_id","player"))
            item_id=str(payload.get("item_id",""))
            target_id=payload.get("target_id")
            difficulty=payload.get("difficulty_override")
            passage_actions={
                "PICK_LOCK","FORCE_OPEN","UNLOCK_WITH_KEY",
                "CLIMB_WITH_ROPE","TRAVERSE_PASSAGE",
            }
            if action_id=="USE_ITEM":
                receipt=sim.execute_item_use(self.world,actor_id=actor_id,item_id=item_id)
            elif action_id in {"GIVE_ITEM","DROP_ITEM","PICK_UP_ITEM"}:
                receipt=sim.execute_item_transfer(
                    self.world,action_id=action_id,actor_id=actor_id,item_id=item_id,
                    quantity=payload.get("quantity",1),target_id=target_id,
                    container_id=payload.get("container_id"))
            elif action_id in {"EQUIP_ITEM","UNEQUIP_ITEM"}:
                receipt=sim.execute_equipment_action(
                    self.world,action_id=action_id,actor_id=actor_id,
                    item_id=item_id or None,instance_id=payload.get("instance_id"),
                    slot=payload.get("slot"))
            elif action_id in passage_actions:
                receipt=sim.execute_passage_action(
                    self.world,action_id=action_id,actor_id=actor_id,
                    passage_id=str(payload.get("passage_id","")))
            elif action_id=="PRESENT_IDENTITY":
                receipt=sim.execute_identity_action(
                    self.world,actor_id=actor_id,
                    inspector_id=str(payload.get("inspector_id") or target_id or ""),
                    item_id=item_id,difficulty_override=difficulty)
            elif action_id=="RECORD_INTELLIGENCE":
                receipt=sim.execute_intelligence_record(
                    self.world,actor_id=actor_id,fact_id=str(payload.get("fact_id","")),
                    item_id=item_id or "blank_notebook")
            elif action_id=="THREATEN_WITH_WEAPON":
                receipt=sim.execute_weapon_threat(
                    self.world,actor_id=actor_id,target_id=str(target_id or ""),
                    difficulty_override=difficulty)
            elif action_id in {"PERFORM_LEGAL_RITUAL","PERFORM_SECRET_RITUAL"}:
                receipt=sim.execute_item_ritual(
                    self.world,actor_id=actor_id,
                    illegal=action_id=="PERFORM_SECRET_RITUAL",
                    difficulty_override=difficulty)
            else:
                return {
                    "ok":False,"performed":False,
                    "action":{"action_id":action_id,"code":"invalid_action",
                              "message":f"统一接口不支持行动：{action_id}"},
                    "snapshot":self.snapshot(),
                }
            produced=self.world.events_by_day[day][before:]
            performed=bool(receipt.success or getattr(receipt,"check",None) is not None)
            changed=performed or bool(produced)
            if changed:
                self.last_events=[{
                    "event_id":event.event_id,"day":event.day,"phase":event.phase,
                    "event_type":event.event_type,"scene_id":event.scene_id,
                    "actor_ids":event.actor_ids,"message":event.description,
                    "tags":event.tags,"level":event.level,
                } for event in produced]
                self.revision+=1
                snapshot=self._write_snapshot()
            else:
                snapshot=self.snapshot()
            return {
                "ok":bool(receipt.success),"performed":performed,
                "action_id":action_id,"action":asdict(receipt),"snapshot":snapshot,
            }
        finally:
            self.busy=False
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
        if self.path not in {"/step", "/configure", "/trade", "/use-item", "/action"}:
            self._reply(404, {"error": "not found"})
            return
        try:
            if self.path == "/step":
                self._reply(200, self.bridge.step())
            else:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                if self.path == "/configure":
                    self._reply(200, self.bridge.configure_interface(payload))
                elif self.path == "/use-item":
                    result = self.bridge.use_item(payload)
                    self._reply(200 if result["ok"] else 400, result)
                elif self.path == "/action":
                    result=self.bridge.action(payload)
                    self._reply(200 if result["performed"] else 400,result)
                else:
                    result = self.bridge.trade(payload)
                    self._reply(200 if result["ok"] else 400, result)
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
