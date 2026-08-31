"""Regenerate the human-readable NPC roster from the simulation defaults."""

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from town_demo import Config, World


WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def main():
    with tempfile.TemporaryDirectory() as temp_dir:
        world = World(Config(llm_mode="rule", log_dir=temp_dir, verbose=False))
    target = ROOT / "docs" / "NPC_ROSTER.csv"
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "NPC代号", "层级", "职业", "隶属地点", "住所", "工作日", "工作时段",
            "序列途径", "序列等级", "特殊需求",
        ])
        for npc in sorted(world.npcs.values(), key=lambda item: int(item.name)):
            writer.writerow([
                npc.name,
                npc.layer,
                npc.occupation,
                world.scenes[npc.work_scene].name,
                world.scenes[npc.home_scene].name,
                "、".join(WEEKDAYS[day] for day in npc.work_days),
                "、".join(npc.work_phases),
                npc.sequence_pathway or "",
                npc.sequence_rank or "",
                "、".join(f"{key}:{value}" for key, value in npc.special_needs.items()),
            ])


if __name__ == "__main__":
    main()
