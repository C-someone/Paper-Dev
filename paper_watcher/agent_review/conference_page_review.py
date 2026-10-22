from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from bs4 import BeautifulSoup

from paper_watcher.agent_review.search_review import AgentReviewConfig, _normalize_openai_base_url, _pydantic_ai_ready, load_agent_review_config
from paper_watcher.environment import load_env_file
from paper_watcher.fetchers.conference_page_handler import DEFAULT_LAYOUTS, NAVIGATION_KEYWORDS, extract_conference_page_papers
from paper_watcher.models import Paper, Source


ConferencePageReviewMode = Literal["matched_layout", "unknown_layout"]
ConferencePageDecision = Literal["accept", "reject", "suggest_new_layout", "snapshot_only"]


@dataclass(frozen=True)
class ConferencePageReviewInput:
    mode: ConferencePageReviewMode
    source_id: str
    source_name: str
    watch_url: str
    snapshot_text: str
    page_summary: dict[str, Any]
    matched_layout: str | None = None
    candidate_items: list[dict[str, Any]] = field(default_factory=list)
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "task": "Review a conference website page extraction.",
            "mode": self.mode,
            "source": {
                "source_id": self.source_id,
                "source_name": self.source_name,
                "watch_url": self.watch_url,
                "matched_layout": self.matched_layout,
                "source_metadata": self.source_metadata,
            },
            "page_summary": self.page_summary,
            "snapshot_text": self.snapshot_text[:2000],
            "candidate_items": self.candidate_items,
            "allowed_decisions": ["accept", "reject", "suggest_new_layout", "snapshot_only"],
            "suggested_metadata_fields": [
                "conference_page_mode",
                "conference_content_selector",
                "paper_selector",
                "paper_title_selector",
                "paper_link_selector",
                "paper_author_selector",
                "conference_author_selector",
            ],
        }


@dataclass(frozen=True)
class ConferencePageReviewResult:
    review_id: str
    reviewed_at: str
    reviewer: str
    mode: ConferencePageReviewMode
    decision: ConferencePageDecision
    confidence: float
    reason: str
    evidence: list[str]
    suggested_layout_name: str | None = None
    conference_page_mode: str | None = None
    conference_content_selector: str | None = None
    paper_selector: str | None = None
    paper_title_selector: str | None = None
    paper_link_selector: str | None = None
    paper_author_selector: str | None = None
    conference_author_selector: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def suggested_metadata(self) -> dict[str, str]:
        metadata: dict[str, str] = {}
        for key in (
            "conference_page_mode",
            "conference_content_selector",
            "paper_selector",
            "paper_title_selector",
            "paper_link_selector",
            "paper_author_selector",
            "conference_author_selector",
        ):
            value = getattr(self, key)
            if isinstance(value, str) and value.strip():
                metadata[key] = value.strip()
        if self.suggested_layout_name:
            layout_metadata = _layout_metadata(self.suggested_layout_name)
            metadata = {**layout_metadata, **metadata}
        return metadata

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConferencePageProcessingResult:
    papers: list[Paper]
    review: ConferencePageReviewResult | None
    matched_layout: str | None
    retry_used: bool
    retry_layout: str | None
    snapshot_only: bool
    diagnostics: dict[str, Any]


