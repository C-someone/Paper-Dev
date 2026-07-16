from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from paper_watcher.config_loader import ConfigError, load_config
from paper_watcher.models import AppConfig


CONFIG_FILE_NAMES = (
    "sources.yaml",
    "users.yaml",
    "venues.yaml",
    "keywords.yaml",
    "scoring.yaml",
    "report.yaml",
    "settings.yaml",
)


@dataclass(frozen=True)
class ConfigSnapshot:
    config_dir: Path
    loaded_at: str
    fingerprint: tuple[tuple[str, int | None, int | None], ...]
    config: AppConfig


class ReloadResult(NamedTuple):
    snapshot: ConfigSnapshot
    changed: bool
    error: str | None
    attempted_fingerprint: tuple[tuple[str, int | None, int | None], ...] | None


def config_fingerprint(config_dir: Path) -> tuple[tuple[str, int | None, int | None], ...]:
    entries: list[tuple[str, int | None, int | None]] = []
    for name in CONFIG_FILE_NAMES:
        path = config_dir / name
        try:
            stat = path.stat()
        except FileNotFoundError:
            entries.append((name, None, None))
            continue
        entries.append((name, stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


def load_config_snapshot(config_dir: Path) -> ConfigSnapshot:
    config = load_config(config_dir)
    return ConfigSnapshot(
        config_dir=config_dir,
        loaded_at=datetime.now(UTC).isoformat(),
        fingerprint=config_fingerprint(config_dir),
        config=config,
    )


def maybe_reload_config(config_dir: Path, snapshot: ConfigSnapshot) -> ReloadResult:
    fingerprint = config_fingerprint(config_dir)
    if fingerprint == snapshot.fingerprint:
        return ReloadResult(snapshot=snapshot, changed=False, error=None, attempted_fingerprint=None)
    try:
        return ReloadResult(
            snapshot=load_config_snapshot(config_dir),
            changed=True,
            error=None,
            attempted_fingerprint=fingerprint,
        )
    except ConfigError as exc:
        return ReloadResult(
            snapshot=snapshot,
            changed=False,
            error=str(exc),
            attempted_fingerprint=fingerprint,
        )
