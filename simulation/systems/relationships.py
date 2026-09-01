"""Relationship network construction and social-system entry points."""
from __future__ import annotations

from collections import defaultdict

from simulation.domain.entities import Relationship


def add_mutual_relationship(a, b, kind, trust=50, affection=0, suspicion=0, fear=0):
    for owner, target in ((a, b), (b, a)):
        relation = owner.relationships.setdefault(target.id, Relationship())
        if kind not in relation.kinds:
            relation.kinds.append(kind)
        relation.trust = max(0, min(100, trust))
        relation.affection = max(-100, min(100, affection))
        relation.suspicion = max(0, min(100, suspicion))
        relation.fear = max(0, min(100, fear))


def build_initial_relationship_network(npcs, rng):
    residents = list(npcs.values())
    by_workplace = defaultdict(list)
    for npc in residents:
        by_workplace[npc.work_scene].append(npc)
    for colleagues in by_workplace.values():
        rng.shuffle(colleagues)
        for index, npc in enumerate(colleagues):
            if len(colleagues) > 1:
                add_mutual_relationship(
                    npc, colleagues[(index + 1) % len(colleagues)],
                    "同事", trust=58, affection=12,
                )

    shuffled = residents[:]
    rng.shuffle(shuffled)
    for index, npc in enumerate(shuffled):
        add_mutual_relationship(
            npc, shuffled[(index + 1) % len(shuffled)],
            "朋友", trust=72, affection=48,
        )

    candidates = shuffled[:60]
    for index in range(0, len(candidates) - 1, 2):
        a, b = candidates[index], candidates[index + 1]
        if "朋友" not in a.relationships.get(b.id, Relationship()).kinds:
            add_mutual_relationship(
                a, b, "仇人", trust=8, affection=-65, suspicion=75, fear=12,
            )

    lover_candidates = shuffled[60:100]
    for index in range(0, len(lover_candidates) - 1, 2):
        a, b = lover_candidates[index], lover_candidates[index + 1]
        if "仇人" not in a.relationships.get(b.id, Relationship()).kinds:
            add_mutual_relationship(a, b, "爱人", trust=82, affection=85)

    former_candidates = shuffled[100:160]
    cursor = 0
    while cursor + 1 < len(former_candidates):
        a, b = former_candidates[cursor], former_candidates[cursor + 1]
        cursor += 2
        if (
            a.work_scene != b.work_scene
            and "仇人" not in a.relationships.get(b.id, Relationship()).kinds
        ):
            add_mutual_relationship(
                a, b, "前同事", trust=50, affection=8, suspicion=8,
            )


def arrange_social_invitations(*args, **kwargs):
    from simulation.runtime import arrange_social_invitations as implementation
    return implementation(*args, **kwargs)


def interaction_score(*args, **kwargs):
    from simulation.runtime import interaction_score as implementation
    return implementation(*args, **kwargs)


def relationship_between(*args, **kwargs):
    from simulation.runtime import relationship_between as implementation
    return implementation(*args, **kwargs)


__all__ = [
    "add_mutual_relationship", "arrange_social_invitations",
    "build_initial_relationship_network", "interaction_score", "relationship_between",
]
