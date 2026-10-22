from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import yaml

from paper_watcher.models import AppConfig
from paper_watcher.environment import load_env_file
from paper_watcher.settings import resolve_project_path
from paper_watcher.storage.file_storage import FileStateStore


ConferenceStatus = Literal["scheduled", "likely_scheduled", "not_found", "unclear"]
AcceptedInfoStatus = Literal["public", "not_public", "unclear"]
ReviewAction = Literal["monitor_accepted_page", "monitor_cfp_page", "needs_review", "ignore"]


@dataclass(frozen=True)
class SearchResultItem:
    title: str
    url: str
    snippet: str = ""
    source: str | None = None
    published_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SearchResultItem:
        if not isinstance(data, dict):
            raise ValueError("search result must be a mapping")
        title = data.get("title")
        url = data.get("url") or data.get("link")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("search result title is required")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("search result url/link is required")
        snippet = data.get("snippet") or data.get("description") or ""
        return cls(
            title=title.strip(),
            url=url.strip(),
            snippet=str(snippet).strip(),
            source=data.get("source") if isinstance(data.get("source"), str) else None,
            published_at=data.get("published_at") if isinstance(data.get("published_at"), str) else None,
        )


@dataclass(frozen=True)
class SearchReviewInput:
    venue_id: str
    year: int
    query: str | None
    official_domains: list[str]
    aliases: list[str]
    results: list[SearchResultItem]

    @classmethod
    def from_json_file(
        cls,
        path: Path,
        *,
        venue_id: str | None = None,
        year: int | None = None,
    ) -> SearchReviewInput:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "search" in data and isinstance(data["search"], dict):
            data = data["search"]
        if isinstance(data, list):
            if not venue_id or year is None:
                raise ValueError("venue_id and year are required when input JSON is a list")
            return cls(
                venue_id=venue_id,
                year=year,
                query=None,
                official_domains=[],
                aliases=[],
                results=[SearchResultItem.from_dict(item) for item in data],
            )
        if not isinstance(data, dict):
            raise ValueError("search review input must be an object or list")
        raw_results = data.get("results", [])
        if not isinstance(raw_results, list):
            raise ValueError("input results must be a list")
        resolved_venue_id = venue_id or data.get("venue_id")
        resolved_year = year if year is not None else data.get("year")
        if not isinstance(resolved_venue_id, str) or not resolved_venue_id.strip():
            raise ValueError("venue_id is required")
        if not isinstance(resolved_year, int):
            raise ValueError("year is required")
        return cls(
            venue_id=resolved_venue_id.strip(),
            year=resolved_year,
            query=data.get("query") if isinstance(data.get("query"), str) else None,
            official_domains=_string_list(data.get("official_domains", [])),
            aliases=_string_list(data.get("aliases", [])),
            results=[SearchResultItem.from_dict(item) for item in raw_results],
        )

    def limited(self, limit: int) -> SearchReviewInput:
        return SearchReviewInput(
            venue_id=self.venue_id,
            year=self.year,
            query=self.query,
            official_domains=self.official_domains,
            aliases=self.aliases,
            results=self.results[: max(1, limit)],
        )

    def to_json_payload(self) -> dict[str, Any]:
        return {
            "venue_id": self.venue_id,
            "year": self.year,
            "query": self.query,
            "official_domains": self.official_domains,
            "aliases": self.aliases,
            "results": [asdict(result) for result in self.results],
        }


