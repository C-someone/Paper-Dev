from __future__ import annotations

from pathlib import Path

from paper_watcher.models import AppConfig


def resolve_project_path(config: AppConfig, path: Path) -> Path:
    if path.is_absolute():
        return path
    return config.config_dir.parent / path
