from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from paper_watcher.agent_review.search_review import SearchReviewInput, SearchResultItem, ReviewResult
from paper_watcher.conference_discovery import VenueProfile, load_venue_profiles
from paper_watcher.environment import load_env_file
from paper_watcher.models import AppConfig


@dataclass(frozen=True)
class ConferenceSearchResult:
    search_input: SearchReviewInput
    queries: list[str]
    response_text: str


class ExaSearchClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.exa.ai/search",
        timeout_seconds: float = 30,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> ExaSearchClient:
        api_key = os.environ.get("EXA_API_KEY")
        if not api_key:
            raise ValueError("missing API key env var: EXA_API_KEY")
        base_url = _normalize_exa_search_url(os.environ.get("EXA_API_URL", "https://api.exa.ai/search"))
        return cls(api_key=api_key, base_url=base_url)

    def search(
        self,
        query: str,
        *,
        include_domains: list[str] | None = None,
        num_results: int = 10,
    ) -> list[SearchResultItem]:
        payload: dict[str, Any] = {
            "query": query,
            "numResults": max(1, num_results),
            "contents": {
                "highlights": True,
                "summary": True,
                "text": True,
            },
        }
        if include_domains:
            payload["includeDomains"] = include_domains
        response = httpx.post(
            self.base_url,
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise ValueError(f"Exa search failed with HTTP {response.status_code}: {response.text[:500]}")
        data = response.json()
        raw_results = data.get("results", [])
        if not isinstance(raw_results, list):
            raise ValueError("Exa response results must be a list")
        items: list[SearchResultItem] = []
        for raw_result in raw_results:
            if not isinstance(raw_result, dict):
                continue
            items.append(_normalize_result(raw_result, query))
        return items


def search_conference(
    config: AppConfig,
    *,
    venue_id: str,
    year: int,
    num_results: int = 10,
    output_format: str = "text",
) -> ConferenceSearchResult:
    load_env_file(config.config_dir.parent / ".env")
    profile = _get_profile(config.config_dir, venue_id)
    queries = _build_queries(profile, year)
    client = ExaSearchClient.from_env()
    results = _search_queries(client, queries, profile.official_domains, num_results=num_results)
    search_input = SearchReviewInput(
        venue_id=profile.venue_id,
        year=year,
        query=" | ".join(queries),
        official_domains=profile.official_domains,
        aliases=_profile_aliases(profile),
        results=results,
    )
    return ConferenceSearchResult(
        search_input=search_input,
        queries=queries,
        response_text=render_search_results(search_input, queries=queries, output_format=output_format),
    )


def search_and_review_conference(
    config: AppConfig,
    *,
    venue_id: str,
    year: int,
    reviewer: str = "auto",
    num_results: int = 10,
    search_output_format: str = "text",
    review_output_format: str = "text",
    dry_run: bool = False,
) -> tuple[ConferenceSearchResult, ReviewResult]:
    search_result = search_conference(
        config,
        venue_id=venue_id,
        year=year,
        num_results=num_results,
        output_format=search_output_format,
    )
    from paper_watcher.agent_review.search_review import review_search_input

    review_result = review_search_input(
        config,
        search_result.search_input,
        reviewer=reviewer,
        output_format=review_output_format,
        dry_run=dry_run,
    )
    return search_result, review_result


def render_search_results(search_input: SearchReviewInput, *, queries: list[str], output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(
            {
                "queries": queries,
                "search": search_input.to_json_payload(),
            },
            ensure_ascii=False,
            indent=2,
        )
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    if not search_input.results:
        return f"No search results found for {search_input.venue_id} {search_input.year}."
    lines = [f"Search results for {search_input.venue_id} {search_input.year}:", ""]
    lines.append("Queries:")
    lines.extend(f"- {query}" for query in queries)
    lines.append("")
    for index, item in enumerate(search_input.results, start=1):
        lines.append(f"{index}. {item.title}")
        lines.append(f"   {item.url}")
        if item.snippet:
            lines.append(f"   {item.snippet}")
        if item.published_at:
            lines.append(f"   published_at={item.published_at}")
    return "\n".join(lines)


def _search_queries(
    client: ExaSearchClient,
    queries: list[str],
    official_domains: list[str],
    *,
    num_results: int,
) -> list[SearchResultItem]:
    seen_urls: set[str] = set()
    results: list[SearchResultItem] = []
    for query in queries:
        query_results = client.search(
            query,
            include_domains=official_domains or None,
            num_results=num_results,
        )
        if not query_results and official_domains:
            query_results = client.search(query, include_domains=None, num_results=num_results)
        for result in query_results:
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            results.append(result)
    return results


def _normalize_result(raw: dict[str, Any], query: str) -> SearchResultItem:
    title = _string_or_empty(raw.get("title"))
    url = _string_or_empty(raw.get("url") or raw.get("link"))
    if not title or not url:
        raise ValueError("Exa result must include title and url")
    snippet = _pick_snippet(raw)
    published_at = _string_or_none(raw.get("publishedDate") or raw.get("published_at"))
    return SearchResultItem(
        title=title,
        url=url,
        snippet=snippet,
        source=f"exa:{query}",
        published_at=published_at,
    )


def _pick_snippet(raw: dict[str, Any]) -> str:
    summary = raw.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    highlights = raw.get("highlights")
    if isinstance(highlights, list):
        for item in highlights:
            if isinstance(item, str) and item.strip():
                return item.strip()
    text = raw.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()[:500]
    return ""


def _build_queries(profile: VenueProfile, year: int) -> list[str]:
    terms: list[str] = []
    for pattern in profile.url_patterns:
        terms.extend(_term_from_kind(pattern.kind))
    if not terms:
        terms = ["accepted papers", "program", "call for papers"]
    terms = _unique(terms)
    names = _profile_aliases(profile)
    queries: list[str] = []
    for name in names[:3]:
        for term in terms[:3]:
            queries.append(f"{name} {year} {term}")
    return _unique(queries)


def _term_from_kind(kind: str) -> list[str]:
    text = kind.lower()
    if "accepted" in text:
        return ["accepted papers"]
    if "technical" in text:
        return ["technical sessions"]
    if "program" in text:
        return ["program"]
    if "important" in text:
        return ["important dates"]
    if "proceed" in text:
        return ["proceedings"]
    if "cfp" in text or "call" in text:
        return ["call for papers"]
    return []


def _profile_aliases(profile: VenueProfile) -> list[str]:
    names = [profile.short_name, profile.full_name, *profile.aliases]
    return _unique([name for name in names if name.strip()])


def _get_profile(config_dir: Path, venue_id: str) -> VenueProfile:
    profiles = load_venue_profiles(config_dir)
    for profile in profiles:
        if profile.venue_id == venue_id:
            return profile
    raise ValueError(f"venue profile not found: {venue_id}")


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _string_or_empty(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _string_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_exa_search_url(value: str) -> str:
    stripped = value.rstrip("/")
    if stripped.endswith("/search"):
        return stripped
    return f"{stripped}/search"
