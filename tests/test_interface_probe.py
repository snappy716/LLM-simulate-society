import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import Mock

from simulation.api.server import SimulationBridge
from simulation.cognition.interface_probe import run_probe, validate_probe
from simulation.cognition.provider import ProviderFailure, RuleOnlyProvider


class InterfaceProbeTests(unittest.TestCase):
    def test_requires_explicit_confirmation(self):
        for payload in ({}, {"confirmed": 1, "request_id": str(uuid4())},
                        {"confirmed": True, "request_id": "bad"},
                        {"confirmed": True, "request_id": str(uuid4()), "prompt": "hidden"}):
            with self.assertRaises((ValueError, TypeError)):
                validate_probe(payload)

    def test_offline_no_call(self):
        self.assertEqual(run_probe(RuleOnlyProvider())["code"], "offline")

    def test_short_probe_and_sanitized_failures(self):
        provider = Mock(configured=True)
        provider._complete_json.return_value = {"probe_ok": True, "_usage": {"prompt_tokens": 12, "completion_tokens": 5}, "secret": "not-returned"}
        result = run_probe(provider)
        self.assertTrue(result["ok"])
        self.assertNotIn("secret", str(result))
        args = provider._complete_json.call_args.args
        self.assertEqual(args[2], 128)
        self.assertEqual(args[1], {"purpose": "explicit_connection_test"})
        provider._complete_json.side_effect = ProviderFailure("http_402", {"prompt_tokens": 3})
        self.assertEqual(run_probe(provider)["code"], "http_402")
        provider._complete_json.side_effect = RuntimeError("secret-api-key")
        self.assertNotIn("secret-api-key", str(run_probe(provider)))

    def test_same_id_charged_once_and_world_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = SimulationBridge(save_dir=Path(directory))
            provider = Mock(configured=True)
            provider._complete_json.return_value = {"probe_ok": True, "_usage": {"prompt_tokens": 9, "completion_tokens": 4}}
            bridge.campus.cognition_runtime.provider = provider
            before = bridge.campus.kernel.state.to_dict()
            payload = {"confirmed": True, "request_id": str(uuid4())}
            first = bridge.probe_interface(payload)
            second = bridge.probe_interface(payload)
            self.assertEqual(first, second)
            self.assertEqual(provider._complete_json.call_count, 1)
            self.assertEqual(first["aggregate_usage"]["calls"], 1)
            self.assertEqual(before, bridge.campus.kernel.state.to_dict())


if __name__ == "__main__":
    unittest.main()
