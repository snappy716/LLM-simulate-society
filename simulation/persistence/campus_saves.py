"""Player slots: checked checkpoints, one recoverable backup, no client paths."""
import hashlib
import json
import os
from uuid import uuid4
from contextlib import contextmanager
from pathlib import Path

from simulation.persistence.kernel_checkpoint import build_kernel_checkpoint, load_kernel_checkpoint, CheckpointError
from simulation.persistence.snapshot import atomic_write_json

SLOTS = ("slot_1", "slot_2", "slot_3")
PRESENTATION_MAPS = ("campus_gate", "living_area", "east_dormitory", "west_dormitory", "psychology_bridge", "library", "sports_field")


class SaveError(ValueError):
    pass


class CampusSaveStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def path(self, slot, backup=False):
        if slot not in SLOTS:
            raise SaveError("请选择有效的存档槽。")
        path = self.directory / (slot + (".previous" if backup else "") + ".json")
        if path.is_symlink() or path.with_suffix(path.suffix + ".tmp").is_symlink():
            raise SaveError("存档路径不能是符号链接。")
        return path

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_path = self.directory / ".slots.lock"
        if lock_path.is_symlink():
            raise SaveError("存档锁路径无效。")
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def token(path):
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""

    def listing(self):
        result = []
        for slot in SLOTS:
            versions = {}
            for backup in (False, True):
                path = self.path(slot, backup)
                entry = {"exists": path.exists(), "token": self.token(path), "status": "empty"}
                if entry["exists"]:
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                        world = data["world"]
                        player = world["population"]["player"]
                        entry.update(status="present", day=world["clock"]["day"], phase=world["clock"]["phase"],
                                     location_id=player["current_location_id"], revision=world["revision"])
                    except (ValueError, KeyError, TypeError, UnicodeError):
                        entry.update(status="invalid")
                versions["backup" if backup else "current"] = entry
            result.append({"slot_id": slot, **versions})
        return result

    def save(self, slot, state, rng, manifest, *, expected_token, confirmed):
        path = self.path(slot)
        actual = self.token(path)
        if actual != expected_token:
            raise SaveError("存档槽已改变，请刷新后再操作。")
        if actual and confirmed is not True:
            raise SaveError("覆盖已有存档需要确认。")
        payload = build_kernel_checkpoint(state, rng, content_manifest=manifest)
        preserved_invalid = False
        if actual:
            # Never replace a good backup with a corrupt current file.
            try:
                load_kernel_checkpoint(path)
            except CheckpointError:
                archive = self.directory / (slot + ".invalid-" + uuid4().hex + ".json")
                with archive.open("xb") as handle:
                    handle.write(path.read_bytes())
                preserved_invalid = True
            else:
                atomic_write_json(self.path(slot, True), json.loads(path.read_text(encoding="utf-8")))
        atomic_write_json(path, payload)
        return preserved_invalid

    def load(self, slot, *, backup, expected_token, confirmed, content_version):
        path = self.path(slot, backup)
        if confirmed is not True:
            raise SaveError("读档将放弃未保存进度，需要确认。")
        if not path.exists() or self.token(path) != expected_token:
            raise SaveError("存档不存在或已改变，请刷新后再操作。")
        loaded = load_kernel_checkpoint(path, expected_content_version=content_version)
        state = loaded.state
        if state.metadata.get("save_presentation_map", "") not in ("", *PRESENTATION_MAPS):
            raise CheckpointError("存档的展示地图无效，原档未修改。")
        if ("player" not in state.population or not state.inventories.get("trade")
                or not state.inventories.get("supply") or not state.population["player"].get("vitals")):
            raise CheckpointError("此旧档缺少校园资源系统，需要专用迁移；当前世界和原档未修改。")
        # Known additive runtime policy migration only; no refilling inventories,
        # creating people, healing old characters, or changing unknown content.
        changes = []
        for key, value in {"food_reorder_nutrition": 25, "food_buffer_nutrition": [100, 150]}.items():
            if key not in state.inventories["trade"]["policy"]:
                state.inventories["trade"]["policy"][key] = value
                changes.append(key)
        return loaded, changes
