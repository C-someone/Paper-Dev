from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json

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
    since: str | None = None,
    output_format: str = "text",
) -> PullResult:
    user = _find_user(config, user_id)
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    events = _filter_events_for_user(config, store, user, source_id=source_id, since=since)
    events = events[: (limit or user.delivery.max_items)]
    response = render_user_updates(user, events, output_format=output_format)
    if update_cursor:
        if events:
            store.update_user_cursor(user.id, events[-1].seen_at)
        else:
            store.update_user_cursor_now(user.id)
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
    since: str | None = None,
) -> list[WatchEvent]:
    cursors = store.load_user_cursors()
    cursor = cursors.get(user.id, {})
    last_pulled_at = _parse_datetime(since) if since else _parse_datetime(cursor.get("last_pulled_at"))
    allowed_source_ids = notifiable_source_ids_for_user(config, user)
    events = []
    for event in store.load_events():
        if event.source_id not in allowed_source_ids:
            continue
        if source_id and event.source_id != source_id:
            continue
        seen_at = _parse_datetime(event.seen_at)
        if last_pulled_at and seen_at and seen_at <= last_pulled_at:
            continue
        events.append(event)
    events.sort(key=lambda item: item.seen_at)
    return events


def _find_user(config: AppConfig, user_id: str) -> User:
    for user in config.users.users:
        if user.id == user_id:
            return user
    raise ValueError(f"user not found: {user_id}")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)
