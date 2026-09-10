"""Read-only instrumentation of natural outing choices; no injected outcomes."""
from collections import Counter
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from simulation.api.server import CampusKernelBridge
from simulation.actions.commands import SimulationCommand
from simulation.systems import campus_outings as outings
from simulation.systems.campus_messaging import are_phone_contacts


def run(seed=42, days=7):
    counts, blockers, margins = Counter(), Counter(), Counter()
    original = outings.outing_candidates
    original_factory = outings.make_outing_handler

    def candidates(context, actor, schedule, graph, occupancy, policy, top_score):
        rows = original(context, actor, schedule, graph, occupancy, policy, top_score)
        state = context.state
        if state.clock.phase not in outings.PHASES: return rows
        counts["eligible_phase_calls"] += 1
        if int(schedule.get("priority", 0)) >= policy.protected_schedule_priority:
            counts["protected_schedule"] += 1
            return rows
        counts["unprotected_phase_calls"] += 1
        phone = state.cognition.get("messaging", {}).get("contacts_by_actor", {}).get(actor, [])
        counts["phone_contacts"] += len(phone)
        contacts = [who for who in state.relationships.get(actor, {}) if who != actor
            and who in state.population and are_phone_contacts(state, actor, who)]
        contacts.sort(key=lambda who: (-state.relationships[actor][who].get("closeness", 0), who))
        counts["relationship_contacts"] += len(contacts)
        for other in contacts[:3]:
            if not outings.willing(state, actor, other, "companionship"):
                r = state.relationships.get(actor, {}).get(other, {})
                person = state.population[actor]
                if r.get("familiarity", 0) < 10: blockers["familiarity_under_10"] += 1
                if r.get("closeness", 0) + person["needs"].get("social", 0) + person["personality"]["extraversion"] < 75:
                    blockers["social_readiness_under_75"] += 1
                counts["unwilling_pairs"] += 1
                continue
            counts["willing_pairs"] += 1
            for location in outings.PLACES:
                problem = outings.slot_problem(state, actor, other, state.clock.day, state.clock.phase, location, graph)
                blockers[problem or "slot_legal"] += 1
        counts["candidate_rows"] += len(rows)
        for row in rows:
            margins[str(round(row["score"] - top_score))] += 1
        return rows

    def factory(*args):
        handler = original_factory(*args)
        def handle(context, request):
            result = handler(context, request)
            if request.action_id == "INVITE_CAMPUS_OUTING":
                counts["invitation_attempts"] += 1
                counts["invitation_result:" + result.code] += 1
            return result
        return handle

    with patch.object(outings, "outing_candidates", candidates), patch.object(outings, "make_outing_handler", factory), \
            patch("urllib.request.urlopen", side_effect=AssertionError("No paid API in diagnosis")):
        bridge = CampusKernelBridge(seed)
        assert not bridge.cognition_runtime.provider.configured
        for step in range(days * 4):
            state = bridge.kernel._state
            result = bridge.kernel.execute(SimulationCommand(f"outing-diagnosis:{seed}:{step}", "player", "ADVANCE_PHASE",
                state.revision, issued_day=state.clock.day, issued_phase=state.clock.phase))
            assert result.success, result.code
            if step % 4 == 3:
                print(json.dumps({"elapsed_days": (step + 1) // 4, "counts": dict(counts), "blockers": dict(blockers),
                    "score_margins": dict(margins)}, ensure_ascii=False), flush=True)
        print("OUTING_DIAGNOSIS_OK", flush=True)


if __name__ == "__main__": run()