@dataclass(frozen=True)
class ConferenceSearchReview:
    review_id: str
    reviewed_at: str
    reviewer: str
    venue_id: str
    year: int
    conference_status: ConferenceStatus
    accepted_info_status: AcceptedInfoStatus
    action: ReviewAction
    confidence: float
    reason: str
    evidence: list[str]
    official_url: str | None = None
    accepted_info_url: str | None = None
    dates_text: str | None = None
    risk_flags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConferenceSearchReview:
        return cls(
            review_id=str(data["review_id"]),
            reviewed_at=str(data["reviewed_at"]),
            reviewer=str(data["reviewer"]),
            venue_id=str(data["venue_id"]),
            year=int(data["year"]),
            conference_status=data["conference_status"],
            accepted_info_status=data["accepted_info_status"],
            action=data["action"],
            confidence=float(data["confidence"]),
            reason=str(data["reason"]),
            evidence=_string_list(data.get("evidence", [])),
            official_url=data.get("official_url") if isinstance(data.get("official_url"), str) else None,
            accepted_info_url=data.get("accepted_info_url") if isinstance(data.get("accepted_info_url"), str) else None,
            dates_text=data.get("dates_text") if isinstance(data.get("dates_text"), str) else None,
            risk_flags=_string_list(data.get("risk_flags", [])),
            raw=data.get("raw") if isinstance(data.get("raw"), dict) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentReviewConfig:
    enabled: bool = False
    default_reviewer: str = "pydantic_ai"
    model: str = "deepseek-v4-pro"
    model_env: str = "DEEPSEEK_API_MODEL"
    api_key_env: str = "DEEPSEEK_API_KEY"
    base_url_env: str = "DEEPSEEK_API_URL"
    monitor_min_confidence: float = 0.85
    needs_review_min_confidence: float = 0.55
    max_results_per_review: int = 10


@dataclass(frozen=True)
class ReviewResult:
    review: ConferenceSearchReview
    response_text: str


def load_agent_review_config(config_dir: Path) -> AgentReviewConfig:
    path = config_dir / "agent_review.yaml"
    if not path.exists():
        return AgentReviewConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"agent review config must be a mapping: {path}")
    raw = data.get("agent_review", {})
    if not isinstance(raw, dict):
        raise ValueError("agent_review must be a mapping")
    pydantic_ai = raw.get("pydantic_ai", {})
    if pydantic_ai is None:
        pydantic_ai = {}
    if not isinstance(pydantic_ai, dict):
        raise ValueError("agent_review.pydantic_ai must be a mapping")
    policy = raw.get("policy", {})
    if policy is None:
        policy = {}
    if not isinstance(policy, dict):
        raise ValueError("agent_review.policy must be a mapping")
    return AgentReviewConfig(
        enabled=bool(raw.get("enabled", False)),
        default_reviewer=str(raw.get("default_reviewer", "pydantic_ai")),
        model=str(pydantic_ai.get("model", "deepseek-v4-pro")),
        model_env=str(pydantic_ai.get("model_env", "DEEPSEEK_API_MODEL")),
        api_key_env=str(pydantic_ai.get("api_key_env", "DEEPSEEK_API_KEY")),
        base_url_env=str(pydantic_ai.get("base_url_env", "DEEPSEEK_API_URL")),
        monitor_min_confidence=float(policy.get("monitor_min_confidence", 0.85)),
        needs_review_min_confidence=float(policy.get("needs_review_min_confidence", 0.55)),
        max_results_per_review=int(policy.get("max_results_per_review", 10)),
    )


def review_search_results(
    config: AppConfig,
    *,
    input_path: Path,
    venue_id: str | None = None,
    year: int | None = None,
    reviewer: str = "auto",
    output_format: str = "text",
    dry_run: bool = False,
) -> ReviewResult:
    settings = load_agent_review_config(config.config_dir)
    load_env_file(config.config_dir.parent / ".env")
    review_input = SearchReviewInput.from_json_file(input_path, venue_id=venue_id, year=year)
    return review_search_input(
        config,
        review_input,
        reviewer=reviewer,
        output_format=output_format,
        dry_run=dry_run,
        settings=settings,
    )


def review_search_input(
    config: AppConfig,
    review_input: SearchReviewInput,
    *,
    reviewer: str = "auto",
    output_format: str = "text",
    dry_run: bool = False,
    settings: AgentReviewConfig | None = None,
) -> ReviewResult:
    settings = settings or load_agent_review_config(config.config_dir)
    load_env_file(config.config_dir.parent / ".env")
    review_input = _enrich_input_from_profiles(config.config_dir, review_input).limited(settings.max_results_per_review)
    selected_reviewer = _select_reviewer(reviewer, settings)
    if selected_reviewer == "pydantic_ai":
        review = PydanticAISearchReviewer(settings).review(review_input)
    elif selected_reviewer == "rule_based":
        review = RuleBasedSearchReviewer(settings).review(review_input)
    else:
        raise ValueError(f"unsupported reviewer: {selected_reviewer}")

    if not dry_run:
        store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
        store.append_conference_search_reviews([review.to_dict()])
    return ReviewResult(review=review, response_text=render_review(review, output_format=output_format))


