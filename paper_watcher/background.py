from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sys
import time
from pathlib import Path
from typing import Callable
from uuid import uuid4

from paper_watcher.config_watcher import ConfigSnapshot, load_config_snapshot, maybe_reload_config
from paper_watcher.fetchers.base import SourceState
from paper_watcher.fetchers.dblp_fetcher import DBLPFetcher
from paper_watcher.fetchers.rss_fetcher import RSSFetcher
from paper_watcher.fetchers.website_watcher import WebsiteWatcherFetcher
from paper_watcher.models import AppConfig, Source, SourceType
from paper_watcher.network import build_http_client
from paper_watcher.settings import resolve_project_path
from paper_watcher.storage.file_storage import FileStateStore, WatchEvent
from paper_watcher.subscriptions import all_subscribed_source_ids


def run_background_once(
    config: AppConfig,
    *,
    source_id: str | None = None,
    include_disabled: bool = False,
    respect_schedule: bool = False,
) -> tuple[int, int, int]:
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    store.ensure()

    subscribed_source_ids = all_subscribed_source_ids(config)
    source_by_id = {source.id: source for source in config.sources.sources}
    source_state = store.load_source_state()
    global_known_paper_ids = store.known_paper_ids()

    http_client = build_http_client(config)
    fetcher = RSSFetcher(
        timeout_seconds=config.settings.request_timeout_seconds,
        user_agent=config.settings.user_agent,
        http_client=http_client,
        allow_cached_on_error=False,
    )
    dblp_fetcher = DBLPFetcher(
        timeout_seconds=config.settings.request_timeout_seconds,
        user_agent=config.settings.user_agent,
        http_client=http_client,
        allow_cached_on_error=False,
    )
    website_fetcher = WebsiteWatcherFetcher(
        timeout_seconds=config.settings.request_timeout_seconds,
        user_agent=config.settings.user_agent,
        http_client=http_client,
        allow_cached_on_error=False,
    )

    scanned = 0
    new_events: list[WatchEvent] = []
    errors = 0
    for current_source_id in sorted(subscribed_source_ids):
        if source_id and current_source_id != source_id:
            continue
        source = source_by_id.get(current_source_id)
        if not source or source.source_type not in {
            SourceType.RSS,
            SourceType.ARXIV,
            SourceType.DBLP,
            SourceType.WEBSITE_WATCH,
        }:
            continue
        if not source.enabled and not include_disabled:
            continue
        state = source_state.get(source.id, {})
        if respect_schedule and not source_id and not _source_is_due(source, state):
            continue
        scanned += 1
        source_known_paper_ids = set(state.get("known_paper_ids", []))
        first_successful_scan = not state.get("initialized_at")
        if source.source_type == SourceType.DBLP:
            fetcher_for_source = dblp_fetcher
        elif source.source_type == SourceType.WEBSITE_WATCH:
            fetcher_for_source = website_fetcher
        else:
            fetcher_for_source = fetcher
        result = fetcher_for_source.fetch(
            source,
            SourceState(
                etag=state.get("etag"),
                last_modified=state.get("last_modified"),
                content_hash=state.get("content_hash"),
            ),
        )
        if not result.ok:
            errors += 1
            source_state[source.id] = {
                **state,
                "last_scan_at": datetime.now(UTC).isoformat(),
                "next_scan_after": _next_scan_after(source),
                "last_error_at": datetime.now(UTC).isoformat(),
                "last_error": result.error,
            }
            continue

        fetched_paper_ids = {paper.id for paper in result.papers if paper.id}
        source_state[source.id] = {
            **state,
            "etag": result.etag or state.get("etag"),
            "last_modified": result.last_modified or state.get("last_modified"),
            "content_hash": result.content_hash or state.get("content_hash"),
            "last_success_at": datetime.now(UTC).isoformat(),
            "last_scan_at": datetime.now(UTC).isoformat(),
            "next_scan_after": _next_scan_after(source),
            "initialized_at": state.get("initialized_at") or datetime.now(UTC).isoformat(),
            "known_paper_ids": sorted(source_known_paper_ids.union(fetched_paper_ids)),
            "last_error": None,
            "last_error_at": None,
        }
        if first_successful_scan:
            continue
        for paper in result.papers:
            if not paper.id:
                continue
            if paper.id in global_known_paper_ids or paper.id in source_known_paper_ids:
                continue
            global_known_paper_ids.add(paper.id)
            source_known_paper_ids.add(paper.id)
            new_events.append(_paper_to_event(paper, source))

    store.append_events(new_events)
    store.save_source_state(source_state)
    return scanned, len(new_events), errors


