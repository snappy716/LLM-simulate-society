"""Opt-in paid DeepSeek audit. Secret arrives via no-echo stdin, never files.

Uses shipped provider options: --non-thinking explicitly disables DeepSeek
thinking; --timeout changes only this test provider. Runs three
complete planned days after offline bootstrap, plus an identical offline world.
"""
import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import getpass
import io
import json
from pathlib import Path
import sys
import time
import urllib.request
from unittest.mock import patch

from simulation.actions.commands import SimulationCommand
from simulation.api.server import CampusKernelBridge
from simulation.cognition.provider import OpenAICompatibleCognitionProvider


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class AuditedProvider(OpenAICompatibleCognitionProvider):
    def __init__(self, key, output, timeout, non_thinking):
        super().__init__("https://api.deepseek.com", "deepseek-v4-flash", key, timeout_seconds=timeout,
                         thinking_mode="disabled" if non_thinking else "default")
        self.output, self.non_thinking = output, non_thinking
        self.records, self.consecutive_errors = [], 0

    def _complete_json(self, prompt, payload, limit):
        record = {"index": len(self.records), "started_at": datetime.now(timezone.utc).isoformat(), "npc_id": payload.get("npc_id"),
                  "day": payload.get("day"), "phase": payload.get("phase"),
                  "kind": "plan" if "daily_options" in payload else "dialogue" if "dialogue_kind" in payload else "interaction",
                  "output_limit": limit, "request": payload}
        self.records.append(record)
        original = urllib.request.urlopen

        def transport(request, **kwargs):
            body = json.loads(request.data)
            with original(request, **kwargs) as response:
                raw = response.read()
                decoded = json.loads(raw)
                choice = decoded.get("choices", [{}])[0]
                record.update(http_status=response.status, actual_model=decoded.get("model"), response_id=decoded.get("id"),
                              finish_reason=choice.get("finish_reason"), usage=decoded.get("usage", {}),
                              content_chars=len(choice.get("message", {}).get("content") or ""))
            return io.BytesIO(raw)

        start = time.perf_counter()
        try:
            with patch("urllib.request.urlopen", transport):
                result = super()._complete_json(prompt, payload, limit)
            record["response"] = result
            self.consecutive_errors = 0
            return result
        except Exception as error:
            record["error"] = type(error).__name__
            record["cause"] = type(error.__cause__).__name__
            record["http_status"] = getattr(error.__cause__, "code", record.get("http_status"))
            self.consecutive_errors += 1
            if self.consecutive_errors >= 3:
                raise SystemExit("Stopped audit after three consecutive provider failures; game quotas unchanged")
            raise
        finally:
            record["seconds"] = round(time.perf_counter() - start, 3)
            write(self.output / "requests.json", self.records)
            print(json.dumps({k: record.get(k) for k in ("index", "day", "kind", "seconds", "error", "finish_reason")}), flush=True)


def advance(bridge, name):
    state = bridge.kernel._state
    result = bridge.kernel.execute(SimulationCommand(name, "player", "ADVANCE_PHASE", state.revision,
        issued_day=state.clock.day, issued_phase=state.clock.phase, issued_minute=state.clock.minute))
    if not result.success:
        raise RuntimeError(result.code)
    return result


def run_world(days, provider, output, label):
    bridge = CampusKernelBridge(42)
    for index in range(3):
        advance(bridge, f"bootstrap:{index}")
    if provider:
        bridge.cognition_runtime.provider = provider
    phases, events, plans, usage, traces = [], [], [], [], []
    for index in range(days * 4):
        before = bridge.kernel._state
        start = time.perf_counter()
        count = len(provider.records) if provider else 0
        result = advance(bridge, f"live-audit:{index}")
        state = bridge.kernel._state
        calls = len(provider.records) - count if provider else 0
        if before.clock.phase != "late_night":
            assert calls == 0, "unexpected intraday API request"
        events.extend(event.to_dict() for event in result.events)
        phase = {**asdict(state.clock), "seconds": round(time.perf_counter() - start, 3),
                 "requests": calls, "committed_events": len(result.events)}
        phases.append(phase)
        if state.clock.phase == "morning":
            plans.append(deepcopy(state.cognition["daily_plans"]))
        if state.clock.phase == "late_night":
            usage.append(deepcopy(state.cognition["usage"]))
        traces.extend({"day": state.clock.day, "phase": state.clock.phase, "actor_id": actor_id,
                       "location": actor.get("current_location_id"), "activity": deepcopy(actor.get("current_activity")),
                       "decision": deepcopy(actor.get("current_decision"))}
                      for actor_id, actor in state.population.items() if actor_id != "player")
        write(output / f"{label}-phases.json", phases)
        print(label + "_PHASE " + json.dumps(phase), flush=True)
    state = bridge.kernel._state
    summary = {"label": label, "days": days, "seed": 42, "clock": asdict(state.clock),
               "focused_ids": list(state.cognition["focused_ids"]), "usage_by_day": usage,
               "event_counts": dict(Counter(event["event_type"] for event in events)),
               "npc_activity_counts": dict(Counter(event["payload"].get("activity_id", "unknown") for event in events
                                                   if event["event_type"] == "NPC_ACTIVITY_COMPLETED")),
               "phases": phases, "all_commands_committed_and_invariants_passed": True}
    write(output / f"{label}-summary.json", summary)
    write(output / f"{label}-events.json", events)
    write(output / f"{label}-plans.json", plans)
    write(output / f"{label}-traces.json", traces)
    write(output / f"{label}-audit.json", state.cognition["decision_audit"])
    return bridge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--non-thinking", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.days <= 7:
        parser.error("This acceptance run supports 1..7 days")
    if not sys.stdin.isatty():
        parser.error("Use an interactive terminal for hidden API key input")
    args.output.mkdir(parents=True, exist_ok=False)
    print("KEY_INPUT_READY", flush=True)
    key = getpass.getpass("DeepSeek API Key (not saved): ").strip()
    if not key:
        parser.error("API key is required")
    provider = AuditedProvider(key, args.output, args.timeout, args.non_thinking)
    del key
    write(args.output / "configuration.json", {"model": provider.model, "base_url": provider.base_url,
          "days": args.days, "timeout": args.timeout, "thinking_mode": provider.effective_thinking,
          "player_participation_during_simulation": False, "transport_payload_override": False})
    try:
        # Stop before bulk expenditure unless the actual adapter parses a reply.
        probe = provider._complete_json('Reply JSON only: {"ok":true}', {"test": "connectivity"}, 160)
        assert probe.get("ok") is True
        live = run_world(args.days, provider, args.output, "live")
        # Dialogue is sampled only AFTER the unattended simulation, on detached
        # state. This tests the runtime response method, not Godot UI commands.
        detached = live.kernel.state
        base = detached.cognition["focused_ids"]
        ordinary = next(n for n in detached.population if n != "player" and n not in base)
        replies = []
        for actor_id in (base[0], ordinary):
            reply = live.cognition_runtime.compose_player_in_person_reply(detached, actor_id, "player",
                "你好，最近在校园里过得怎么样？", {}, [], [])
            replies.append({"npc_id": actor_id, "deep": actor_id in base, "reply": reply})
        write(args.output / "player-dialogue-samples.json", replies)
        run_world(args.days, None, args.output, "offline")
        print("LIVE_COGNITION_AUDIT_COMPLETE", flush=True)
    finally:
        provider.secret_forget()


if __name__ == "__main__":
    main()
