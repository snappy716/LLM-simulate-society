"""Central, versioned loader for data-driven game content."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


class ContentValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ContentSource:
    relative_path: str
    kind: str
    collection_key: Optional[str] = None
    id_field: str = "id"
    mapping_entries: bool = False
    singleton_id: Optional[str] = None


DEFAULT_CONTENT_SOURCES: Tuple[ContentSource, ...] = (
    ContentSource("items/catalog.json", "item", "items"),
    ContentSource("items/uses.json", "item_use", "uses", id_field="item_id"),
    ContentSource("items/shops.json", "shop", "shops"),
    ContentSource("items/placements.json", "item_placement", "placements", id_field="inventory_id:item_id"),
    ContentSource("locations/passages.json", "passage", "passages"),
    ContentSource("locations/scene_regions.json", "location", mapping_entries=True),
    ContentSource("locations/campus_regions.json", "campus_region", "regions"),
    ContentSource("locations/interior_templates.json", "interior_template", "templates"),
    ContentSource("locations/campus_locations.json", "campus_location", "locations"),
    ContentSource("locations/campus_passages.json", "campus_passage", "passages"),
    ContentSource("actions/college_skills.json", "college", "colleges"),
    ContentSource("actions/college_skills.json", "campus_ability", "abilities"),
    ContentSource("actions/action_economy.json", "configuration", singleton_id="action_economy"),
    ContentSource("actions/campus_activities.json", "campus_activity", "activities"),
    ContentSource(
        "actions/campus_decisions.json",
        "configuration",
        singleton_id="campus_decisions",
    ),
    ContentSource(
        "actions/campus_interactions.json",
        "configuration",
        singleton_id="campus_interactions",
    ),
    ContentSource(
        "actions/campus_messaging.json",
        "configuration",
        singleton_id="campus_messaging",
    ),
    ContentSource("actions/campus_schedules.json", "schedule_template", "templates"),
    ContentSource("organizations/clubs.json", "club", "clubs"),
    ContentSource(
        "organizations/party_policy.json",
        "configuration",
        singleton_id="party_policy",
    ),
    ContentSource("situations/surface_tasks.json", "surface_task_template", "templates"),
    ContentSource(
        "situations/forum_policy.json",
        "configuration",
        singleton_id="forum_policy",
    ),
    ContentSource("npcs/generation_rules.json", "configuration", singleton_id="npc_generation"),
    ContentSource("npcs/campus_population.json", "configuration", singleton_id="campus_population"),
    ContentSource("npcs/cognition_policy.json", "configuration", singleton_id="cognition_policy"),
    ContentSource("main_story/demo_calendar.json", "configuration", singleton_id="demo_calendar"),
    ContentSource("situations/enemy_archetypes.json", "enemy_archetype", "archetypes"),
)


class ContentRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._entries: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._documents: Dict[str, Dict[str, Any]] = {}
        self._manifest: Dict[str, Dict[str, Any]] = {}
        self._content_version = "unloaded"

    @property
    def content_version(self) -> str:
        return self._content_version

    @property
    def manifest(self) -> Dict[str, Dict[str, Any]]:
        return deepcopy(self._manifest)

    @classmethod
    def load_default(cls, root: Path) -> "ContentRegistry":
        registry = cls(root)
        registry.load(DEFAULT_CONTENT_SOURCES)
        registry.validate_references()
        return registry

    def load(self, sources: Iterable[ContentSource]) -> None:
        if self._documents:
            raise RuntimeError("content registry has already been loaded")
        for source in sources:
            self._load_source(source)
        digest = hashlib.sha256()
        for relative_path, record in sorted(self._manifest.items()):
            digest.update(relative_path.encode("utf-8"))
            digest.update(record["sha256"].encode("ascii"))
        self._content_version = digest.hexdigest()[:16]

    def kinds(self) -> list[str]:
        return sorted(self._entries)

    def ids(self, kind: str) -> list[str]:
        return sorted(self._entries.get(kind, {}))

    def get(self, kind: str, content_id: str) -> Dict[str, Any]:
        try:
            return deepcopy(self._entries[kind][content_id])
        except KeyError as exc:
            raise KeyError(f"unknown {kind}: {content_id}") from exc

    def all(self, kind: str) -> Dict[str, Dict[str, Any]]:
        return deepcopy(self._entries.get(kind, {}))

    def document(self, relative_path: str) -> Dict[str, Any]:
        try:
            return deepcopy(self._documents[relative_path])
        except KeyError as exc:
            raise KeyError(f"content document was not loaded: {relative_path}") from exc

    def validate_references(self) -> None:
        errors: list[str] = []
        item_ids = set(self.ids("item"))
        location_ids = set(self.ids("location"))
        for item_use_id in self.ids("item_use"):
            if item_use_id not in item_ids:
                errors.append(f"item_use references unknown item: {item_use_id}")
        for placement in self.all("item_placement").values():
            if placement.get("item_id") not in item_ids:
                errors.append(f"placement references unknown item: {placement.get('item_id')}")
        for shop in self.all("shop").values():
            if shop.get("scene_id") not in location_ids:
                errors.append(f"shop {shop.get('id')} references unknown location: {shop.get('scene_id')}")
            for item_id in shop.get("stock", {}):
                if item_id not in item_ids:
                    errors.append(f"shop {shop.get('id')} stocks unknown item: {item_id}")
        for passage in self.all("passage").values():
            for field_name in ("scene_a", "scene_b"):
                scene_id = passage.get(field_name)
                if scene_id not in location_ids:
                    errors.append(f"passage {passage.get('id')} references unknown location: {scene_id}")
            key_item_id = passage.get("key_item_id")
            if key_item_id and key_item_id not in item_ids:
                errors.append(f"passage {passage.get('id')} references unknown key item: {key_item_id}")
        campus_region_ids = set(self.ids("campus_region"))
        campus_location_ids = set(self.ids("campus_location"))
        campus_node_ids = campus_region_ids | campus_location_ids
        template_ids = set(self.ids("interior_template"))
        for location in self.all("campus_location").values():
            if location.get("region_id") not in campus_region_ids:
                errors.append(
                    f"campus location {location.get('id')} references unknown region: {location.get('region_id')}"
                )
            if location.get("parent_id") not in campus_node_ids:
                errors.append(
                    f"campus location {location.get('id')} references unknown parent: {location.get('parent_id')}"
                )
            template_id = location.get("interior_template_id")
            if template_id and template_id not in template_ids:
                errors.append(
                    f"campus location {location.get('id')} references unknown template: {template_id}"
                )
        for passage in self.all("campus_passage").values():
            for field_name in ("from_id", "to_id"):
                node_id = passage.get(field_name)
                if node_id not in campus_node_ids:
                    errors.append(
                        f"campus passage {passage.get('id')} references unknown node: {node_id}"
                    )
        schedule_ids = set(self.ids("schedule_template"))
        activity_ids = set(self.ids("campus_activity"))
        activity_profiles = (
            self.document("actions/campus_activities.json").get("profiles", {})
            if activity_ids else {}
        )
        for activity in self.all("campus_activity").values():
            if activity.get("profile_id") not in activity_profiles:
                errors.append(
                    f"campus activity {activity.get('id')} references unknown profile: "
                    f"{activity.get('profile_id')}"
                )
        for schedule in self.all("schedule_template").values():
            for day_kind in ("weekday", "weekend"):
                for phase, slot in schedule.get(day_kind, {}).items():
                    activity_id = slot.get("activity_id")
                    if activity_id not in activity_ids:
                        errors.append(
                            f"schedule {schedule.get('id')} references unknown activity: {activity_id}"
                        )
                        continue
                    activity = self.get("campus_activity", activity_id)
                    if slot.get("action_class") != activity.get("action_class"):
                        errors.append(
                            f"schedule {schedule.get('id')} action class differs for {activity_id}"
                        )
                    if phase not in activity.get("allowed_phases", []):
                        errors.append(
                            f"schedule {schedule.get('id')} uses {activity_id} in forbidden phase {phase}"
                        )
        decision_config = self.all("configuration").get("campus_decisions", {})
        for alternative in decision_config.get("alternatives", []):
            if not isinstance(alternative, dict):
                errors.append("campus decision alternative must be a mapping")
                continue
            activity_id = alternative.get("activity_id")
            if activity_id not in activity_ids:
                errors.append(
                    f"campus decision {alternative.get('id')} references unknown activity: {activity_id}"
                )
                continue
            activity = self.get("campus_activity", activity_id)
            forbidden = set(alternative.get("allowed_phases", [])) - set(
                activity.get("allowed_phases", [])
            )
            if forbidden:
                errors.append(
                    f"campus decision {alternative.get('id')} uses {activity_id} in forbidden phases: "
                    + ", ".join(sorted(forbidden))
                )
        population_config = self.all("configuration").get("campus_population", {})
        party_policy = self.all("configuration").get("party_policy", {})
        if party_policy:
            for field_name in (
                "max_members", "invitation_score_threshold", "withdrawal_score_threshold",
                "minimum_commitment_days", "same_college_bonus", "shared_club_bonus",
            ):
                value = party_policy.get(field_name)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    errors.append(f"party policy requires non-negative {field_name}")
            access_modifiers = party_policy.get("night_access_modifiers", {})
            if not isinstance(access_modifiers, dict) or set(access_modifiers) != {
                "unaware", "sensitive", "capable", "willing",
            }:
                errors.append("party policy requires all night access modifiers")
            relationship_skills = party_policy.get("relationship_skills", {})
            configured_skills = set(population_config.get("relationship_skills", ()))
            if not isinstance(relationship_skills, dict) or set(relationship_skills) != configured_skills:
                errors.append("party policy relationship skills must match population generation")
            elif any(
                not isinstance(definition, dict)
                or not definition.get("name")
                or not definition.get("description")
                or not isinstance(definition.get("battle_effect"), dict)
                for definition in relationship_skills.values()
            ):
                errors.append("party relationship skill definitions are invalid")
        referenced_schedules = set(population_config.get("schedules", {}).values())
        unknown_schedules = referenced_schedules - schedule_ids
        if unknown_schedules:
            errors.append(
                "campus population references unknown schedules: "
                + ", ".join(sorted(unknown_schedules))
            )
        surface_task_ids = set(self.ids("surface_task_template"))
        club_ids = set(self.ids("club"))
        college_ids = set(self.ids("college"))
        ability_ids = set(self.ids("campus_ability"))
        if college_ids or ability_ids:
            ability_profiles = self.document("actions/college_skills.json").get(
                "ability_profiles", {}
            )
            if not isinstance(ability_profiles, dict):
                errors.append("college skill ability_profiles must be a mapping")
                ability_profiles = {}
            for ability in self.all("campus_ability").values():
                if ability.get("college_id") not in college_ids:
                    errors.append(
                        f"campus ability {ability.get('id')} references unknown college: "
                        f"{ability.get('college_id')}"
                    )
                if ability.get("profile_id") not in ability_profiles:
                    errors.append(
                        f"campus ability {ability.get('id')} references unknown profile: "
                        f"{ability.get('profile_id')}"
                    )
                if ability.get("source_kind") not in {"common", "specialization"}:
                    errors.append(
                        f"campus ability {ability.get('id')} has invalid source kind: "
                        f"{ability.get('source_kind')}"
                    )
                check_tags = ability.get("check_tags")
                if not isinstance(check_tags, list) or not check_tags or any(
                    not isinstance(tag, str) or not tag for tag in check_tags
                ):
                    errors.append(
                        f"campus ability {ability.get('id')} requires non-empty check tags"
                    )
            for college in self.all("college").values():
                college_id = college.get("id")
                expected_common = {
                    ability_id
                    for ability_id, ability in self.all("campus_ability").items()
                    if ability.get("college_id") == college_id
                    and ability.get("source_kind") == "common"
                }
                expected_specializations = {
                    ability_id
                    for ability_id, ability in self.all("campus_ability").items()
                    if ability.get("college_id") == college_id
                    and ability.get("source_kind") == "specialization"
                }
                common = set(college.get("common_skills", ()))
                specializations = set(college.get("specializations", ()))
                if common != expected_common:
                    errors.append(f"college {college_id} common abilities do not match definitions")
                if specializations != expected_specializations:
                    errors.append(
                        f"college {college_id} specialization abilities do not match definitions"
                    )
                unknown = (common | specializations) - ability_ids
                if unknown:
                    errors.append(
                        f"college {college_id} references unknown abilities: "
                        + ", ".join(sorted(unknown))
                    )
        club_skill_owners: Dict[str, str] = {}
        club_runtime_policy = (
            self.document("organizations/clubs.json").get("runtime_policy", {})
            if club_ids else {}
        )
        if club_ids and not isinstance(club_runtime_policy, dict):
            errors.append("club runtime_policy must be a mapping")
        elif club_ids:
            thresholds = club_runtime_policy.get("rank_thresholds", {})
            if not isinstance(thresholds, dict) or set(thresholds) != {"member", "core_member", "leader"}:
                errors.append("club runtime_policy must define all rank thresholds")
            for field_name in (
                "activity_contribution", "activity_resource_gain", "task_contribution",
                "task_resource_gain", "daily_resource_cost", "resource_capacity",
                "initial_resource", "core_member_limit", "tactic_resource_cost",
                "recruitment_score_threshold", "existing_membership_penalty",
            ):
                value = club_runtime_policy.get(field_name)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    errors.append(f"club runtime_policy requires non-negative {field_name}")
        for club in self.all("club").values():
            club_id = str(club.get("id", ""))
            for required_field in ("category", "signature_resource", "night_skill_name"):
                if not isinstance(club.get(required_field), str) or not club.get(required_field):
                    errors.append(f"club {club_id} requires {required_field}")
            unknown_overlaps = set(club.get("college_overlap_ids", ())) - college_ids
            if unknown_overlaps:
                errors.append(
                    f"club {club_id} references unknown college overlaps: "
                    + ", ".join(sorted(unknown_overlaps))
                )
            activity_slots = club.get("activity_slots")
            if not isinstance(activity_slots, list) or not activity_slots:
                errors.append(f"club {club_id} requires activity_slots")
            else:
                for slot in activity_slots:
                    if (
                        not isinstance(slot, dict)
                        or slot.get("phase") not in {"morning", "afternoon", "evening"}
                        or not isinstance(slot.get("days"), list)
                        or not slot["days"]
                        or any(isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6 for day in slot["days"])
                        or len(slot["days"]) != len(set(slot["days"]))
                    ):
                        errors.append(f"club {club_id} has invalid activity slot")
            for field_name in ("surface_skill", "night_skill"):
                skill_id = club.get(field_name)
                if not isinstance(skill_id, str) or not skill_id:
                    errors.append(f"club {club_id} requires {field_name}")
                    continue
                if skill_id in ability_ids:
                    errors.append(
                        f"club {club_id} skill {skill_id} duplicates a college ability"
                    )
                previous_owner = club_skill_owners.get(skill_id)
                if previous_owner is not None:
                    errors.append(
                        f"club skill {skill_id} is shared by {previous_owner} and {club_id}"
                    )
                club_skill_owners[skill_id] = club_id
        for template in self.all("surface_task_template").values():
            activity_id = template.get("activity_id")
            scene_id = template.get("scene_id")
            if activity_id not in activity_ids:
                errors.append(
                    f"surface task {template.get('id')} references unknown activity: {activity_id}"
                )
            if scene_id not in campus_node_ids:
                errors.append(
                    f"surface task {template.get('id')} references unknown campus location: {scene_id}"
                )
            organization_id = template.get("organization_id")
            if organization_id and organization_id not in club_ids:
                errors.append(
                    f"surface task {template.get('id')} references unknown organization: {organization_id}"
                )
            unknown_preferred_clubs = set(template.get("preferred_club_ids", ())) - club_ids
            if unknown_preferred_clubs:
                errors.append(
                    f"surface task {template.get('id')} references unknown preferred clubs: "
                    + ", ".join(sorted(unknown_preferred_clubs))
                )
            unknown_preferred_colleges = set(template.get("preferred_college_ids", ())) - college_ids
            if unknown_preferred_colleges:
                errors.append(
                    f"surface task {template.get('id')} references unknown preferred colleges: "
                    + ", ".join(sorted(unknown_preferred_colleges))
                )
            unknown_follow_ups = set(template.get("follow_up_template_ids", ())) - surface_task_ids
            if unknown_follow_ups:
                errors.append(
                    f"surface task {template.get('id')} references unknown follow-ups: "
                    + ", ".join(sorted(unknown_follow_ups))
                )
            parent_id = template.get("chain_parent_template_id")
            if parent_id and parent_id not in surface_task_ids:
                errors.append(
                    f"surface task {template.get('id')} references unknown chain parent: {parent_id}"
                )
        if errors:
            raise ContentValidationError("invalid content references: " + "; ".join(errors))

    def _load_source(self, source: ContentSource) -> None:
        relative = Path(source.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ContentValidationError(f"content path must stay below content root: {source.relative_path}")
        path = (self.root / relative).resolve()
        if self.root not in path.parents:
            raise ContentValidationError(f"content path escapes content root: {source.relative_path}")
        if not path.is_file():
            raise ContentValidationError(f"missing content file: {source.relative_path}")
        raw = path.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContentValidationError(f"invalid JSON in {source.relative_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ContentValidationError(f"content document must be an object: {source.relative_path}")
        schema_version = payload.get("schema_version", 1 if source.mapping_entries else None)
        if schema_version != 1:
            raise ContentValidationError(
                f"unsupported content schema in {source.relative_path}: {schema_version}"
            )
        self._documents[source.relative_path] = deepcopy(payload)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self._manifest[source.relative_path] = {
            "schema_version": schema_version,
            "sha256": hashlib.sha256(canonical).hexdigest(),
        }
        if source.singleton_id is not None:
            self._register(source.kind, source.singleton_id, payload, source.relative_path)
            return
        if source.mapping_entries:
            entries = {key: value for key, value in payload.items() if key != "schema_version"}
            for content_id, value in entries.items():
                if not isinstance(value, dict):
                    raise ContentValidationError(f"{source.relative_path}:{content_id} must be an object")
                entry = {"id": content_id, **value}
                self._register(source.kind, content_id, entry, source.relative_path)
            return
        if source.collection_key is None:
            raise ContentValidationError(f"collection key is required for {source.relative_path}")
        entries = payload.get(source.collection_key)
        if not isinstance(entries, list):
            raise ContentValidationError(
                f"{source.relative_path}:{source.collection_key} must be an array"
            )
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ContentValidationError(f"{source.relative_path}[{index}] must be an object")
            content_id = self._entry_id(entry, source.id_field)
            self._register(source.kind, content_id, entry, source.relative_path)

    @staticmethod
    def _entry_id(entry: Dict[str, Any], id_field: str) -> str:
        field_names = id_field.split(":")
        values = [entry.get(field_name) for field_name in field_names]
        if any(not isinstance(value, str) or not value for value in values):
            raise ContentValidationError(f"content entry is missing identifier field(s): {id_field}")
        return ":".join(values)

    def _register(self, kind: str, content_id: str, entry: Dict[str, Any], source: str) -> None:
        bucket = self._entries.setdefault(kind, {})
        if content_id in bucket:
            raise ContentValidationError(f"duplicate {kind} id {content_id} in {source}")
        bucket[content_id] = deepcopy(entry)


__all__ = [
    "ContentRegistry",
    "ContentSource",
    "ContentValidationError",
    "DEFAULT_CONTENT_SOURCES",
]
