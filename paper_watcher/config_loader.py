from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from paper_watcher.models import (
    AppConfig,
    KeywordsConfig,
    ModelError,
    ReportConfig,
    ScoringConfig,
    SettingsConfig,
    SourcesConfig,
    UsersConfig,
    VenuesConfig,
)


class ConfigError(RuntimeError):
    """Raised when configuration files are missing or invalid."""


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"missing config file: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config file must contain a YAML mapping: {path}")
    return data


def parse_config_file(path: Path, model):
    try:
        return model.from_dict(load_yaml(path))
    except ModelError as exc:
        raise ConfigError(f"invalid config {path}:\n{exc}") from exc


def load_config(config_dir: Path | str = Path("config")) -> AppConfig:
    directory = Path(config_dir)
    if not directory.exists():
        raise ConfigError(f"config directory does not exist: {directory}")
    if not directory.is_dir():
        raise ConfigError(f"config path is not a directory: {directory}")

    sources = parse_config_file(directory / "sources.yaml", SourcesConfig)
    users = parse_config_file(directory / "users.yaml", UsersConfig)
    validate_user_source_references(users, sources)

    return AppConfig(
        sources=sources,
        venues=parse_config_file(directory / "venues.yaml", VenuesConfig),
        users=users,
        keywords=parse_config_file(directory / "keywords.yaml", KeywordsConfig),
        scoring=parse_config_file(directory / "scoring.yaml", ScoringConfig),
        report=parse_config_file(directory / "report.yaml", ReportConfig),
        settings=parse_config_file(directory / "settings.yaml", SettingsConfig),
        config_dir=directory,
    )


def validate_user_source_references(users: UsersConfig, sources: SourcesConfig) -> None:
    source_ids = {source.id for source in sources.sources}
    missing: list[str] = []
    for user in users.users:
        for subscription in user.subscriptions.rss:
            if subscription.source_id not in source_ids:
                missing.append(f"{user.id}:rss:{subscription.source_id}")
        for subscription in user.subscriptions.indexed_venues:
            source_id = subscription.get("source_id") if isinstance(subscription, dict) else None
            if source_id not in source_ids:
                missing.append(f"{user.id}:indexed_venues:{source_id}")
        for subscription in user.subscriptions.website_watch:
            source_id = subscription.get("source_id") if isinstance(subscription, dict) else None
            if source_id not in source_ids:
                missing.append(f"{user.id}:website_watch:{source_id}")
    if missing:
        raise ConfigError("users reference unknown sources: " + ", ".join(missing))
