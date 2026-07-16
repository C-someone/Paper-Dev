from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser

from paper_watcher.fetchers.base import FetchResult, SourceState
from paper_watcher.http_client import RateLimitedHttpClient
from paper_watcher.models import Paper, Source
from paper_watcher.models import Recommendation
from paper_watcher.parsers.normalizer import (
    extract_arxiv_id,
    extract_doi,
    normalize_title,
    paper_identity,
    parse_year,
)


class RSSFetcher:
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
        if not source.feed_url:
            return FetchResult(source_id=source.id, error="missing feed_url")

        headers = {"User-Agent": self.user_agent}
        if state and state.etag:
            headers["If-None-Match"] = state.etag
        if state and state.last_modified:
            headers["If-Modified-Since"] = state.last_modified

        try:
            response = self.http_client.get(
                source.feed_url,
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
                    from_cache=response.from_cache,
                )
            response.raise_for_status()
        except Exception as exc:
            return FetchResult(source_id=source.id, error=str(exc))

        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            return FetchResult(source_id=source.id, error=f"invalid feed: {parsed.bozo_exception}")

        now = datetime.now(UTC)
        papers = [self._entry_to_paper(source, entry, now) for entry in parsed.entries]
        papers = [paper for paper in papers if paper is not None]
        return FetchResult(
            source_id=source.id,
            papers=papers,
            fetched_count=len(parsed.entries),
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            from_cache=response.from_cache,
        )

    def _entry_to_paper(self, source: Source, entry: Any, now: datetime) -> Paper | None:
        title = str(getattr(entry, "title", "") or "").strip()
        if not title:
            return None

        paper_url = self._first_link(entry)
        summary = str(getattr(entry, "summary", "") or "").strip() or None
        published_at = self._entry_datetime(entry)
        authors = self._authors(entry)
        normalized_title = normalize_title(title)
        arxiv_id = extract_arxiv_id(paper_url, getattr(entry, "id", None), summary)
        doi = extract_doi(paper_url, summary, getattr(entry, "id", None))
        year = parse_year(published_at)
        paper_id = paper_identity(
            normalized_title,
            doi=doi,
            arxiv_id=arxiv_id,
            first_author=authors[0] if authors else None,
            year=year,
        )

        raw = dict(entry)
        return Paper(
            id=paper_id,
            title=title,
            normalized_title=normalized_title,
            authors=authors,
            abstract=summary,
            venue=source.name,
            venue_type=source.venue_type,
            ccf_level=source.ccf_level,
            area=source.area,
            source_id=source.id,
            source_url=source.feed_url,
            paper_url=paper_url,
            pdf_url=self._pdf_link(entry),
            doi=doi,
            arxiv_id=arxiv_id,
            dblp_key=None,
            openreview_id=None,
            year=year,
            published_at=published_at,
            first_seen_at=now,
            last_seen_at=now,
            score=0.0,
            tags=list(source.tags),
            summary=None,
            recommendation=Recommendation.IGNORE,
            raw=raw,
        )

    def _first_link(self, entry: Any) -> str | None:
        link = getattr(entry, "link", None)
        if link:
            return str(link)
        links = getattr(entry, "links", None) or []
        if links:
            href = links[0].get("href")
            return str(href) if href else None
        return None

    def _pdf_link(self, entry: Any) -> str | None:
        for link in getattr(entry, "links", None) or []:
            href = link.get("href")
            link_type = link.get("type")
            title = link.get("title")
            if href and (link_type == "application/pdf" or title == "pdf"):
                return str(href)
        return None

    def _authors(self, entry: Any) -> list[str]:
        authors = getattr(entry, "authors", None)
        if isinstance(authors, list):
            result = []
            for author in authors:
                name = author.get("name") if isinstance(author, dict) else getattr(author, "name", None)
                if name:
                    result.append(str(name).strip())
            return result
        author = getattr(entry, "author", None)
        if author:
            return [part.strip() for part in str(author).split(",") if part.strip()]
        return []

    def _entry_datetime(self, entry: Any) -> datetime | None:
        for key in ("published", "updated", "created"):
            value = getattr(entry, key, None)
            if not value:
                continue
            try:
                parsed = parsedate_to_datetime(str(value))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed.astimezone(UTC)
            except (TypeError, ValueError):
                continue
        return None
