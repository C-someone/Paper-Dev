from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

import yaml

from paper_watcher.config_loader import load_config
from paper_watcher.models import AppConfig, SourceType
from paper_watcher.subscriptions import user_subscription_source_ids


SubscriptionBucket = Literal["auto", "rss", "indexed_venues", "website_watch"]


@dataclass(frozen=True)
class UserAdminResult:
    response_text: str


def list_users_for_admin(config: AppConfig, *, output_format: str = "text") -> UserAdminResult:
    source_by_id = {source.id: source for source in config.sources.sources}
    rows = []
    for user in config.users.users:
        source_ids = sorted(user_subscription_source_ids(user))
        rows.append(
            {
                "id": user.id,
                "display_name": user.display_name,
                "source_count": len(source_ids),
                "sources": [
                    {
                        "source_id": source_id,
                        "source_type": source_by_id[source_id].source_type.value if source_id in source_by_id else "missing",
                    }
                    for source_id in source_ids
                ],
                "delivery": {
                    "format": user.delivery.format,
                    "max_items": user.delivery.max_items,
                },
            }
        )
    if output_format == "json":
        return UserAdminResult(json.dumps({"users": rows}, ensure_ascii=False, indent=2))
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    if not rows:
        return UserAdminResult("No users configured.")
    lines = ["Users:", ""]
    for row in rows:
        lines.append(f"- {row['id']} ({row['display_name']}) sources={row['source_count']}")
        for source in row["sources"]:
            lines.append(f"  {source['source_id']} [{source['source_type']}]")
    return UserAdminResult("\n".join(lines))


def subscribe_user_to_source(
    config: AppConfig,
    *,
    user_id: str,
    source_id: str,
    bucket: SubscriptionBucket = "auto",
) -> UserAdminResult:
    data = _read_users_data(config)
    users = _users_list(data)
    user = _find_user_mapping(users, user_id)
    resolved_bucket = _resolve_bucket(config, source_id, bucket)
    subscriptions = _subscriptions_mapping(user)
    target = subscriptions.setdefault(resolved_bucket, [])
    if not isinstance(target, list):
        raise ValueError(f"subscriptions.{resolved_bucket} must be a list")
    if not _has_source_subscription(target, source_id):
        target.append({"source_id": source_id})
        _write_users_data(config, data)
        load_config(config.config_dir)
        return UserAdminResult(f"Subscribed {user_id} to {source_id} in {resolved_bucket}.")
    return UserAdminResult(f"{user_id} is already subscribed to {source_id} in {resolved_bucket}.")


def unsubscribe_user_from_source(
    config: AppConfig,
    *,
    user_id: str,
    source_id: str,
    bucket: SubscriptionBucket = "auto",
) -> UserAdminResult:
    data = _read_users_data(config)
    users = _users_list(data)
    user = _find_user_mapping(users, user_id)
    buckets = [_resolve_bucket(config, source_id, bucket)] if bucket != "auto" else ["rss", "indexed_venues", "website_watch"]
    subscriptions = _subscriptions_mapping(user)
    removed_from: list[str] = []
    for current_bucket in buckets:
        target = subscriptions.setdefault(current_bucket, [])
        if not isinstance(target, list):
            raise ValueError(f"subscriptions.{current_bucket} must be a list")
        before = len(target)
        target[:] = [item for item in target if not (isinstance(item, dict) and item.get("source_id") == source_id)]
        if len(target) != before:
            removed_from.append(current_bucket)
    if removed_from:
        _write_users_data(config, data)
        load_config(config.config_dir)
        return UserAdminResult(f"Unsubscribed {user_id} from {source_id} in {', '.join(removed_from)}.")
    return UserAdminResult(f"{user_id} was not subscribed to {source_id}.")


def _resolve_bucket(config: AppConfig, source_id: str, bucket: SubscriptionBucket) -> str:
    source = next((source for source in config.sources.sources if source.id == source_id), None)
    if source is None:
        raise ValueError(f"source not found: {source_id}")
    if bucket != "auto":
        return bucket
    if source.source_type in {SourceType.RSS, SourceType.ARXIV}:
        return "rss"
    if source.source_type == SourceType.DBLP:
        return "indexed_venues"
    if source.source_type == SourceType.WEBSITE_WATCH:
        return "website_watch"
    return "indexed_venues"


def _read_users_data(config: AppConfig) -> dict[str, Any]:
    path = config.config_dir / "users.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("users.yaml must contain a mapping")
    return data


def _write_users_data(config: AppConfig, data: dict[str, Any]) -> None:
    path = config.config_dir / "users.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _users_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    users = data.setdefault("users", [])
    if not isinstance(users, list):
        raise ValueError("users.yaml users must be a list")
    if not all(isinstance(user, dict) for user in users):
        raise ValueError("users.yaml users entries must be mappings")
    return users


def _find_user_mapping(users: list[dict[str, Any]], user_id: str) -> dict[str, Any]:
    for user in users:
        if user.get("id") == user_id:
            return user
    raise ValueError(f"user not found: {user_id}")


def _subscriptions_mapping(user: dict[str, Any]) -> dict[str, Any]:
    subscriptions = user.setdefault("subscriptions", {})
    if not isinstance(subscriptions, dict):
        raise ValueError("user subscriptions must be a mapping")
    subscriptions.setdefault("rss", [])
    subscriptions.setdefault("indexed_venues", [])
    subscriptions.setdefault("website_watch", [])
    return subscriptions


def _has_source_subscription(items: list[Any], source_id: str) -> bool:
    return any(isinstance(item, dict) and item.get("source_id") == source_id for item in items)