def list_search_reviews(
    config: AppConfig,
    *,
    venue_id: str | None = None,
    year: int | None = None,
    output_format: str = "text",
) -> str:
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    reviews = [ConferenceSearchReview.from_dict(item) for item in store.load_conference_search_reviews()]
    if venue_id:
        reviews = [review for review in reviews if review.venue_id == venue_id]
    if year is not None:
        reviews = [review for review in reviews if review.year == year]
    reviews.sort(key=lambda item: item.reviewed_at, reverse=True)
    if output_format == "json":
        return json.dumps(
            {"count": len(reviews), "reviews": [review.to_dict() for review in reviews]},
            ensure_ascii=False,
            indent=2,
        )
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    if not reviews:
        return "No conference search reviews found."
    lines = ["Conference search reviews:", ""]
    for review in reviews:
        lines.append(
            f"- {review.review_id} {review.venue_id} {review.year} "
            f"action={review.action} accepted={review.accepted_info_status} confidence={review.confidence:.2f}"
        )
        lines.append(f"  reason={review.reason}")
        if review.accepted_info_url:
            lines.append(f"  accepted_info_url={review.accepted_info_url}")
    return "\n".join(lines)


def render_review(review: ConferenceSearchReview, *, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(review.to_dict(), ensure_ascii=False, indent=2)
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    lines = [
        f"Review: {review.review_id}",
        f"venue={review.venue_id} year={review.year} reviewer={review.reviewer}",
        f"conference_status={review.conference_status}",
        f"accepted_info_status={review.accepted_info_status}",
        f"action={review.action} confidence={review.confidence:.2f}",
        f"reason={review.reason}",
    ]
    if review.dates_text:
        lines.append(f"dates={review.dates_text}")
    if review.official_url:
        lines.append(f"official_url={review.official_url}")
    if review.accepted_info_url:
        lines.append(f"accepted_info_url={review.accepted_info_url}")
    if review.evidence:
        lines.append("evidence:")
        lines.extend(f"- {item}" for item in review.evidence)
    if review.risk_flags:
        lines.append("risk_flags:")
        lines.extend(f"- {item}" for item in review.risk_flags)
    return "\n".join(lines)


class RuleBasedSearchReviewer:
    def __init__(self, settings: AgentReviewConfig) -> None:
        self.settings = settings

    def review(self, review_input: SearchReviewInput) -> ConferenceSearchReview:
        aliases = [review_input.venue_id.replace("_", " ")] + review_input.aliases
        official_domain_hits = []
        accepted_hits = []
        cfp_hits = []
        date_hits = []
        evidence: list[str] = []
        risk_flags: list[str] = []
        year_text = str(review_input.year)

        for item in review_input.results:
            title = item.title.lower()
            snippet = item.snippet.lower()
            text = f"{title} {snippet}"
            url = item.url.lower()
            domain_match = any(domain.lower() in url for domain in review_input.official_domains)
            alias_match = any(alias.lower() in text or alias.lower() in url for alias in aliases if alias)
            year_match = _year_matches(text, url, review_input.year)
            page_year_match = _year_matches(title, url, review_input.year) and not _has_wrong_year(title, url, review_input.year)
            accepted_match = _accepted_info_is_public(title=title, snippet=snippet, url=url)
            cfp_match = any(marker in text or marker in url for marker in _CFP_MARKERS)
            date_match = _DATE_PATTERN.search(text) is not None
            if domain_match and page_year_match:
                official_domain_hits.append(item.url)
            if accepted_match and page_year_match and (domain_match or alias_match):
                accepted_hits.append(item.url)
            if cfp_match and page_year_match and (domain_match or alias_match):
                cfp_hits.append(item.url)
            if date_match and page_year_match and (domain_match or alias_match):
                date_hits.append(item.snippet or item.title)
            if domain_match and alias_match and page_year_match:
                evidence.append(f"official-domain result matches venue alias: {item.title}")
            elif alias_match and year_match:
                evidence.append(f"search result matches venue alias and year: {item.title}")

        if not review_input.results:
            return self._review(
                review_input,
                conference_status="not_found",
                accepted_info_status="unclear",
                action="needs_review",
                confidence=0.1,
                reason="No search results were provided.",
                evidence=[],
                risk_flags=["empty_search_results"],
            )

        if accepted_hits:
            confidence = 0.92 if official_domain_hits else 0.72
            return self._review(
                review_input,
                conference_status="scheduled",
                accepted_info_status="public",
                action="monitor_accepted_page" if confidence >= self.settings.monitor_min_confidence else "needs_review",
                confidence=confidence,
                reason="Search results indicate that accepted-paper or program information is public.",
                evidence=evidence[:5] or ["accepted-paper markers found in search results"],
                official_url=official_domain_hits[0] if official_domain_hits else None,
                accepted_info_url=accepted_hits[0],
                dates_text=date_hits[0] if date_hits else None,
            )

        if cfp_hits or date_hits or official_domain_hits:
            confidence = 0.78 if official_domain_hits else 0.62
            return self._review(
                review_input,
                conference_status="likely_scheduled",
                accepted_info_status="not_public",
                action="monitor_cfp_page" if confidence >= self.settings.needs_review_min_confidence else "needs_review",
                confidence=confidence,
                reason="Search results suggest the conference is scheduled, but accepted-paper information is not public.",
                evidence=evidence[:5] or ["CFP/date/official-domain markers found in search results"],
                official_url=official_domain_hits[0] if official_domain_hits else cfp_hits[0] if cfp_hits else None,
                dates_text=date_hits[0] if date_hits else None,
            )

        risk_flags.append("no_official_domain_or_accepted_info_match")
        return self._review(
            review_input,
            conference_status="unclear",
            accepted_info_status="unclear",
            action="needs_review",
            confidence=0.35,
            reason="Search results are too weak to determine conference status.",
            evidence=evidence[:5],
            risk_flags=risk_flags,
        )

    def _review(
        self,
        review_input: SearchReviewInput,
        *,
        conference_status: ConferenceStatus,
        accepted_info_status: AcceptedInfoStatus,
        action: ReviewAction,
        confidence: float,
        reason: str,
        evidence: list[str],
        official_url: str | None = None,
        accepted_info_url: str | None = None,
        dates_text: str | None = None,
        risk_flags: list[str] | None = None,
    ) -> ConferenceSearchReview:
        return ConferenceSearchReview(
            review_id=f"review_{uuid4().hex}",
            reviewed_at=_iso_now(),
            reviewer="rule_based",
            venue_id=review_input.venue_id,
            year=review_input.year,
            conference_status=conference_status,
            accepted_info_status=accepted_info_status,
            action=action,
            confidence=max(0.0, min(1.0, confidence)),
            reason=reason,
            evidence=evidence,
            official_url=official_url,
            accepted_info_url=accepted_info_url,
            dates_text=dates_text,
            risk_flags=risk_flags or [],
            raw={"query": review_input.query, "result_count": len(review_input.results)},
        )


class PydanticAISearchReviewer:
    def __init__(self, settings: AgentReviewConfig) -> None:
        self.settings = settings

    def review(self, review_input: SearchReviewInput) -> ConferenceSearchReview:
        try:
            from pydantic import BaseModel, Field
            from pydantic_ai import Agent
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider
        except ImportError as exc:
            raise ValueError("pydantic-ai is not installed. Install with: pip install '.[agent]'") from exc

        api_key = os.environ.get(self.settings.api_key_env)
        if not api_key:
            raise ValueError(f"missing API key env var: {self.settings.api_key_env}")
        base_url = _normalize_openai_base_url(os.environ.get(self.settings.base_url_env) or "https://api.deepseek.com")
        model_name = os.environ.get(self.settings.model_env) or self.settings.model

        class AgentOutput(BaseModel):
            conference_status: ConferenceStatus
            accepted_info_status: AcceptedInfoStatus
            action: ReviewAction
            confidence: float = Field(ge=0, le=1)
            reason: str
            evidence: list[str] = Field(default_factory=list)
            official_url: str | None = None
            accepted_info_url: str | None = None
            dates_text: str | None = None
            risk_flags: list[str] = Field(default_factory=list)

        model = OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(base_url=base_url, api_key=api_key),
        )
        agent = Agent(
            model,
            system_prompt=f"{_SYSTEM_PROMPT}\n\n{_JSON_OUTPUT_PROMPT}",
        )
        payload = _review_input_payload(review_input)
        try:
            result = agent.run_sync(json.dumps(payload, ensure_ascii=False, indent=2))
            output = AgentOutput.model_validate(_extract_json_object(str(result.output)))
        except Exception as exc:
            raise ValueError(f"pydantic-ai review failed: {exc}") from exc
        return ConferenceSearchReview(
            review_id=f"review_{uuid4().hex}",
            reviewed_at=_iso_now(),
            reviewer="pydantic_ai",
            venue_id=review_input.venue_id,
            year=review_input.year,
            conference_status=output.conference_status,
            accepted_info_status=output.accepted_info_status,
            action=output.action,
            confidence=float(output.confidence),
            reason=output.reason,
            evidence=output.evidence,
            official_url=output.official_url,
            accepted_info_url=output.accepted_info_url,
            dates_text=output.dates_text,
            risk_flags=output.risk_flags,
            raw={"query": review_input.query, "result_count": len(review_input.results)},
        )


