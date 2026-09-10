"""Godot -> game HTTP -> parallel loopback model HTTP; no paid API."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import urllib.request
from unittest.mock import patch
from simulation.api.server import Handler, SimulationBridge
from simulation.cognition.prompt_compaction import expand_option_payload
from tests.test_campus_cognition import command


class ModelHandler(BaseHTTPRequestHandler):
    lock = threading.Lock()
    active = peak = 0
    requests = []

    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        request = expand_option_payload(json.loads(body["messages"][1]["content"]))
        cls = type(self)
        with cls.lock:
            cls.active += 1
            cls.peak = max(cls.peak, cls.active)
            cls.requests.append(request)
        try:
            time.sleep(.15)
            answer = {"npc_id": request["npc_id"], "candidate_revision": request["candidate_revision"],
                      "selected_action_id": None, "reason": "根据自身需求选择合法安排"}
            if request.get("daily_options") is not None:
                answer["daily_choices"] = {p: rows[-1]["candidate_id"] for p, rows in request["daily_options"].items()}
            elif "target_id" in request:
                answer.update(target_id=request["target_id"], utterance="我会按约定安排。", fact_ids_used=[])
            else:
                answer["selected_action_id"] = request["candidates"][-1]["candidate_id"]
            data = json.dumps({"model": "loopback-only", "choices": [{"finish_reason": "stop",
                "message": {"content": json.dumps(answer)}}], "usage": {"prompt_tokens": 31, "completion_tokens": 13}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        finally:
            with cls.lock:
                cls.active -= 1


class VerifiedBridge(SimulationBridge):
    def campus_command(self, payload):
        before = self.campus.kernel.state.clock
        started = time.perf_counter()
        result = super().campus_command(payload)
        if payload.get("action_id") == "ADVANCE_PHASE" and before.phase == "late_night":
            state = self.campus.kernel.state
            plans = [r for r in ModelHandler.requests if r.get("daily_options") is not None]
            assert result["ok"] and state.clock.day == 2
            assert len(plans) == 20 and len({r["npc_id"] for r in plans}) == 20
            assert 1 < ModelHandler.peak <= 10 and ModelHandler.active == 0
            assert state.cognition["usage"]["fallbacks"] == 0
            assert state.cognition["usage"]["prompt_tokens"] == len(ModelHandler.requests) * 31
            assert state.cognition["usage"]["completion_tokens"] == len(ModelHandler.requests) * 13
            for actor in state.cognition["focused_ids"]:
                slots = state.cognition["daily_plans"]["actors"][actor]
                assert len(slots) == 4 and all(s["planned_source"] == "llm" for s in slots.values())
            print("PARALLEL_HTTP_VERIFIED " + json.dumps({"daily_calls": 20,
                "total_calls": len(ModelHandler.requests), "peak_http": ModelHandler.peak,
                "full_command_seconds": time.perf_counter() - started,
                "daily_planning": self.campus.cognition_runtime.last_daily_performance,
                "paid_api_calls": 0}), flush=True)
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="campus-parallel-fixture-") as directory, ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler) as model_server:
        worker = threading.Thread(target=model_server.serve_forever, daemon=True)
        worker.start()
        url = "http://127.0.0.1:" + str(model_server.server_port)
        original = urllib.request.urlopen
        def local_only(request, **kwargs):
            assert request.full_url == url + "/chat/completions", "fixture forbids external API"
            return original(request, **kwargs)
        try:
            with patch("simulation.settings.load_runtime_settings", return_value={"seed": 42}), patch("urllib.request.urlopen", side_effect=local_only):
                bridge = VerifiedBridge(output_dir=Path(directory), save_dir=Path(directory) / "saves")
                for _ in range(3):
                    assert command(bridge.campus, "ADVANCE_PHASE")["ok"]
                bridge.configure_interface({"provider": "openai_compatible", "base_url": url,
                    "model": "loopback-only", "api_key": "fake-never-billable", "max_concurrent_requests": 10})
                Handler.bridge = bridge
                with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
                    print("PARALLEL_FIXTURE_READY loopback_only no_personal_settings no_paid_api", flush=True)
                    server.serve_forever()
        finally:
            model_server.shutdown()
            worker.join(timeout=5)


if __name__ == "__main__":
    main()
