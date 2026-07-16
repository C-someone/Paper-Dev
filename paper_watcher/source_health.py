from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from paper_watcher.models import AppConfig
from paper_watcher.settings import resolve_project_path
from paper_watcher.storage.file_storage import FileStateStore


@dataclass(frozen=True)
class SourceHealth:
    source_id: str
    source_type: str
    enabled: bool
    notification_policy: str
    last_scan_at: str | None
    next_scan_after: str | None
    due: bool
    last_success_at: str | None
    last_error_at: str | None
    last_error: str | None
    verification_status: str | None
    verification_checked_at: str | None


@dataclass(frozen=True)
class SourceHealthResult:
    rows: list[SourceHealth]
    response_text: str


def list_source_health(
    config: AppConfig,
    *,
    source_id: str | None = None,
    source_type: str | None = None,
    failed_only: bool = False,
    due_only: bool = False,
    output_format: str = "text",
) -> SourceHealthResult:
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    source_state = store.load_source_state()
    verification = store.load_source_verification()
    rows: list[SourceHealth] = []

    for source in config.sources.sources:
        if source_id and source.id != source_id:
            continue
        if source_type and source.source_type.value != source_type:
            continue
        state = source_state.get(source.id, {})
        verified = verification.get(source.id, {})
        row = SourceHealth(
            source_id=source.id,
            source_type=source.source_type.value,
            enabled=source.enabled,
            notification_policy=source.notification_policy.value,
            last_scan_at=_string_or_none(state.get("last_scan_at")),
            next_scan_after=_string_or_none(state.get("next_scan_after")),
            due=_is_due(state.get("next_scan_after")),
            last_success_at=_string_or_none(state.get("last_success_at")),
            last_error_at=_string_or_none(state.get("last_error_at")),
            last_error=_string_or_none(state.get("last_error")),
            verification_status=_string_or_none(verified.get("status")),
            verification_checked_at=_string_or_none(verified.get("checked_at")),
        )
        if failed_only and not row.last_error and row.verification_status not in _FAILED_VERIFICATION_STATUSES:
            continue
        if due_only and not row.due:
            continue
        rows.append(row)

    return SourceHealthResult(rows=rows, response_text=render_source_health(rows, output_format=output_format))


def render_source_health(rows: list[SourceHealth], *, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(
            {"count": len(rows), "sources": [asdict(row) for row in rows]},
            ensure_ascii=False,
            indent=2,
        )
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    if not rows:
        return "No sources found."
    lines = ["Source health:", ""]
    for row in rows:
        enabled = "enabled" if row.enabled else "disabled"
        status = _compact_status(row)
        lines.append(f"- {row.source_id} [{row.source_type}] {enabled} {status}")
        lines.append(f"  last_scan_at={row.last_scan_at or '-'} next_scan_after={row.next_scan_after or '-'} due={row.due}")
        if row.verification_status:
            lines.append(f"  verification={row.verification_status} checked_at={row.verification_checked_at or '-'}")
        if row.last_error:
            lines.append(f"  last_error={row.last_error}")
    return "\n".join(lines)


_FAILED_VERIFICATION_STATUSES = {
    "failed",
    "network_error",
    "http_429",
    "http_503",
    "parse_error",
    "missing_required_field",
    "unsupported_source_type",
}


def _compact_status(row: SourceHealth) -> str:
    if row.last_error:
        return "status=scan_error"
    if row.verification_status in _FAILED_VERIFICATION_STATUSES:
        return f"status=verify_{row.verification_status}"
    if row.last_success_at:
        return "status=ok"
    return "status=unscanned"


def _is_due(value: Any) -> bool:
    parsed = _parse_datetime(value)
    if parsed is None:
        return True
    return datetime.now(UTC) >= parsed


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