def process_conference_page(
    source: Source,
    content: bytes,
    *,
    now: datetime,
    content_hash: str,
    snapshot_text: str,
    review_config_dir: Path,
    reviewer: str = "auto",
) -> ConferencePageProcessingResult:
    page_summary = _summarize_page(content, snapshot_text)
    source_metadata = source.metadata or {}
    initial_papers = extract_conference_page_papers(
        source=source,
        content=content,
        now=now,
        content_hash=content_hash,
    )
    matched_layout = _matched_layout_name(initial_papers)
    review_input = ConferencePageReviewInput(
        mode="matched_layout" if initial_papers else "unknown_layout",
        source_id=source.id,
        source_name=source.name,
        watch_url=source.watch_url or "",
        snapshot_text=snapshot_text,
        page_summary=page_summary,
        matched_layout=matched_layout,
        candidate_items=_paper_candidates_payload(initial_papers),
        source_metadata=source_metadata,
    )

    diagnostics: dict[str, Any] = {
        "page_summary": page_summary,
        "initial_candidate_count": len(initial_papers),
        "matched_layout": matched_layout,
        "analysis_mode": review_input.mode,
    }

    try:
        review = review_conference_page(
            review_config_dir,
            review_input,
            reviewer=reviewer,
        )
        diagnostics["review"] = review.to_dict()

        if initial_papers and review.decision == "accept":
            return ConferencePageProcessingResult(
                papers=initial_papers,
                review=review,
                matched_layout=matched_layout,
                retry_used=False,
                retry_layout=None,
                snapshot_only=False,
                diagnostics=diagnostics,
            )

        suggested_metadata = review.suggested_metadata()
        if suggested_metadata:
            merged_metadata = {**source_metadata, **suggested_metadata}
            if merged_metadata != source_metadata:
                retry_source = replace(source, metadata=merged_metadata)
                retry_papers = extract_conference_page_papers(
                    source=retry_source,
                    content=content,
                    now=now,
                    content_hash=content_hash,
                )
                if retry_papers:
                    retry_layout = _matched_layout_name(retry_papers)
                    diagnostics["retry_used"] = True
                    diagnostics["retry_layout"] = retry_layout
                    diagnostics["retry_metadata"] = suggested_metadata
                    diagnostics["final_candidate_count"] = len(retry_papers)
                    return ConferencePageProcessingResult(
                        papers=retry_papers,
                        review=review,
                        matched_layout=retry_layout,
                        retry_used=True,
                        retry_layout=retry_layout,
                        snapshot_only=False,
                        diagnostics=diagnostics,
                    )
    except Exception as exc:
        diagnostics["review_error"] = str(exc)

    diagnostics["fallback_to_snapshot_only"] = True
    return ConferencePageProcessingResult(
        papers=[],
        review=review if "review" in locals() else None,
        matched_layout=matched_layout,
        retry_used=False,
        retry_layout=None,
        snapshot_only=True,
        diagnostics=diagnostics,
    )


def review_conference_page(
    config_dir: Path,
    review_input: ConferencePageReviewInput,
    *,
    reviewer: str = "auto",
) -> ConferencePageReviewResult:
    settings = load_agent_review_config(config_dir)
    load_env_file(config_dir.parent / ".env")
    selected_reviewer = _select_reviewer(reviewer, settings)
    if selected_reviewer == "pydantic_ai":
        return PydanticAIConferencePageReviewer(settings).review(review_input)
    if selected_reviewer == "rule_based":
        return RuleBasedConferencePageReviewer(settings).review(review_input)
    raise ValueError(f"unsupported reviewer: {selected_reviewer}")


class RuleBasedConferencePageReviewer:
    def __init__(self, settings: AgentReviewConfig) -> None:
        self.settings = settings

    def review(self, review_input: ConferencePageReviewInput) -> ConferencePageReviewResult:
        if review_input.mode == "matched_layout":
            evidence = _candidate_evidence(review_input.candidate_items)
            if _candidate_items_look_like_navigation(review_input.candidate_items):
                suggestion = _suggest_layout_from_summary(review_input.page_summary)
                if suggestion is not None:
                    layout_name, reason, layout_evidence = suggestion
                    return ConferencePageReviewResult(
                        review_id=f"page_review_{_uuid_hex()}",
                        reviewed_at=_iso_now(),
                        reviewer="rule_based",
                        mode=review_input.mode,
                        decision="suggest_new_layout",
                        confidence=0.55,
                        reason="The matched layout appears to be navigation rather than paper entries, so a new layout should be tried.",
                        evidence=[*evidence[:5], *layout_evidence],
                        suggested_layout_name=layout_name,
                        raw={
                            "mode": review_input.mode,
                            "page_summary": review_input.page_summary,
                            "candidate_count": len(review_input.candidate_items),
                        },
                    )
                return ConferencePageReviewResult(
                    review_id=f"page_review_{_uuid_hex()}",
                    reviewed_at=_iso_now(),
                    reviewer="rule_based",
                    mode=review_input.mode,
                    decision="reject",
                    confidence=0.45,
                    reason="The matched layout looks like navigation rather than paper entries.",
                    evidence=evidence or ["matched items look like navigation"],
                    raw={
                        "mode": review_input.mode,
                        "page_summary": review_input.page_summary,
                        "candidate_count": len(review_input.candidate_items),
                    },
                )
            return ConferencePageReviewResult(
                review_id=f"page_review_{_uuid_hex()}",
                reviewed_at=_iso_now(),
                reviewer="rule_based",
                mode=review_input.mode,
                decision="accept",
                confidence=0.9 if evidence else 0.75,
                reason="Known conference layout matched and extracted items look structurally valid.",
                evidence=evidence or ["matched layout produced paper-like items"],
                raw={
                    "mode": review_input.mode,
                    "page_summary": review_input.page_summary,
                    "candidate_count": len(review_input.candidate_items),
                },
            )

        suggestion = _suggest_layout_from_summary(review_input.page_summary)
        if suggestion is not None:
            layout_name, reason, evidence = suggestion
            return ConferencePageReviewResult(
                review_id=f"page_review_{_uuid_hex()}",
                reviewed_at=_iso_now(),
                reviewer="rule_based",
                mode=review_input.mode,
                decision="suggest_new_layout",
                confidence=0.62,
                reason=reason,
                evidence=evidence,
                suggested_layout_name=layout_name,
                raw={
                    "mode": review_input.mode,
                    "page_summary": review_input.page_summary,
                },
            )

        return ConferencePageReviewResult(
            review_id=f"page_review_{_uuid_hex()}",
            reviewed_at=_iso_now(),
            reviewer="rule_based",
            mode=review_input.mode,
            decision="snapshot_only",
            confidence=0.25,
            reason="The page does not expose a clear conference-paper list structure.",
            evidence=["no clear list/table/card pattern in the page summary"],
            raw={
                "mode": review_input.mode,
                "page_summary": review_input.page_summary,
            },
        )


