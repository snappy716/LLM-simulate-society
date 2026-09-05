"""Production service startup is independent from the retired town runtime."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from simulation.api.server import Handler, SimulationBridge
from simulation.persistence.campus_saves import CampusSaveStore
from simulation.settings import load_runtime_settings

ROOT = Path(__file__).resolve().parents[1]


class CampusServiceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = SimulationBridge(Path(self.temp.name))

    def test_fresh_process_never_imports_or_constructs_town_or_auto_enables_llm(self):
        code = """import json,sys
from simulation.api.server import SimulationBridge
b=SimulationBridge()
print(json.dumps({"runtime": "simulation.runtime" in sys.modules,
"legacy_bridge": "simulation.api.legacy_bridge" in sys.modules,
"world": hasattr(b,"world"), "population": len(b.campus_snapshot()["population"]),
"configured": b.campus.cognition_runtime.public_status()["configured"]}))"""
        env = {**os.environ, "GODOT_SIM_LLM_MODE": "deepseek", "DEEPSEEK_API_KEY": "fake-test-only"}
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual({"runtime": False, "legacy_bridge": False, "world": False,
                          "population": 200, "configured": False}, json.loads(result.stdout))

    def test_no_legacy_snapshot_or_trace_files_on_startup(self):
        self.assertEqual([], list(Path(self.temp.name).iterdir()))
        self.assertFalse(hasattr(self.bridge, "world"))

    def test_module_entry_is_campus_server(self):
        result = subprocess.run([sys.executable, "-m", "simulation", "--help"], cwd=ROOT,
                                capture_output=True, text=True, timeout=10, check=True)
        self.assertIn("--port", result.stdout)
        self.assertIn("--save-dir", result.stdout)
        self.assertNotIn("--deepseek-model", result.stdout)

    def test_settings_default_local_override_and_invalid_json(self):
        root = Path(self.temp.name)
        (root / "config.json").write_text('{"seed":42}', encoding="utf-8")
        (root / "config.local.json").write_text('{"seed":7}', encoding="utf-8")
        self.assertEqual(7, load_runtime_settings(root)["seed"])
        (root / "config.local.json").write_text('[]', encoding="utf-8")
        with self.assertRaises(RuntimeError):
            load_runtime_settings(root)

    def test_explicit_configuration_is_offline_until_dialogue_or_decision(self):
        before = self.bridge.campus.kernel.state.to_dict()
        with patch("urllib.request.urlopen", side_effect=AssertionError("configuration must not call LLM")):
            result = self.bridge.configure_interface({"provider": "openai_compatible",
                "base_url": "https://example.invalid/v1", "model": "custom", "api_key": "fake-test-secret"})
            self.assertTrue(result["ok"])
            self.assertTrue(result["api_key_configured"])
        self.assertEqual(before, self.bridge.campus.kernel.state.to_dict())
        self.assertNotIn("fake-test-secret", json.dumps(self.bridge.campus_snapshot()))
        with self.assertRaises(ValueError):
            self.bridge.configure_interface({"provider": "openai_compatible", "base_url": "", "model": ""})
        self.assertTrue(self.bridge.campus.cognition_runtime.public_status()["configured"])
        self.bridge.configure_interface({"provider": "rule"})
        self.assertFalse(self.bridge.campus.cognition_runtime.public_status()["configured"])

    def test_http_only_exposes_campus_and_legacy_requests_cannot_mutate(self):
        class TestHandler(Handler):
            bridge = self.bridge
        with ThreadingHTTPServer(("127.0.0.1", 0), TestHandler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(path, payload=None):
                    body = None if payload is None else json.dumps(payload).encode()
                    return urlopen(Request(f"http://127.0.0.1:{server.server_port}{path}",
                        data=body, headers={"Content-Type": "application/json"}), timeout=10)
                with request("/health") as response:
                    self.assertEqual("campus", json.load(response)["world_kind"])
                with request("/kernel/campus-snapshot") as response:
                    self.assertEqual(200, len(json.load(response)["population"]))
                before = self.bridge.campus.kernel.state.to_dict()
                for path in ("/snapshot", "/step", "/trade", "/use-item", "/action"):
                    with self.assertRaises(HTTPError) as caught:
                        request(path, None if path == "/snapshot" else {})
                    self.assertEqual(410, caught.exception.code)
                self.assertEqual(before, self.bridge.campus.kernel.state.to_dict())
                with self.assertRaises(HTTPError) as caught:
                    request("/configure", {"provider": "openai_compatible"})
                self.assertEqual(400, caught.exception.code)
            finally:
                server.shutdown()
                thread.join()

    def test_existing_campus_slot_loads_after_service_restart(self):
        store = CampusSaveStore(Path(self.temp.name) / "saves")
        payload = {"operation": "save", "slot_id": "slot_1", "confirmed": True,
                   "expected_world_revision": 1, "expected_token": ""}
        saved = self.bridge.campus.persistence(store, payload)
        fresh = SimulationBridge(Path(self.temp.name))
        payload.update(operation="load", expected_token=saved["slots"][0]["current"]["token"])
        loaded = fresh.campus.persistence(store, payload)
        self.assertEqual(saved["snapshot"]["economy"], loaded["snapshot"]["economy"])
        self.assertEqual(saved["snapshot"]["population"], loaded["snapshot"]["population"])