def _select_reviewer(requested: str, settings: AgentReviewConfig) -> str:
    if requested != "auto":
        return requested
    if settings.enabled and settings.default_reviewer == "pydantic_ai" and _pydantic_ai_ready(settings):
        return "pydantic_ai"
    return "rule_based"


def _review_input_payload(review_input: SearchReviewInput) -> dict[str, Any]:
    return {
        "task": "Determine whether this conference is scheduled, when it is held if visible, and whether accepted-paper/program information is public.",
        "venue_id": review_input.venue_id,
        "year": review_input.year,
        "query": review_input.query,
        "official_domains": review_input.official_domains,
        "aliases": review_input.aliases,
        "results": [asdict(item) for item in review_input.results],
        "allowed_actions": ["monitor_accepted_page", "monitor_cfp_page", "needs_review", "ignore"],
    }


def _enrich_input_from_profiles(config_dir: Path, review_input: SearchReviewInput) -> SearchReviewInput:
    if review_input.official_domains and review_input.aliases:
        return review_input
    path = config_dir / "venue_profiles.yaml"
    if not path.exists():
        return review_input
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profiles = data.get("venue_profiles", []) if isinstance(data, dict) else []
    if not isinstance(profiles, list):
        return review_input
    for profile in profiles:
        if not isinstance(profile, dict) or profile.get("venue_id") != review_input.venue_id:
            continue
        aliases = review_input.aliases or _string_list(profile.get("aliases", []))
        short_name = profile.get("short_name")
        full_name = profile.get("full_name")
        for name in (short_name, full_name):
            if isinstance(name, str) and name and name not in aliases:
                aliases.append(name)
        return SearchReviewInput(
            venue_id=review_input.venue_id,
            year=review_input.year,
            query=review_input.query,
            official_domains=review_input.official_domains or _string_list(profile.get("official_domains", [])),
            aliases=aliases,
            results=review_input.results,
        )
    return review_input


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("expected a list of strings")
    return value


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_openai_base_url(value: str) -> str:
    stripped = value.rstrip("/")
    suffix = "/chat/completions"
    if stripped.endswith(suffix):
        return stripped[: -len(suffix)] or stripped
    return stripped