class PydanticAIConferencePageReviewer:
    def __init__(self, settings: AgentReviewConfig) -> None:
        self.settings = settings

    def review(self, review_input: ConferencePageReviewInput) -> ConferencePageReviewResult:
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
            decision: ConferencePageDecision
            confidence: float = Field(ge=0, le=1)
            reason: str
            evidence: list[str] = Field(default_factory=list)
            suggested_layout_name: str | None = None
            conference_page_mode: str | None = None
            conference_content_selector: str | None = None
            paper_selector: str | None = None
            paper_title_selector: str | None = None
            paper_link_selector: str | None = None
            paper_author_selector: str | None = None
            conference_author_selector: str | None = None

        model = OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(base_url=base_url, api_key=api_key),
        )
        agent = Agent(
            model,
            system_prompt=f"{_SYSTEM_PROMPT}\n\n{_JSON_OUTPUT_PROMPT}",
        )
        payload = review_input.to_payload()
        try:
            result = agent.run_sync(json.dumps(payload, ensure_ascii=False, indent=2))
            output = AgentOutput.model_validate(_extract_json_object(str(result.output)))
        except Exception as exc:
            raise ValueError(f"pydantic-ai conference page review failed: {exc}") from exc
        return ConferencePageReviewResult(
            review_id=f"page_review_{_uuid_hex()}",
            reviewed_at=_iso_now(),
            reviewer="pydantic_ai",
            mode=review_input.mode,
            decision=output.decision,
            confidence=float(output.confidence),
            reason=output.reason,
            evidence=output.evidence,
            suggested_layout_name=output.suggested_layout_name,
            conference_page_mode=output.conference_page_mode,
            conference_content_selector=output.conference_content_selector,
            paper_selector=output.paper_selector,
            paper_title_selector=output.paper_title_selector,
            paper_link_selector=output.paper_link_selector,
            paper_author_selector=output.paper_author_selector,
            conference_author_selector=output.conference_author_selector,
            raw={"mode": review_input.mode, "page_summary": review_input.page_summary},
        )


def _select_reviewer(requested: str, settings: AgentReviewConfig) -> str:
    if requested != "auto":
        return requested
    if settings.enabled and settings.default_reviewer == "pydantic_ai" and _pydantic_ai_ready(settings):
        return "pydantic_ai"
    return "rule_based"


def _candidate_evidence(candidate_items: list[dict[str, Any]]) -> list[str]:
    evidence: list[str] = []
    for item in candidate_items[:5]:
        title = item.get("title")
        if isinstance(title, str) and title.strip():
            evidence.append(f"candidate title: {title.strip()}")
    return evidence


