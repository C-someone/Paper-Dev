from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any

from paper_watcher.models import AppConfig, User
from paper_watcher.settings import resolve_project_path
from paper_watcher.storage.file_storage import FileStateStore, WatchEvent
from paper_watcher.subscriptions import notifiable_source_ids_for_user


@dataclass(frozen=True)
class PullResult:
    user_id: str
    events: list[WatchEvent]
    response_text: str


def pull_user_updates(
    config: AppConfig,
    user_id: str,
    *,
    update_cursor: bool = True,
    limit: int | None = None,
    source_id: str | None = None,
    exclude_source_ids: set[str] | None = None,
    since: str | None = None,
    output_format: str = "text",
) -> PullResult:
    user = _find_user(config, user_id)
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    all_source_ids, included_source_ids = _read_source_sets(
        config,
        user,
        source_id=source_id,
        exclude_source_ids=exclude_source_ids,
    )
    events = _filter_events_for_user(
        config,
        store,
        user,
        source_id=source_id,
        exclude_source_ids=exclude_source_ids,
        since=since,
    )
    events = events[: (limit or user.delivery.max_items)]
    response = render_user_updates(user, events, output_format=output_format)
    if update_cursor:
        _update_user_cursor_after_read(
            store,
            user.id,
            all_source_ids=all_source_ids,
            included_source_ids=included_source_ids,
            delivered_events=events,
        )
    return PullResult(user_id=user.id, events=events, response_text=response)


def render_user_updates(user: User, events: list[WatchEvent], *, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(
            {
                "user_id": user.id,
                "count": len(events),
                "events": [
                    {
                        "event_id": event.event_id,
                        "seen_at": event.seen_at,
                        "source_id": event.source_id,
                        "source_type": event.source_type,
                        "paper_id": event.paper_id,
                        "title": event.title,
                        "link": event.link,
                    }
                    for event in events
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    if not events:
        return f"No new papers for {user.id}."
    lines = [f"New papers for {user.id}:", ""]
    for index, event in enumerate(events, start=1):
        lines.append(f"{index}. {event.title}")
        if event.link:
            lines.append(f"   {event.link}")
    return "\n".join(lines)


def reset_user_cursor(config: AppConfig, user_id: str) -> None:
    _find_user(config, user_id)
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    cursors = store.load_user_cursors()
    cursors.pop(user_id, None)
    store.save_user_cursors(cursors)


def _filter_events_for_user(
    config: AppConfig,
    store: FileStateStore,
    user: User,
    *,
    source_id: str | None = None,
    exclude_source_ids: set[str] | None = None,
    since: str | None = None,
) -> list[WatchEvent]:
    cursors = store.load_user_cursors()
    cursor = cursors.get(user.id, {})
    allowed_source_ids = notifiable_source_ids_for_user(config, user)
    excluded_source_ids = {source for source in (exclude_source_ids or set()) if source}
    source_cursor = _source_cursor_mapping(cursor)
    events = []
    for event in store.load_events():
        if event.source_id not in allowed_source_ids:
            continue
        if source_id and event.source_id != source_id:
            continue
        if event.source_id in excluded_source_ids:
            continue
        last_pulled_at = _parse_datetime(since) if since else _last_pulled_at_for_source(cursor, source_cursor, event.source_id)
        seen_at = _parse_datetime(event.seen_at)
        if last_pulled_at and seen_at and seen_at <= last_pulled_at:
            continue
        events.append(event)
    events.sort(key=lambda item: item.seen_at)
    return events


def _read_source_sets(
    config: AppConfig,
    user: User,
    *,
    source_id: str | None = None,
    exclude_source_ids: set[str] | None = None,
) -> tuple[set[str], set[str]]:
    all_source_ids = notifiable_source_ids_for_user(config, user)
    included_source_ids = set(all_source_ids)
    if source_id:
        included_source_ids.intersection_update({source_id})
    included_source_ids.difference_update({source for source in (exclude_source_ids or set()) if source})
    return all_source_ids, included_source_ids


def _source_cursor_mapping(cursor: dict[str, Any]) -> dict[str, str] | None:
    value = cursor.get("last_pulled_at_by_source")
    if not isinstance(value, dict):
        return None
    return {str(source_id): str(last_seen) for source_id, last_seen in value.items() if isinstance(last_seen, str)}


def _last_pulled_at_for_source(
    cursor: dict[str, Any],
    source_cursor: dict[str, str] | None,
    source_id: str,
) -> datetime | None:
    if source_cursor is not None:
        return _parse_datetime(source_cursor.get(source_id))
    return _parse_datetime(cursor.get("last_pulled_at"))


def _update_user_cursor_after_read(
    store: FileStateStore,
    user_id: str,
    *,
    all_source_ids: set[str],
    included_source_ids: set[str],
    delivered_events: list[WatchEvent],
) -> None:
    cursors = store.load_user_cursors()
    cursor = cursors.setdefault(user_id, {})
    if not isinstance(cursor, dict):
        cursor = {}
        cursors[user_id] = cursor

    previous_global = cursor.get("last_pulled_at")
    source_cursor = _source_cursor_mapping(cursor)
    if source_cursor is None:
        source_cursor = {}
        if isinstance(previous_global, str):
            for current_source_id in all_source_ids:
                source_cursor[current_source_id] = previous_global

    if delivered_events:
        for event in delivered_events:
            current = source_cursor.get(event.source_id)
            if current is None or event.seen_at > current:
                source_cursor[event.source_id] = event.seen_at
    else:
        now = datetime.now(UTC).isoformat()
        for current_source_id in included_source_ids:
            source_cursor[current_source_id] = now

    cursor["last_pulled_at_by_source"] = source_cursor
    latest = _latest_cursor_value(source_cursor)
    if latest:
        cursor["last_pulled_at"] = latest
    store.save_user_cursors(cursors)


def _latest_cursor_value(source_cursor: dict[str, str]) -> str | None:
    values = [value for value in source_cursor.values() if value]
    if not values:
        return None
    return max(values)


def _find_user(config: AppConfig, user_id: str) -> User:
    for user in config.users.users:
        if user.id == user_id:
            return user
    raise ValueError(f"user not found: {user_id}")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)
