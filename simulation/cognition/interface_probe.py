"""Explicit, small connectivity probe; no NPC data and no game-state mutation."""
from uuid import UUID
import re
from simulation.cognition.provider import ProviderFailure, safe_usage


def validate_probe(payload):
    if not isinstance(payload, dict) or set(payload) != {"request_id", "confirmed"} or payload["confirmed"] is not True:
        raise ValueError("Probe requires an explicit cost confirmation and request id")
    if not isinstance(payload["request_id"], str) or not re.fullmatch(r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", payload["request_id"]):
        raise ValueError("Invalid probe request id")
    return str(UUID(payload["request_id"]))


def run_probe(provider):
    if not provider.configured:
        return {"ok": False, "code": "offline", "usage": safe_usage({}), "message": "当前为离线模式，不发送测试请求。"}
    try:
        response = provider._complete_json(
            'Connection test only. Return exactly JSON {"probe_ok":true}.',
            {"purpose": "explicit_connection_test"}, 128,
        )
        ok = response.get("probe_ok") is True
        return {"ok": ok, "code": "accepted" if ok else "invalid_response",
                "usage": safe_usage(response.get("_usage")),
                "message": "接口返回了有效测试 JSON；不代表完整 NPC 行为已验证。" if ok else "收到响应，但测试结构不正确。"}
    except ProviderFailure as exc:
        # ProviderFailure exposes a sanitized code, not transport headers/body.
        code = exc.code if exc.code in {"timeout", "transport_error", "invalid_json", "output_truncated"} or (exc.code.startswith("http_") and exc.code[5:].isdigit()) else "provider_error"
        return {"ok": False, "code": code, "usage": safe_usage(exc.usage), "message": "测试未通过；不会自动重试。请检查接口状态。"}
    except Exception:
        return {"ok": False, "code": "provider_error", "usage": safe_usage({}), "message": "接口未返回有效测试结果；不会自动重试。"}
