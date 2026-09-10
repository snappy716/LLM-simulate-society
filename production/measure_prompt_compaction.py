"""Offline replay of recorded inputs. Counts characters, NOT billable tokens.

No network, credentials, simulation execution or model calls. Reconstructs old
and new wire input from identical archived actor facts and candidate records.
"""
import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simulation.cognition import provider
from simulation.cognition.action_rules import COMMON_RULES
from simulation.cognition.prompt_compaction import canonical, expand_option_payload, model_messages


def old_constants(ref, path):
    source = subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT, text=True)
    values = {}

    def value(node):
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return value(node.left) + value(node.right)
        return ast.literal_eval(node)

    # Read only literal constants and their string concatenations; never exec
    # historical source code or import historical modules.
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = value(node.value)
            except (ValueError, KeyError, TypeError):
                pass
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and isinstance(node.op, ast.Add):
            values[node.target.id] += value(node.value)
    return values


def measure(baseline):
    prompts = old_constants(baseline, "simulation/cognition/provider.py")
    old_rules = old_constants(baseline, "simulation/cognition/action_rules.py")["COMMON_RULES"]
    assert set(old_rules) == set(COMMON_RULES)
    groups = {}
    for branch in ("llm-unattended", "llm-participant"):
        path = ROOT / "production/validation/step11-free-errands" / branch / "requests.json"
        for record in json.loads(path.read_text()):
            before = deepcopy(record["request"])
            after = deepcopy(before)
            if "action_rules" in before.get("state", {}):
                before["state"]["action_rules"]["common"] = deepcopy(old_rules)
                after["state"]["action_rules"]["common"] = deepcopy(COMMON_RULES)
            name = ("DAILY_PLAN_SYSTEM_PROMPT" if before.get("daily_options") is not None else
                    "DIALOGUE_SYSTEM_PROMPT" if "target_id" in before else "SYSTEM_PROMPT")
            messages = model_messages(getattr(provider, name), after)
            packed = json.loads(messages[1]["content"])
            assert canonical(expand_option_payload(packed)) == canonical(after)
            group = groups.setdefault(name, {"requests": 0, "compacted": 0, "before_input_chars": 0,
                                            "after_input_chars": 0, "historical_prompt_tokens": 0})
            group["requests"] += 1
            group["compacted"] += "option_defaults" in packed
            group["before_input_chars"] += len(prompts[name]) + len(canonical(before))
            group["after_input_chars"] += sum(len(m["content"]) for m in messages)
            group["historical_prompt_tokens"] += record.get("usage", {}).get("prompt_tokens", 0)
    for group in groups.values():
        group["input_char_reduction_percent"] = round(100 * (1 - group["after_input_chars"] / group["before_input_chars"]), 2)
        group["historical_mean_prompt_tokens"] = round(group["historical_prompt_tokens"] / group["requests"], 2)
    return {"baseline_commit": baseline, "network_calls": 0, "lossless_roundtrip": True,
            "unit": "Unicode characters including system prompt and compaction guidance; not tokens or cost",
            "groups": groups}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="75afaff29dbb67874e3e9b11af77c4b06112e7ab")
    print(json.dumps(measure(parser.parse_args().baseline), ensure_ascii=False, indent=2))
