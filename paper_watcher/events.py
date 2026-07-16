from __future__ import annotations

import json
from dataclasses import dataclass

from paper_watcher.models import AppConfig, NotificationPolicy
from paper_watcher.settings import resolve_project_path
from paper_watcher.storage.file_storage import FileStateStore, WatchEvent


@dataclass(frozen=True)
class EventListResult:
    events: list[WatchEvent]
    response_text: str


def list_global_events(
    config: AppConfig,
    *,
    limit: int = 10,
    source_id: str | None = None,
    record_only: bool = False,
    notifiable: bool = False,
    output_format: str = "text",
) -> EventListResult:
    if record_only and notifiable:
        raise ValueError("--record-only and --notifiable cannot be used together")
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    source_by_id = {source.id: source for source in config.sources.sources}
    events = []
    for event in store.load_events():
        if source_id and event.source_id != source_id:
            continue
        source = source_by_id.get(event.source_id)
        if record_only and (not source or source.notification_policy != NotificationPolicy.RECORD_ONLY):
            continue
        if notifiable and (not source or source.notification_policy != NotificationPolicy.NOTIFY):
            continue
        events.append(event)
    events.sort(key=lambda item: item.seen_at, reverse=True)
    if limit > 0:
        events = events[:limit]
    return EventListResult(events=events, response_text=render_events(events, output_format=output_format))


def render_events(events: list[WatchEvent], *, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(
            {
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
        return "No events found."
    lines = ["Events:", ""]
    for index, event in enumerate(events, start=1):
        lines.append(f"{index}. [{event.source_id}] {event.title}")
        lines.append(f"   seen_at={event.seen_at}")
        if event.link:
            lines.append(f"   {event.link}")
    return "\n".join(lines)