_ACCEPTED_MARKERS = {
    "accepted papers",
    "accepted-papers",
    "accepted paper",
    "program",
    "technical sessions",
    "papers accepted",
    "proceedings",
}

_ACCEPTED_NEGATIVE_PATTERNS = [
    re.compile(
        r"\b(?:does not|doesn't|do not|don't|no)\b.{0,120}"
        r"\b(?:accepted papers?|program|technical sessions?|proceedings)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:accepted papers?|program|technical sessions?|proceedings)\b.{0,120}"
        r"\b(?:not public|not available|not visible|not released|not posted|unavailable)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:does not|doesn't|do not|don't)\b.{0,120}\b(?:contain|include|provide|list)\b.{0,120}"
        r"\b(?:accepted papers?|program|technical sessions?|proceedings|details)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:accepted papers?|program|technical sessions?|proceedings)\b.{0,160}"
        r"\b(?:consult|check|need to check|would need|please consult|please search)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bnot\b.{0,80}\b(?:individual paper titles|2026 details|explicitly listed)\b", re.IGNORECASE),
    re.compile(r"\b(?:likely need|need to|must)\b.{0,80}\b(?:accepted papers?|program)\b", re.IGNORECASE),
    re.compile(r"\bafter the conference\b", re.IGNORECASE),
]

