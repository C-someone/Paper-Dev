from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from paper_watcher.fetchers.base import FetchResult, SourceState
from paper_watcher.http_client import RateLimitedHttpClient
from paper_watcher.models import Paper, Recommendation, Source
from paper_watcher.parsers.normalizer import normalize_title


class WebsiteWatcherFetcher:
    def __init__(
        self,
        timeout_seconds: float = 20,
        user_agent: str = "PaperWatcher/0.1",
        http_client: RateLimitedHttpClient | None = None,
        allow_cached_on_error: bool = True,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.allow_cached_on_error = allow_cached_on_error
        self.http_client = http_client or RateLimitedHttpClient(
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
            cache_enabled=False,
        )

    def fetch(self, source: Source, state: SourceState | None = None) -> FetchResult:
        if not source.watch_url:
            return FetchResult(source_id=source.id, error="missing watch_url")
        if not source.css_selector:
            return FetchResult(source_id=source.id, error="missing css_selector")

        headers: dict[str, str] = {}
        if state and state.etag:
            headers["If-None-Match"] = state.etag
        if state and state.last_modified:
            headers["If-Modified-Since"] = state.last_modified

        try:
            response = self.http_client.get(
                source.watch_url,
                headers=headers,
                allow_cached_on_error=self.allow_cached_on_error,
            )
            if response.status_code == 304:
                return FetchResult(
                    source_id=source.id,
                    papers=[],
                    fetched_count=0,
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                    content_hash=state.content_hash if state else None,
                    from_cache=response.from_cache,
                )
            response.raise_for_status()
        except Exception as exc:
            return FetchResult(source_id=source.id, error=str(exc))

        try:
            selected_text = _select_text(response.content, source.css_selector)
        except ValueError as exc:
            return FetchResult(source_id=source.id, error=str(exc))

        content_hash = hashlib.sha256(selected_text.encode("utf-8")).hexdigest()
        now = datetime.now(UTC)
        title = f"{source.name} updated"
        paper = Paper(
            id=f"website:{source.id}:{content_hash}",
            title=title,
            normalized_title=normalize_title(title),
            authors=[],
            abstract=None,
            venue=source.name,
            venue_type=source.venue_type,
            ccf_level=source.ccf_level,
            area=source.area,
            source_id=source.id,
            source_url=source.watch_url,
            paper_url=source.watch_url,
            pdf_url=None,
            doi=None,
            arxiv_id=None,
            dblp_key=None,
            openreview_id=None,
            year=None,
            published_at=None,
            first_seen_at=now,
            last_seen_at=now,
            score=0.0,
            tags=list(source.tags),
            summary=None,
            recommendation=Recommendation.IGNORE,
            raw={
                "content_hash": content_hash,
                "excerpt": selected_text[:500],
                "css_selector": source.css_selector,
            },
        )
        return FetchResult(
            source_id=source.id,
            papers=[paper],
            fetched_count=1,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            content_hash=content_hash,
            from_cache=response.from_cache,
        )


def _select_text(content: bytes, css_selector: str) -> str:
    soup = BeautifulSoup(content, "html.parser")
    elements = soup.select(css_selector)
    if not elements:
        raise ValueError(f"selector did not match: {css_selector}")
    text = "\n".join(element.get_text(" ", strip=True) for element in elements)
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        raise ValueError(f"selector matched empty content: {css_selector}")
    return normalized
