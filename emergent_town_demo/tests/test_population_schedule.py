import unittest

from town_demo import (Config, NPCLayer, Phase, World, arrange_social_invitations,
                       mutual_relationship_kind, rule_plan_for_npc)


class PopulationScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World(Config(core_npcs=20, simple_npcs=180, llm_mode="rule",
                                 log_dir="runs/test_population_schedule", verbose=False))

    def test_default_population_has_200_numbered_residents_and_20_beyonders(self):
        self.assertEqual(200, len(self.world.npcs))
        self.assertEqual([str(i) for i in range(1, 201)],
                         [npc.name for npc in self.world.npcs.values()])
        beyonders = [npc for npc in self.world.npcs.values()
                     if npc.layer != NPCLayer.ORDINARY.value]
        self.assertEqual(20, len(beyonders))

    def test_every_resident_has_a_weekly_schedule(self):
        for npc in self.world.npcs.values():
            self.assertTrue(npc.work_days)
            self.assertTrue(npc.work_phases)
            self.assertTrue(all(0 <= day <= 6 for day in npc.work_days))
            self.assertIn(npc.work_scene, self.world.scenes)

    def test_ordinary_worker_uses_fixed_rule_plan(self):
        npc = next(n for n in self.world.npcs.values()
                   if n.layer == NPCLayer.ORDINARY.value and 0 in n.work_days
                   and Phase.MORNING.value in n.work_phases)
        plan = rule_plan_for_npc(self.world, npc, planned_day=1)["morning"]
        self.assertEqual("WORK", plan.behavior)
        self.assertEqual(npc.work_scene, plan.scene_id)
        self.assertIn(npc.occupation, plan.intent)
        self.assertIn(self.world.scenes[npc.work_scene].name, plan.intent)

    def test_workday_has_two_work_slots_one_free_slot_and_one_home_rest_slot(self):
        npc = next(n for n in self.world.npcs.values()
                   if n.layer == NPCLayer.ORDINARY.value and 0 in n.work_days)
        plans = rule_plan_for_npc(self.world, npc, planned_day=1)
        behaviors = [plan.behavior for plan in plans.values()]
        self.assertEqual(2, behaviors.count("WORK"))
        self.assertEqual(1, behaviors.count("REST"))
        rest = next(plan for plan in plans.values() if plan.behavior == "REST")
        self.assertEqual(npc.home_scene, rest.scene_id)
        self.assertEqual(1, sum(plan.behavior not in {"WORK", "REST"}
                                for plan in plans.values()))

    def test_homes_are_unique_and_relationship_types_are_reciprocal(self):
        homes = [npc.home_scene for npc in self.world.npcs.values()]
        self.assertEqual(len(homes), len(set(homes)))
        for npc in self.world.npcs.values():
            for target_id, relation in npc.relationships.items():
                reverse = self.world.npcs[target_id].relationships.get(npc.id)
                self.assertIsNotNone(reverse)
                self.assertEqual(set(relation.kinds), set(reverse.kinds))

    def test_accepted_invitation_writes_both_plans(self):
        for npc in self.world.npcs.values():
            npc.daily_plan = rule_plan_for_npc(self.world, npc, planned_day=1)
        arrange_social_invitations(self.world, 1, max_invitations=100)
        accepted = [item for item in self.world.invitations.values()
                    if item.day == 1 and item.status == "accepted"]
        self.assertTrue(accepted)
        for item in accepted:
            inviter = self.world.npcs[item.inviter_id]
            invitee = self.world.npcs[item.invitee_id]
            self.assertEqual(item.invitee_id, inviter.daily_plan[item.phase].target_id)
            self.assertEqual(item.inviter_id, invitee.daily_plan[item.phase].target_id)
            self.assertEqual("MEET_PERSON", inviter.daily_plan[item.phase].behavior)
            self.assertEqual(item.required_relationship,
                             mutual_relationship_kind(inviter, invitee))


if __name__ == "__main__":
    unittest.main()