def run_background_loop(
    config_dir: Path,
    *,
    interval_seconds: float = 300,
    watch_config: bool = False,
    source_id: str | None = None,
    include_disabled: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_iterations: int | None = None,
) -> None:
    snapshot = load_config_snapshot(config_dir)
    iteration = 0
    last_failed_fingerprint: tuple[tuple[str, int | None, int | None], ...] | None = None
    while max_iterations is None or iteration < max_iterations:
        if watch_config:
            reload_result = maybe_reload_config(config_dir, snapshot)
            if reload_result.error:
                if reload_result.attempted_fingerprint != last_failed_fingerprint:
                    _log_config_reload_error(snapshot, reload_result.error, reload_result.attempted_fingerprint)
                    print(f"Config reload failed; keeping previous config: {reload_result.error}", file=sys.stderr)
                    last_failed_fingerprint = reload_result.attempted_fingerprint
            elif reload_result.changed:
                snapshot = reload_result.snapshot
                last_failed_fingerprint = None
                print(f"Config reloaded: {snapshot.loaded_at}")

        scanned, new_events, errors = run_background_once(
            snapshot.config,
            source_id=source_id,
            include_disabled=include_disabled,
            respect_schedule=True,
        )
        print(
            f"Background pass completed: scanned={scanned} "
            f"new_events={new_events} errors={errors}"
        )
        iteration += 1
        if max_iterations is not None and iteration >= max_iterations:
            break
        sleep_fn(max(0, interval_seconds))


def _log_config_reload_error(
    snapshot: ConfigSnapshot,
    error: str,
    attempted_fingerprint: tuple[tuple[str, int | None, int | None], ...] | None,
) -> None:
    store = FileStateStore(resolve_project_path(snapshot.config, snapshot.config.settings.state_dir))
    store.append_config_reload_error(
        {
            "seen_at": datetime.now(UTC).isoformat(),
            "config_dir": str(snapshot.config_dir),
            "loaded_at": snapshot.loaded_at,
            "active_fingerprint": list(snapshot.fingerprint),
            "attempted_fingerprint": list(attempted_fingerprint or ()),
            "error": error,
        }
    )


def _source_is_due(source: Source, state: dict) -> bool:
    next_scan_after = _parse_datetime(state.get("next_scan_after"))
    if next_scan_after is None:
        return True
    return datetime.now(UTC) >= next_scan_after


def _next_scan_after(source: Source) -> str | None:
    interval_seconds = source.schedule.get("interval_seconds")
    if interval_seconds is None:
        return None
    try:
        seconds = max(0, float(interval_seconds))
    except (TypeError, ValueError):
        return None
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _parse_datetime(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _paper_to_event(paper, source: Source) -> WatchEvent:
    raw = {
        "authors": paper.authors,
        "abstract": paper.abstract,
        "published_at": paper.published_at.isoformat() if paper.published_at else None,
        "venue": paper.venue,
        "source_url": paper.source_url,
    }
    raw.update(paper.raw or {})
    return WatchEvent(
        event_id=f"evt_{uuid4().hex}",
        seen_at=datetime.now(UTC).isoformat(),
        source_id=source.id,
        source_type=source.source_type.value,
        paper_id=paper.id or "",
        title=paper.title,
        link=paper.paper_url or paper.pdf_url,
        matched_users=[],
        raw=raw,
    )
