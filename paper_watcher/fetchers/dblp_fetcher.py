from __future__ import annotations

from datetime import UTC, datetime
import xml.etree.ElementTree as ET

from paper_watcher.fetchers.base import FetchResult, SourceState
from paper_watcher.http_client import RateLimitedHttpClient
from paper_watcher.models import Paper, Recommendation, Source
from paper_watcher.parsers.normalizer import extract_doi, normalize_title, paper_identity


class DBLPFetcher:
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
        if not source.venue_key:
            return FetchResult(source_id=source.id, error="missing venue_key")
        url = source.url or f"https://dblp.org/db/{source.venue_key}/index.xml"
        headers = {"User-Agent": self.user_agent}
        if state and state.etag:
            headers["If-None-Match"] = state.etag
        if state and state.last_modified:
            headers["If-Modified-Since"] = state.last_modified

        try:
            response = self.http_client.get(
                url,
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

        try:
            papers = self._parse_xml(source, response.content, url)
        except ET.ParseError as exc:
            return FetchResult(source_id=source.id, error=f"invalid DBLP XML: {exc}")

        return FetchResult(
            source_id=source.id,
            papers=papers,
            fetched_count=len(papers),
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            from_cache=response.from_cache,
        )

    def _parse_xml(self, source: Source, content: bytes, source_url: str) -> list[Paper]:
        root = ET.fromstring(content)
        now = datetime.now(UTC)
        papers: list[Paper] = []
        for element in root.iter():
            tag = _strip_namespace(element.tag)
            if tag not in {"article", "inproceedings", "proceedings", "book", "incollection"}:
                continue
            title = _child_text(element, "title")
            if not title:
                continue
            authors = [child.text.strip() for child in element if _strip_namespace(child.tag) == "author" and child.text]
            year = _safe_int(_child_text(element, "year"))
            paper_url = _child_text(element, "ee") or _child_text(element, "url")
            doi = extract_doi(paper_url)
            dblp_key = element.attrib.get("key")
            normalized_title = normalize_title(title)
            paper_id = paper_identity(
                normalized_title,
                doi=doi,
                dblp_key=dblp_key,
                first_author=authors[0] if authors else None,
                year=year,
            )
            papers.append(
                Paper(
                    id=paper_id,
                    title=title,
                    normalized_title=normalized_title,
                    authors=authors,
                    abstract=None,
                    venue=source.name,
                    venue_type=source.venue_type,
                    ccf_level=source.ccf_level,
                    area=source.area,
                    source_id=source.id,
                    source_url=source_url,
                    paper_url=paper_url,
                    pdf_url=None,
                    doi=doi,
                    arxiv_id=None,
                    dblp_key=dblp_key,
                    openreview_id=None,
                    year=year,
                    published_at=datetime(year, 1, 1, tzinfo=UTC) if year else None,
                    first_seen_at=now,
                    last_seen_at=now,
                    score=0.0,
                    tags=list(source.tags),
                    summary=None,
                    recommendation=Recommendation.IGNORE,
                    raw={
                        "dblp_key": dblp_key,
                        "venue_key": source.venue_key,
                    },
                )
            )
        return papers


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, child_name: str) -> str | None:
    for child in element:
        if _strip_namespace(child.tag) == child_name and child.text:
            return child.text.strip()
    return None


def _safe_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None
