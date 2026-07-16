from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from time import monotonic

from paper_watcher.fetchers.base import SourceState
from paper_watcher.fetchers.dblp_fetcher import DBLPFetcher
from paper_watcher.fetchers.rss_fetcher import RSSFetcher
from paper_watcher.models import AppConfig, Source, SourceType
from paper_watcher.network import build_http_client
from paper_watcher.settings import resolve_project_path
from paper_watcher.storage.file_storage import FileStateStore


@dataclass(frozen=True)
class SourceVerificationResult:
    source_id: str
    source_type: str
    enabled: bool
    status: str
    item_count: int = 0
    elapsed_ms: int = 0
    error: str | None = None
    checked_at: str = ""


def verify_sources(
    config: AppConfig,
    *,
    source_id: str | None = None,
    source_type: str | None = None,
    include_disabled: bool = False,
) -> list[SourceVerificationResult]:
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    source_state = store.load_source_state()
    verification_state = store.load_source_verification()
    http_client = build_http_client(config)
    rss_fetcher = RSSFetcher(
        timeout_seconds=config.settings.request_timeout_seconds,
        user_agent=config.settings.user_agent,
        http_client=http_client,
    )
    dblp_fetcher = DBLPFetcher(
        timeout_seconds=config.settings.request_timeout_seconds,
        user_agent=config.settings.user_agent,
        http_client=http_client,
    )

    results: list[SourceVerificationResult] = []
    for source in config.sources.sources:
        if source_id and source.id != source_id:
            continue
        if source_type and source.source_type.value != source_type:
            continue
        if not source.enabled and not include_disabled:
            continue
        state = source_state.get(source.id, {})
        if source.source_type in {SourceType.RSS, SourceType.ARXIV}:
            result = _verify_fetcher(source, rss_fetcher, state)
        elif source.source_type == SourceType.DBLP:
            result = _verify_fetcher(source, dblp_fetcher, state)
        else:
            result = SourceVerificationResult(
                source_id=source.id,
                source_type=source.source_type.value,
                enabled=source.enabled,
                status="unsupported_source_type",
                error=f"verify-sources does not support {source.source_type.value} yet",
                checked_at=datetime.now(UTC).isoformat(),
            )
        results.append(result)
        verification_state[source.id] = asdict(result)

    store.save_source_verification(verification_state)
    return results


def _verify_fetcher(source: Source, fetcher, state: dict) -> SourceVerificationResult:
    started = monotonic()
    checked_at = datetime.now(UTC).isoformat()
    result = fetcher.fetch(
        source,
        SourceState(etag=state.get("etag"), last_modified=state.get("last_modified")),
    )
    elapsed_ms = int((monotonic() - started) * 1000)
    if result.ok:
        return SourceVerificationResult(
            source_id=source.id,
            source_type=source.source_type.value,
            enabled=source.enabled,
            status="cached_ok" if result.from_cache else "ok",
            item_count=result.fetched_count,
            elapsed_ms=elapsed_ms,
            checked_at=checked_at,
        )
    status = classify_error(result.error or "")
    return SourceVerificationResult(
        source_id=source.id,
        source_type=source.source_type.value,
        enabled=source.enabled,
        status=status,
        item_count=0,
        elapsed_ms=elapsed_ms,
        error=result.error,
        checked_at=checked_at,
    )


def classify_error(error: str) -> str:
    text = error.lower()
    if "429" in text:
        return "http_429"
    if "503" in text:
        return "http_503"
    if "invalid feed" in text or "invalid dblp xml" in text or "parse" in text:
        return "parse_error"
    if "missing" in text and ("feed_url" in text or "venue_key" in text):
        return "missing_required_field"
    if any(marker in text for marker in ("timeout", "connection", "network", "reset by peer")):
        return "network_error"
    return "failed"
