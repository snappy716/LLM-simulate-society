from __future__ import annotations

from typing import Iterable


def build_plan_schema(phases: Iterable[str]) -> dict:
    """Build the structured-output contract used by NPC planners."""
    phase_names = list(phases)
    phase_contract = {
        "type": "object",
        "properties": {
            "scene_id": {"type": "string"},
            "intent": {"type": "string"},
            "target_id": {"type": ["string", "null"]},
            "priority": {"type": "integer"},
            "behavior": {"type": "string"},
            "fallback_scene_id": {"type": ["string", "null"]},
        },
        "required": [
            "scene_id",
            "intent",
            "target_id",
            "priority",
            "behavior",
            "fallback_scene_id",
        ],
    }
    return {
        "type": "object",
        "properties": {
            "primary_goal": {"type": "string"},
            "plans": {
                "type": "object",
                "properties": {phase: phase_contract for phase in phase_names},
                "required": phase_names,
            },
            "strategy_steps": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "phase": {"type": "string"},
                        "action_id": {"type": "string"},
                        "scene_id": {"type": "string"},
                        "target_id": {"type": ["string", "null"]},
                        "condition": {"type": "string"},
                        "intent": {"type": "string"},
                    },
                    "required": [
                        "phase",
                        "action_id",
                        "scene_id",
                        "target_id",
                        "condition",
                        "intent",
                    ],
                },
            },
        },
        "required": ["primary_goal", "plans"],
    }
