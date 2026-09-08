import io
import json
import unittest
from unittest.mock import patch
from simulation.api.server import CampusKernelBridge
from simulation.cognition.provider import OpenAICompatibleCognitionProvider, ProviderFailure
from tests.test_campus_cognition import command


class ProviderOptionsTests(unittest.TestCase):
    def test_auto_is_scoped_to_official_deepseek_v4_and_explicit_override_is_supported(self):
        for url, model, mode, expected in (
            ("https://api.deepseek.com/v1", "deepseek-v4-flash", "auto", "disabled"),
            ("https://api.deepseek.com.evil.invalid", "deepseek-v4-flash", "auto", "default"),
            ("https://other.invalid", "generic", "auto", "default"),
            ("https://api.deepseek.com", "deepseek-v4-flash", "default", "default"),
            ("https://other.invalid", "generic", "disabled", "disabled")):
            p = OpenAICompatibleCognitionProvider(url, model, "fake", thinking_mode=mode)
            with patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}]}')) as send:
                p._complete_json("JSON", {}, 512)
            body = json.loads(send.call_args.args[0].data)
            self.assertEqual(expected, p.effective_thinking)
            self.assertEqual(None if expected == "default" else {"type": expected}, body.get("thinking"))

    def test_truncation_counts_tokens_and_exposes_sanitized_failure(self):
        b = CampusKernelBridge(42)
        for _ in range(3):
            self.assertTrue(command(b, "ADVANCE_PHASE")["ok"])
        b.configure_cognition_interface({"provider": "openai_compatible", "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash", "api_key": "fake-secret", "timeout_seconds": 30})
        def response(*args, **kwargs):
            return io.BytesIO(b'{"model":"actual-test","choices":[{"message":{"content":""},"finish_reason":"length"}],"usage":{"prompt_tokens":15,"completion_tokens":512}}')
        with patch("urllib.request.urlopen", response):
            r = command(b, "ADVANCE_PHASE")
        self.assertTrue(r["ok"])
        usage = r["snapshot"]["cognition"]["usage"]
        self.assertGreaterEqual(usage["provider_errors"], 20)
        self.assertEqual(usage["provider_errors"] * 512, usage["completion_tokens"])
        status = b.cognition_runtime.public_status()
        self.assertEqual("output_truncated", status["last_result"]["error_code"])
        self.assertNotIn("fake-secret", json.dumps(status))
        self.assertGreater(b.snapshot()["cognition"]["overnight_timeout_seconds"], 1000)

    def test_invalid_config_keeps_previous_provider_and_key(self):
        b = CampusKernelBridge(42)
        config = {"provider": "openai_compatible", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash", "api_key": "fake"}
        b.configure_cognition_interface(config)
        old = b.cognition_runtime.provider
        for value in (True, 0, 121, float("nan"), "30"):
            with self.assertRaises(ValueError):
                b.configure_cognition_interface({**config, "timeout_seconds": value})
            self.assertIs(old, b.cognition_runtime.provider)
            self.assertTrue(old.configured)


if __name__ == "__main__":
    unittest.main()