def _candidate_items_look_like_navigation(candidate_items: list[dict[str, Any]]) -> bool:
    if not candidate_items:
        return False
    matches = 0
    for item in candidate_items:
        title = item.get("title")
        if not isinstance(title, str):
            continue
        normalized = _normalize_text(title).lower()
        if normalized in NAVIGATION_KEYWORDS:
            matches += 1
    return matches > 0 and matches >= max(1, len(candidate_items) // 2)


def _paper_candidates_payload(papers: list[Paper]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for paper in papers[:10]:
        payload.append(
            {
                "title": paper.title,
                "paper_url": paper.paper_url,
                "authors_text": paper.raw.get("conference_page_authors_text"),
                "layout": paper.raw.get("conference_page_layout"),
                "item_selector": paper.raw.get("conference_page_item_selector"),
                "title_selector": paper.raw.get("conference_page_title_selector"),
                "link_selector": paper.raw.get("conference_page_link_selector"),
                "author_selector": paper.raw.get("conference_page_author_selector"),
            }
        )
    return payload


def _summarize_page(content: bytes, snapshot_text: str) -> dict[str, Any]:
    soup = BeautifulSoup(content, "html.parser")
    headings = [_normalize_text(tag.get_text(" ", strip=True)) for tag in soup.select("h1, h2, h3") if _normalize_text(tag.get_text(" ", strip=True))]
    links = _collect_links(soup)
    return {
        "title": _normalize_text(soup.title.get_text(" ", strip=True)) if soup.title else None,
        "heading_texts": headings[:10],
        "body_excerpt": snapshot_text[:1500],
        "link_count": len(links),
        "sample_links": links[:12],
        "list_group_count": len(soup.select("div.list-group-item")),
        "table_count": len(soup.find_all("table")),
        "row_count": len(soup.find_all("tr")),
        "li_count": len(soup.find_all("li")),
        "article_count": len(soup.find_all("article")),
        "card_count": len(soup.select(".card, .paper-card, .session-card, .post-card")),
        "main_tags": [tag.name for tag in soup.select("main, section, article, div.main-content, div.container")[:8]],
    }


def _collect_links(soup: BeautifulSoup) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if not isinstance(href, str) or not href.strip():
            continue
        text = _normalize_text(anchor.get_text(" ", strip=True))
        key = (text, href.strip())
        if key in seen:
            continue
        seen.add(key)
        links.append({"text": text, "href": href.strip()})
    return links


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _suggest_layout_from_summary(summary: dict[str, Any]) -> tuple[str, str, list[str]] | None:
    if summary.get("list_group_count"):
        return (
            "bootstrap_list_group",
            "The page summary exposes Bootstrap-style list-group items.",
            ["list-group items are visible in the page summary"],
        )
    if summary.get("row_count") or summary.get("table_count"):
        return (
            "table_rows",
            "The page summary exposes table rows that can plausibly hold accepted-paper entries.",
            ["table-like structure is visible in the page summary"],
        )
    if summary.get("li_count") or summary.get("article_count") or summary.get("card_count"):
        return (
            "list_items",
            "The page summary exposes list/article/card items that can plausibly hold paper entries.",
            ["list-like structure is visible in the page summary"],
        )
    return None


def _layout_metadata(layout_name: str) -> dict[str, str]:
    for layout in DEFAULT_LAYOUTS:
        if layout.name == layout_name:
            metadata = {
                "conference_page_mode": layout.name,
                "paper_selector": layout.item_selector,
                "paper_title_selector": layout.title_selector,
            }
            if layout.link_selector:
                metadata["paper_link_selector"] = layout.link_selector
            if layout.author_selector:
                metadata["paper_author_selector"] = layout.author_selector
            return metadata
    return {}


def _matched_layout_name(papers: list[Paper]) -> str | None:
    if not papers:
        return None
    first = papers[0].raw.get("conference_page_layout")
    if isinstance(first, str) and first.strip():
        return first.strip()
    return None


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


def _uuid_hex() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


_SYSTEM_PROMPT = """
You supervise conference website page extraction.

Your job is not to invent papers. You only judge whether the provided extraction is trustworthy and, if not, whether you can infer a better layout.

For matched_layout mode:
- Review the extracted candidate items.
- Accept them if they look like genuine conference papers, accepted papers, program entries, or proceedings entries.
- Reject them or suggest a new layout if they are clearly navigation noise, duplicated menu entries, or obviously wrong structure.

For unknown_layout mode:
- Inspect the page summary and decide whether the page looks like a conference accepted-papers or program page.
- If you can infer a workable selector set, suggest it.
- If the page is still too unclear, return snapshot_only.

You must not invent paper titles, authors, or URLs.
Keep the decision conservative.
"""

_JSON_OUTPUT_PROMPT = """
Return exactly one JSON object, without Markdown, commentary, or tool calls.
Use this schema:
{
  "decision": "accept | reject | suggest_new_layout | snapshot_only",
  "confidence": 0.0,
  "reason": "short reason",
  "evidence": ["short evidence item"],
  "suggested_layout_name": "bootstrap_list_group | table_rows | list_items | null",
  "conference_page_mode": "string or null",
  "conference_content_selector": "string or null",
  "paper_selector": "string or null",
  "paper_title_selector": "string or null",
  "paper_link_selector": "string or null",
  "paper_author_selector": "string or null",
  "conference_author_selector": "string or null"
}
"""
