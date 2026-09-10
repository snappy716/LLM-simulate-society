"""Observe a failed shift in the existing offline fake-model regression."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.systems import campus_medical
from simulation.systems.campus_night_sites import captive_site

original = campus_medical.validate_shift
def observe(context, command, definition):
    outcome = original(context, command, definition)
    if outcome and not outcome.success:
        actor = context.state.population[command.actor_id]
        print(json.dumps({"actor": command.actor_id, "day": context.state.clock.day, "phase": context.state.clock.phase,
            "location": actor["current_location_id"], "layer": campus_medical.actor_layer(context.state, command.actor_id),
            "occupation": actor["occupation_id"], "health": actor["vitals"]["health"],
            "captive": bool(captive_site(context.state, command.actor_id)),
            "battle": campus_medical.battle_locked(context.state, command.actor_id),
            "activity": command.action_id, "parameters": command.parameters, "decision": actor.get("current_decision")}, ensure_ascii=False), flush=True)
    return outcome

with patch.object(campus_medical, "validate_shift", observe):
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName(
        "tests.test_campus_outings.OutingTests.test_fake_daily_model_can_choose_optional_outings_without_extra_calls"))
    sys.exit(not result.wasSuccessful())
