from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from paper_watcher.fetchers.base import SourceState
from paper_watcher.fetchers.rss_fetcher import RSSFetcher
from paper_watcher.filters.scoring import score_paper
from paper_watcher.models import AppConfig, Paper, SourceType
from paper_watcher.network import build_http_client
from paper_watcher.reports.markdown_report import write_run_report
from paper_watcher.settings import resolve_project_path
from paper_watcher.storage.repository import Repository


@dataclass(frozen=True)
class ScanSummary:
    run_id: str
    scanned_sources: int
    fetched_count: int
    new_count: int
    updated_count: int
    error_count: int
    report_path: Path


def scan_once(config: AppConfig, repository: Repository, source_id: str | None = None) -> ScanSummary:
    started_at = datetime.now(UTC)
    run_id = f"scan_{uuid4().hex}"
    repository.create_scan_run(run_id, started_at, source_id)

    enabled_sources = [source for source in config.sources.sources if source.enabled]
    if source_id:
        enabled_sources = [source for source in enabled_sources if source.id == source_id]
        if not enabled_sources:
            raise ValueError(f"enabled source not found: {source_id}")

    fetcher = RSSFetcher(
        timeout_seconds=config.settings.request_timeout_seconds,
        user_agent=config.settings.user_agent,
        http_client=build_http_client(config),
        allow_cached_on_error=False,
    )
    scanned_sources = 0
    fetched_count = 0
    new_papers: list[Paper] = []
    updated_count = 0
    errors: dict[str, str] = {}

    for source in enabled_sources:
        if source.source_type not in {SourceType.RSS, SourceType.ARXIV}:
            continue
        scanned_sources += 1
        state_row = repository.get_source_state(source.id)
        state = SourceState(
            etag=state_row["etag"] if state_row else None,
            last_modified=state_row["last_modified"] if state_row else None,
        )
        result = fetcher.fetch(source, state)
        fetched_count += result.fetched_count
        if not result.ok:
            errors[source.id] = result.error or "unknown error"
            repository.mark_source_error(source.id, errors[source.id])
            continue

        repository.mark_source_success(source.id, etag=result.etag, last_modified=result.last_modified)
        for paper in result.papers:
            scored = score_paper(paper, source, config)
            inserted = repository.upsert_paper(scored)
            repository.record_paper_seen(scored, source_item_id=scored.arxiv_id or scored.paper_url or scored.id or "")
            if inserted:
                new_papers.append(scored)
            else:
                updated_count += 1

    finished_at = datetime.now(UTC)
    reports_dir = resolve_project_path(config, config.settings.reports_dir)
    report_path = write_run_report(
        report_dir=reports_dir,
        started_at=started_at,
        finished_at=finished_at,
        scanned_sources=scanned_sources,
        new_papers=new_papers,
        updated_count=updated_count,
        errors=errors,
        filename_pattern=str(config.report.daily_report.get("filename_pattern", "run_%Y-%m-%d_%H-%M-%S.md")),
    )
    status = "success" if not errors else "partial_failure"
    repository.finish_scan_run(
        run_id,
        finished_at,
        status=status,
        fetched_count=fetched_count,
        new_count=len(new_papers),
        updated_count=updated_count,
        error_count=len(errors),
        log=f"report={report_path}",
    )
    return ScanSummary(
        run_id=run_id,
        scanned_sources=scanned_sources,
        fetched_count=fetched_count,
        new_count=len(new_papers),
        updated_count=updated_count,
        error_count=len(errors),
        report_path=report_path,
    )
