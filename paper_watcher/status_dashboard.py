from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from paper_watcher.models import AppConfig
from paper_watcher.settings import resolve_project_path
from paper_watcher.storage.file_storage import FileStateStore


@dataclass(frozen=True)
class StatusDashboardResult:
    data: dict[str, Any]
    response_text: str


def build_status_dashboard(config: AppConfig, *, output_format: str = "text") -> StatusDashboardResult:
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    events = store.load_events()
    source_state = store.load_source_state()
    candidates = store.load_source_candidates()
    reviews = store.load_conference_search_reviews()
    tasks = store.load_scheduled_tasks()

    enabled_sources = [source for source in config.sources.sources if source.enabled]
    failed_sources = [
        source_id
        for source_id, state in source_state.items()
        if isinstance(state, dict) and state.get("last_error")
    ]
    last_scan_at = _latest(
        state.get("last_scan_at")
        for state in source_state.values()
        if isinstance(state, dict)
    )
    last_success_at = _latest(
        state.get("last_success_at")
        for state in source_state.values()
        if isinstance(state, dict)
    )
    pending_candidates = [candidate for candidate in candidates if candidate.get("status") == "pending"]
    approved_candidates = [candidate for candidate in candidates if candidate.get("status") == "approved"]
    rejected_candidates = [candidate for candidate in candidates if candidate.get("status") == "rejected"]

    data = {
        "sources": {
            "total": len(config.sources.sources),
            "enabled": len(enabled_sources),
            "failed": len(failed_sources),
            "failed_source_ids": sorted(failed_sources),
        },
        "users": {
            "total": len(config.users.users),
            "ids": [user.id for user in config.users.users],
        },
        "events": {
            "total": len(events),
            "last_seen_at": _latest(event.seen_at for event in events),
        },
        "candidates": {
            "total": len(candidates),
            "pending": len(pending_candidates),
            "approved": len(approved_candidates),
            "rejected": len(rejected_candidates),
        },
        "conference_reviews": {
            "total": len(reviews),
            "last_reviewed_at": _latest(review.get("reviewed_at") for review in reviews if isinstance(review, dict)),
        },
        "background": {
            "last_scan_at": last_scan_at,
            "last_success_at": last_success_at,
        },
        "scheduled_tasks": tasks,
    }
    return StatusDashboardResult(data=data, response_text=render_status_dashboard(data, output_format=output_format))


def render_status_dashboard(data: dict[str, Any], *, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(data, ensure_ascii=False, indent=2)
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    lines = [
        "PaperWatcher status:",
        "",
        f"Sources: {data['sources']['enabled']} enabled / {data['sources']['total']} total",
        f"Failed sources: {data['sources']['failed']}",
        f"Users: {data['users']['total']} ({', '.join(data['users']['ids'])})",
        f"Events: {data['events']['total']}",
        f"Last event: {data['events']['last_seen_at'] or 'none'}",
        (
            "Candidates: "
            f"{data['candidates']['pending']} pending / "
            f"{data['candidates']['approved']} approved / "
            f"{data['candidates']['rejected']} rejected"
        ),
        f"Conference reviews: {data['conference_reviews']['total']}",
        f"Last conference review: {data['conference_reviews']['last_reviewed_at'] or 'none'}",
        f"Last background scan: {data['background']['last_scan_at'] or 'none'}",
    ]
    if data["scheduled_tasks"]:
        lines.append("")
        lines.append("Scheduled tasks:")
        for task_id, task in sorted(data["scheduled_tasks"].items()):
            if not isinstance(task, dict):
                continue
            lines.append(
                f"- {task_id}: last_run={task.get('last_run_at') or 'none'} "
                f"last_success={task.get('last_success_at') or 'none'} "
                f"last_error={task.get('last_error') or 'none'}"
            )
    return "\n".join(lines)


def _latest(values) -> str | None:
    parsed: list[tuple[datetime, str]] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        try:
            parsed.append((datetime.fromisoformat(value), value))
        except ValueError:
            continue
    if not parsed:
        return None
    parsed.sort(key=lambda item: item[0], reverse=True)
    return parsed[0][1]
