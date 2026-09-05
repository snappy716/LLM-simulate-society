"""Local configuration loading without constructing any simulation world."""
import json
from pathlib import Path


def load_runtime_settings(project_dir=None):
    project_dir = Path(project_dir) if project_dir is not None else Path(__file__).resolve().parent
    settings = {}
    for filename in ("config.json", "config.local.json"):
        path = project_dir / filename
        if not path.exists():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"无法读取运行配置 {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise RuntimeError(f"运行配置 {path} 必须是 JSON 对象")
        settings.update(loaded)
    return settings
