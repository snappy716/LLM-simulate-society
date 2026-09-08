"""Exercise the actual HTTP adapter against a loopback scripted server, not an LLM.

Run from the repository root: python3 -m production.check_llm_local_protocol
No user settings, saved credentials, external provider, or paid API is used.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from simulation.api.server import CampusKernelBridge
from tests.test_campus_cognition import command


class ScriptedProvider(BaseHTTPRequestHandler):
    records = []
    invalid = False

    def do_POST(self):
        assert self.path == "/v1/chat/completions"
        assert self.headers["Authorization"] == "Bearer loopback-fixture-only"
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["model"] == "local-scripted-fixture"
        assert body["response_format"] == {"type": "json_object"}
        request = json.loads(body["messages"][1]["content"])
        answer = {"npc_id": request["npc_id"], "candidate_revision": request["candidate_revision"]}
        if request.get("daily_options") is not None:
            assert body["max_tokens"] >= 512
            answer.update(selected_action_id=None, reason="本地协议夹具的组合选择，不是真实模型推理。",
                          daily_choices={phase: options[index % len(options)]["candidate_id"]
                                         for index, (phase, options) in enumerate(request["daily_options"].items())})
            purpose = "daily_plan"
        elif "dialogue_kind" in request:
            answer.update(target_id=request["target_id"], utterance="这是本地协议测试回复。", fact_ids_used=[])
            purpose = "dialogue"
        else:
            answer.update(selected_action_id=request["candidates"][0]["candidate_id"], reason="本地协议夹具选择。")
            purpose = "interaction"
        if self.invalid:
            answer["npc_id"] = "foreign-actor"
        self.records.append({"npc_id": request["npc_id"], "purpose": purpose})
        raw = json.dumps({"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}],
                          "usage": {"prompt_tokens": 100, "completion_tokens": 40}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


def main():
    bridge = CampusKernelBridge(42)
    for _ in range(3):
        assert command(bridge, "ADVANCE_PHASE")["ok"]
    ScriptedProvider.records = []
    ScriptedProvider.invalid = False
    with ThreadingHTTPServer(("127.0.0.1", 0), ScriptedProvider) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            bridge.cognition_runtime.configure_openai_compatible(
                f"http://127.0.0.1:{server.server_port}/v1", "local-scripted-fixture", "loopback-fixture-only")
            assert command(bridge, "ADVANCE_PHASE")["ok"]
            plans = [row for row in ScriptedProvider.records if row["purpose"] == "daily_plan"]
            assert len(plans) == 20 and len({row["npc_id"] for row in plans}) == 20
            state = bridge.kernel._state
            npc = next(n for n in state.population if n != "player" and n not in state.cognition["focused_ids"])
            reply = bridge.cognition_runtime.compose_player_in_person_reply(state, npc, "player", "你好", {}, [], [])
            assert reply is not None and reply["source"] == "llm"
            ScriptedProvider.invalid = True
            rejected = bridge.cognition_runtime.compose_player_in_person_reply(state, npc, "player", "再说一句", {}, [], [])
            assert rejected is None
            assert state.cognition["usage"]["budget_blocks"] == 0
            assert state.cognition["usage"]["rejected_responses"] >= 1
            print("LOCAL_LLM_PROTOCOL_OK 20_unique_daily_plans ordinary_npc_chat wrong_actor_rejected no_quota local_scripted_responses paid_calls=0")
        finally:
            bridge.cognition_runtime.configure_rule()
            server.shutdown()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
