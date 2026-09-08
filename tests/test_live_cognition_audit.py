"""No-network checks for the opt-in paid audit transport and secret handling."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from production.run_live_cognition_soak import AuditedProvider


class Response(io.BytesIO):
    status = 200


class LiveAuditTests(unittest.TestCase):
    def test_non_thinking_is_only_an_explicit_test_option_and_no_secret_is_logged(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                provider = AuditedProvider("fake-private-test-key", Path(directory), 30, enabled)
                received = []

                def respond(request, **kwargs):
                    received.append(json.loads(request.data))
                    return Response(json.dumps({"choices": [{"message": {"content": '{"ok":true}'},
                                                             "finish_reason": "stop"}],
                                                "usage": {"total_tokens": 10}}).encode())

                with patch("urllib.request.urlopen", respond) as transport:
                    result = provider._complete_json("JSON only", {"test": "public-test"}, 160)
                    self.assertIs(transport, __import__("urllib.request", fromlist=["urlopen"]).urlopen)
                self.assertTrue(result["ok"])
                self.assertEqual(enabled, "thinking" in received[0])
                self.assertEqual(160, received[0]["max_tokens"])
                logged = (Path(directory) / "requests.json").read_text()
                self.assertNotIn("fake-private-test-key", logged)
                self.assertNotIn("Authorization", logged)
                self.assertEqual(10, provider.records[0]["usage"]["total_tokens"])
                provider.secret_forget()
                self.assertFalse(provider.configured)

    def test_truncated_response_retains_usage_and_stops_after_three_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = AuditedProvider("fake-private-test-key", Path(directory), 30, True)

            def respond(*args, **kwargs):
                return Response(json.dumps({"choices": [{"message": {"content": ""},
                                                         "finish_reason": "length"}],
                                            "usage": {"total_tokens": 160}}).encode())

            with patch("urllib.request.urlopen", respond):
                for _ in range(2):
                    with self.assertRaises(RuntimeError):
                        provider._complete_json("JSON only", {}, 160)
                with self.assertRaises(SystemExit):
                    provider._complete_json("JSON only", {}, 160)
            self.assertEqual(3, len(provider.records))
            self.assertEqual(480, sum(r["usage"]["total_tokens"] for r in provider.records))
            self.assertTrue(all(r["finish_reason"] == "length" for r in provider.records))


if __name__ == "__main__":
    unittest.main()