_CFP_MARKERS = {
    "call for papers",
    "cfp",
    "important dates",
    "submission deadline",
    "paper submission",
    "deadline",
}

_DATE_PATTERN = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+\d{1,2}\b",
    re.IGNORECASE,
)


def _accepted_info_is_public(*, title: str, snippet: str, url: str) -> bool:
    title_or_url = f"{title} {url}"
    if any(marker in title_or_url for marker in _ACCEPTED_MARKERS):
        return True
    if not any(marker in snippet for marker in _ACCEPTED_MARKERS):
        return False
    return not any(pattern.search(snippet) for pattern in _ACCEPTED_NEGATIVE_PATTERNS)


def _year_matches(text: str, url: str, year: int) -> bool:
    year_text = str(year)
    if year_text in text or year_text in url:
        return True
    short_year = year_text[-2:]
    combined = f"{text} {url}"
    if re.search(rf"['’]{re.escape(short_year)}\b", combined):
        return True
    return re.search(rf"(?:^|[^0-9]){re.escape(short_year)}(?:[^0-9]|$)", combined) is not None


def _has_wrong_year(title: str, url: str, year: int) -> bool:
    years = {int(match) for match in re.findall(r"\b20\d{2}\b", f"{title} {url}")}
    return any(item != year for item in years)


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise ValueError("model output did not contain a JSON object")
        data = json.loads(stripped[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model output JSON must be an object")
    return data

_SYSTEM_PROMPT = """
You review fuzzy web-search results for academic conference monitoring.

Decide only from the provided search-result titles, snippets, URLs, aliases, and official domains.
Do not invent dates or accepted-paper status.

Definitions:
- conference_status scheduled: official or high-confidence evidence says the conference/year is happening.
- likely_scheduled: CFP/date/official page exists but details are incomplete.
- not_found: no useful evidence.
- unclear: mixed or weak evidence.
- accepted_info_status public: accepted papers, program, technical sessions, or proceedings appear public.
- not_public: CFP/date information exists but accepted information is not visible.
- unclear: insufficient evidence.

Actions:
- monitor_accepted_page: accepted/program/proceedings info appears public and should become a monitoring candidate.
- monitor_cfp_page: conference appears scheduled, but accepted info is not public yet.
- needs_review: evidence is weak or risky.
- ignore: clearly irrelevant or wrong-year results.

Return concise evidence and risk flags. Prefer official domains over mirrors, blogs, or social posts.
"""

_JSON_OUTPUT_PROMPT = """
Return exactly one JSON object, without Markdown, commentary, or tool calls.
Use this schema:
{
  "conference_status": "scheduled | likely_scheduled | not_found | unclear",
  "accepted_info_status": "public | not_public | unclear",
  "action": "monitor_accepted_page | monitor_cfp_page | needs_review | ignore",
  "confidence": 0.0,
  "reason": "short reason",
  "evidence": ["short evidence item"],
  "official_url": "URL or null",
  "accepted_info_url": "URL or null",
  "dates_text": "visible date text or null",
  "risk_flags": ["short risk flag"]
}
"""


def _pydantic_ai_ready(settings: AgentReviewConfig) -> bool:
    if not os.environ.get(settings.api_key_env):
        return False
    try:
        import pydantic_ai  # noqa: F401
    except ImportError:
        return False
    return True
