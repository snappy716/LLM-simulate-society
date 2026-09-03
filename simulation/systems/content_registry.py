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
    ContentSource("actions/action_economy.json", "configuration", singleton_id="action_economy"),
    ContentSource("organizations/clubs.json", "club", "clubs"),
    ContentSource("npcs/generation_rules.json", "configuration", singleton_id="npc_generation"),
    ContentSource("npcs/campus_population.json", "configuration", singleton_id="campus_population"),
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
