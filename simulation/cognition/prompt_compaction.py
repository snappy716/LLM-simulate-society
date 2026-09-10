"""Lossless factoring of repeated candidate metadata on the model wire only.

No candidate, memory, identity or authoritative field is discarded. Internal
requests and response validation retain their original shape and full records.
"""
from copy import deepcopy
import json


DEFAULTS_GUIDANCE = "option_defaults 仅去除候选的重复字段：候选缺少某字段时，继承同名候选组的默认值；daily_options/free_options 按时段继承，candidates/social_options 直接继承。候选自身字段优先。省略不代表无条件或免除费用。返回原候选ID，不返回默认值。"
FACTORED_FIELDS = {"reason", "parameters", "action_class", "major_action_cost",
                   "cost_rechecked_at_execution", "cost_condition"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def compact_option_payload(payload):
    """Preserve IDs/targets/locations and only factor exactly equal typed values.

Unknown fields and caller-provided option_defaults pass through unchanged.
Do not grow short requests merely to advertise a compression protocol.
"""
    result = deepcopy(payload)
    if "option_defaults" in result:
        return result
    defaults = {}

    def factor(rows):
        if not isinstance(rows, (list, tuple)) or len(rows) < 2 or not all(isinstance(r, dict) for r in rows):
            return rows, {}
        shared = {}
        for key in sorted(FACTORED_FIELDS):
            if all(key in row for row in rows) and all(canonical(row[key]) == canonical(rows[0][key]) for row in rows[1:]):
                shared[key] = deepcopy(rows[0][key])
        return [{k: deepcopy(v) for k, v in row.items() if k not in shared} for row in rows], shared

    for name in ("daily_options", "free_options"):
        if isinstance(result.get(name), dict):
            for phase, rows in result[name].items():
                packed, shared = factor(rows)
                if shared:
                    result[name][phase] = packed
                    defaults.setdefault(name, {})[phase] = shared
    for name in ("candidates", "social_options"):
        packed, shared = factor(result.get(name))
        if shared:
            result[name] = packed
            defaults[name] = shared
    if not defaults:
        return deepcopy(payload)
    result["option_defaults"] = defaults
    if len(canonical(payload)) - len(canonical(result)) <= len(DEFAULTS_GUIDANCE) + 32:
        return deepcopy(payload)
    return result


def expand_option_payload(payload):
    """Audit/test decoder: demonstrate every fact and candidate was preserved."""
    result = deepcopy(payload)
    defaults = result.pop("option_defaults", {})
    for name, shared in defaults.items():
        if name in ("daily_options", "free_options"):
            for phase, fields in shared.items():
                result[name][phase] = [{**deepcopy(fields), **row} for row in result[name][phase]]
        elif name in ("candidates", "social_options"):
            result[name] = [{**deepcopy(shared), **row} for row in result[name]]
    return result


def model_messages(system_prompt, request_payload):
    compact = compact_option_payload(request_payload)
    if "option_defaults" in compact and "option_defaults" not in request_payload:
        system_prompt += DEFAULTS_GUIDANCE
    return [{"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(compact, ensure_ascii=False, separators=(",", ":"))}]
