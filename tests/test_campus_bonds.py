"""Explicit readiness fixture; shared dates execute real travel and settlement.

This is protocol acceptance, not evidence that a natural NPC falls in love.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simulation.api.server import CampusKernelBridge
from simulation.persistence.kernel_checkpoint import save_kernel_checkpoint, load_kernel_checkpoint
from simulation.systems.campus_bonds import records, bond_view, bonds_invariant, willing, own_bond_context, advance_bonds, make_bond_handler
from simulation.systems.campus_messaging import _add_contact, load_campus_messaging_policy
from simulation.systems.campus_social import DEFAULT_RELATIONSHIP
from simulation.systems import ContentRegistry, DeterministicRngPool
from simulation.systems.transactions import TransactionContext
from simulation.actions.commands import SimulationCommand
from tests.test_campus_disputes import command
from tests.test_campus_contact_inquiries import as_npc
from tests.test_campus_combat_deployment import travel_to_location


def prepare_bond_fixture(bridge):
    state = bridge.kernel._state
    people = [n for n in state.population if n.startswith("campus_student_")][:3]
    for who in ["player", *people]:
        for day in state.population[who]["weekly_schedule"].values():
            for slot in day.values(): slot["priority"] = 10
        state.population[who]["needs"].update(rest=10, food=10, safety=10, social=70)
        for other in ["player", *people]:
            if who != other:
                _add_contact(state, who, other)
                state.relationships.setdefault(who, {})[other] = {**DEFAULT_RELATIONSHIP,
                    "familiarity": 70, "closeness": 70, "trust": 80}
    # Two actual completed dates with each of two contacts, never forged receipts.
    for day in (1, 2):
        for other, phase in zip(people[:2], ("afternoon", "evening")):
            result = as_npc(bridge, "player", "INVITE_CAMPUS_OUTING", {"target_id": other,
                "kind": "date", "day": day, "phase": phase, "location_id": "mirror_lake_square"})
            assert result.success, result.code
            key = result.payload["outing"]["outing_id"]
            while (bridge.kernel._state.clock.day, bridge.kernel._state.clock.phase) != (day, phase):
                advanced = command(bridge, "ADVANCE_PHASE", {})
                assert advanced["ok"], advanced
            travel_to_location(bridge, "mirror_lake_square")
            row = bridge.kernel._state.situations["campus_outings"]["records"][key]
            attended = command(bridge, "ATTEND_CAMPUS_OUTING", {"outing_id": key, "expected_revision": row["revision"]})
            assert attended["ok"], attended
            assert bridge.kernel._state.situations["campus_outings"]["records"][key]["status"] == "completed"
    return people


class BondTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = CampusKernelBridge(42)
        cls.people = prepare_bond_fixture(cls.bridge)
        cls.initial, cls.rng = cls.bridge.kernel.capture_checkpoint()

    def setUp(self):
        self.bridge.kernel.restore_checkpoint(self.initial, self.rng, expected_revision=self.bridge.kernel.state.revision)

    @property
    def state(self): return self.bridge.kernel._state

    def propose(self, actor="player", target=None, kind="romance"):
        return as_npc(self.bridge, actor, "PROPOSE_CAMPUS_BOND", {"target_id": target or self.people[0], "kind": kind})

    def op(self, action, row, actor="player", **overrides):
        return as_npc(self.bridge, actor, action, {"bond_id": row["bond_id"], "expected_revision": row["revision"], **overrides})

    def test_multiple_partners_and_ending_one_preserves_other(self):
        before = deepcopy((self.state.relationships, self.state.action_economy, self.state.clock))
        first = self.propose().payload["bond"]
        second = self.propose(target=self.people[1]).payload["bond"]
        self.assertEqual(("active", "active"), (first["status"], second["status"]))
        self.assertTrue(self.op("END_CAMPUS_BOND", first).success)
        self.assertEqual("active", records(self.state)[second["bond_id"]]["status"])
        own = {(r["other_id"], r["kind"]): r["status"] for r in own_bond_context(self.state, "player")}
        self.assertEqual("ended", own[(self.people[0], "romance")])
        self.assertEqual("active", own[(self.people[1], "romance")])
        # Pure projection fixture: JSON key order must not make an older request
        # override the actual latest status. This is not an executed world event.
        reordered = self.state.clone()
        older = deepcopy(first)
        older.update(bond_id="bond:999", created_day=1)
        records(reordered)["bond:999"] = older
        projected = {(r["other_id"], r["kind"]): r["status"] for r in own_bond_context(reordered, "player")}
        self.assertEqual("ended", projected[(self.people[0], "romance")])
        self.assertEqual(before, (self.state.relationships, self.state.action_economy, self.state.clock))
        self.assertEqual([], bonds_invariant(self.state))

    def test_player_consent_cannot_be_assumed(self):
        result = self.propose(actor=self.people[0], target="player")
        self.assertTrue(result.success, result.code)
        row = result.payload["bond"]
        self.assertEqual("pending", row["status"])
        self.assertEqual("recipient_required", self.op("ACCEPT_CAMPUS_BOND", row, actor=self.people[0]).code)
        self.assertTrue(self.op("ACCEPT_CAMPUS_BOND", row).success)

    def test_refusal_and_cooldown_do_not_punish(self):
        row = self.propose(actor=self.people[0], target="player").payload["bond"]
        before = deepcopy(self.state.relationships)
        self.assertTrue(self.op("DECLINE_CAMPUS_BOND", row).success)
        self.assertEqual("bond_pair_cooldown", self.propose().code)
        self.assertEqual(before, self.state.relationships)

    def test_high_affinity_without_shared_dates_is_not_romance(self):
        result = self.propose(target=self.people[2])
        self.assertTrue(result.success)
        self.assertEqual("declined", result.payload["bond"]["status"])
        self.assertFalse(willing(self.state, self.people[2], "player", "romance"))

    def test_friendship_separate_from_romance_and_no_free_gains(self):
        before = deepcopy(self.state.relationships)
        result = self.propose(kind="friendship", target=self.people[1])
        # Dawn may already have independently proposed friendship; that is not romance.
        self.assertTrue(result.success or result.code == "bond_already_live")
        self.assertFalse(any(r["kind"] == "romance" for r in records(self.state).values()))
        self.assertEqual(before, self.state.relationships)

    def test_outsider_cannot_see_or_mutate(self):
        row = self.propose().payload["bond"]
        self.assertNotIn(row["bond_id"], [r["bond_id"] for r in bond_view(self.state, self.people[2])["records"]])
        self.assertEqual("bond_not_visible", self.op("END_CAMPUS_BOND", row, actor=self.people[2]).code)
        self.assertFalse(any(r["kind"] == "romance" for r in own_bond_context(self.state, self.people[2])))

    def test_duplicate_stale_revision_and_malformed_parameters(self):
        row = self.propose().payload["bond"]
        self.assertEqual("bond_already_live", self.propose().code)
        for revision in (True, -1, float("nan"), [], {}):
            self.assertEqual("bond_revision_conflict", self.op("END_CAMPUS_BOND", row, expected_revision=revision).code)
        for fields in ({"target_id": []}, {"kind": []}, {"target_id": "player"}, {"target_id": "missing"}):
            result = as_npc(self.bridge, "player", "PROPOSE_CAMPUS_BOND", {"target_id": self.people[1], "kind": "romance", **fields})
            self.assertFalse(result.success)

    def test_suspicion_and_needs_can_block_even_after_dates(self):
        self.state.relationships[self.people[0]]["player"]["suspicion"] = 90
        self.assertEqual("declined", self.propose().payload["bond"]["status"])
        self.state.population[self.people[1]]["needs"]["safety"] = 95
        self.assertEqual("declined", self.propose(target=self.people[1]).payload["bond"]["status"])

    def test_personality_changes_readiness_without_partner_cap(self):
        actor = self.people[0]
        self.state.relationships[actor]["player"].update(trust=65, closeness=55)
        self.state.population[actor]["personality"]["emotional_sensitivity"] = 100
        self.assertFalse(willing(self.state, actor, "player", "romance"))
        self.state.population[actor]["personality"]["emotional_sensitivity"] = 0
        self.assertTrue(willing(self.state, actor, "player", "romance"))

    def test_checkpoint_preserves_multiple_bonds_and_old_save_compatibility(self):
        self.propose()
        self.propose(target=self.people[1])
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bonds.json"
            state, rng = self.bridge.kernel.capture_checkpoint()
            save_kernel_checkpoint(path, state, rng, content_manifest=self.bridge.registry.manifest)
            saved = load_kernel_checkpoint(path, expected_content_version=state.content_version)
            self.assertEqual(records(self.state), records(saved.state))
        old = self.state.clone()
        old.situations.pop("campus_bonds", None)
        self.assertEqual([], bonds_invariant(old))
        self.assertEqual([], bond_view(old)["records"])

    def test_invariant_rejects_duplicate_and_forged_consent(self):
        row = self.propose().payload["bond"]
        damaged = self.state.clone()
        duplicate = deepcopy(row)
        duplicate["bond_id"] = "bond:duplicate"
        damaged.situations["campus_bonds"]["records"][duplicate["bond_id"]] = duplicate
        self.assertTrue(bonds_invariant(damaged))
        damaged = self.state.clone()
        records(damaged)[row["bond_id"]]["history"][-1]["actor_id"] = "player"
        self.assertTrue(bonds_invariant(damaged))

    def test_autonomous_dawn_is_idempotent_and_never_accepts_for_player(self):
        policy = load_campus_messaging_policy(ContentRegistry.load_default(Path(__file__).resolve().parents[1] / "content"))
        # Find an initiative day without changing clock or executing a fake date.
        state = self.state.clone()
        state.clock.phase = "morning"
        state.cognition.pop("bonds_prepared_day", None)
        context = TransactionContext(state, DeterministicRngPool(42), SimulationCommand("dawn-test", "player", "ADVANCE_PHASE", state.revision, issued_day=state.clock.day))
        for actor in self.people[:2]:
            state.population[actor]["personality"]["extraversion"] = 100
        # Different seeded dawns test the pure upkeep; not a natural-world claim.
        for day in range(3, 15):
            state.clock.day = day
            advance_bonds(context, make_bond_handler(policy), policy)
            frozen = deepcopy(records(state))
            advance_bonds(context, make_bond_handler(policy), policy)
            self.assertEqual(frozen, records(state))
        romances = [r for r in records(state).values() if r["kind"] == "romance"]
        self.assertTrue(romances)
        self.assertTrue(all(r["status"] in {"pending", "expired"} for r in romances if r["recipient_id"] == "player"))

    def test_npc_to_npc_real_outing_can_lead_to_mutual_friendship(self):
        first, second = self.people[:2]
        invited = as_npc(self.bridge, first, "INVITE_CAMPUS_OUTING", {"target_id": second,
            "day": 3, "phase": "afternoon", "location_id": "mirror_lake_square", "kind": "companionship"})
        self.assertTrue(invited.success, invited.code)
        while (self.state.clock.day, self.state.clock.phase) != (3, "afternoon"):
            self.assertTrue(command(self.bridge, "ADVANCE_PHASE", {})["ok"])
        outing = self.state.situations["campus_outings"]["records"][invited.payload["outing"]["outing_id"]]
        self.assertEqual("completed", outing["status"])
        result = self.propose(actor=first, target=second, kind="friendship")
        self.assertTrue(result.success, result.code)
        self.assertEqual("active", result.payload["bond"]["status"])
        self.assertNotIn("player", (result.payload["bond"]["proposer_id"], result.payload["bond"]["recipient_id"]))

    def test_llm_context_knows_own_bonds_not_other_peoples_partners(self):
        from simulation.domain.cognition import BoundedDialogueRequest, BoundedDecisionRequest
        from simulation.systems.campus_cognition import bind_cognition_identity
        self.propose()
        self.propose(target=self.people[1])
        actor = self.people[0]
        requests = [BoundedDecisionRequest(actor, 1, 1, "morning", {}, {}, "", (), ()),
            BoundedDialogueRequest(actor, "player", 1, 1, "morning", {}, {}, {}, (), "你好", (), "player", {})]
        for request in requests:
            bound = bind_cognition_identity(self.state, request)
            own = bound.state["own_bond_statuses"]
            self.assertTrue(any(r["kind"] == "romance" and r["other_id"] == "player" for r in own))
            self.assertFalse(any(r["other_id"] == self.people[1] and r["kind"] == "romance" for r in own))

    def test_player_source_cannot_impersonate_npc_and_command_replay(self):
        state = self.state
        request = SimulationCommand("bond-replay-test", "player", "PROPOSE_CAMPUS_BOND", state.revision,
            issued_day=state.clock.day, issued_phase=state.clock.phase,
            parameters={"target_id": self.people[0], "kind": "romance"})
        rejected = self.bridge.kernel.execute(replace(request, command_id="bond-spoof", actor_id=self.people[1]))
        self.assertFalse(rejected.success)
        first = self.bridge.kernel.execute(request)
        self.assertTrue(first.success, first.code)
        count = len(records(self.state))
        replay = self.bridge.kernel.execute(request)
        self.assertTrue(replay.success, replay.code)
        self.assertEqual(count, len(records(self.state)))

    def test_daily_planner_offers_date_and_companionship_separately(self):
        from collections import Counter
        from types import SimpleNamespace
        from simulation.systems import load_campus_location_graph, load_campus_activity_definitions, load_campus_decision_policy
        from simulation.systems.campus_outings import outing_candidates
        # Existing completed dates remain facts; inspect a later, free schedule.
        self.propose()
        state = self.state.clone()
        state.clock.day = 4
        state.clock.phase = "afternoon"
        actor = self.people[0]
        # This is a future planning preview, so use that phase's refreshed
        # budgets rather than the already-spent budgets of the fixture's dates.
        for who in (actor, "player"):
            state.action_economy["actors"][who]["major_remaining"] = 1
        graph = load_campus_location_graph(self.bridge.registry)
        definitions = load_campus_activity_definitions(self.bridge.registry)
        policy = load_campus_decision_policy(self.bridge.registry, definitions, graph)
        options = outing_candidates(SimpleNamespace(state=state), actor, {"priority": 10}, graph, Counter(), policy, 100)
        own = [r for r in options if r["parameters"]["outing_intent"]["target_id"] == "player"]
        self.assertEqual({"date", "companionship"}, {r["parameters"]["outing_intent"]["kind"] for r in own})
        self.assertEqual(len(own), len({r["candidate_id"] for r in own}))


if __name__ == "__main__": unittest.main()
