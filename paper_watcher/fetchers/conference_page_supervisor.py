from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from paper_watcher.agent_review.conference_page_review import (
    ConferencePageProcessingResult,
    ConferencePageReviewInput,
    process_conference_page,
)
from paper_watcher.fetchers.conference_page_handler import DEFAULT_LAYOUTS, extract_conference_page_papers
from paper_watcher.models import Source


@dataclass(frozen=True)
class ConferencePageSnapshotReview:
    papers: list[Any]
    diagnostics: dict[str, Any]


def supervise_conference_page(
    source: Source,
    content: bytes,
    *,
    now: datetime,
    content_hash: str,
    snapshot_text: str,
    review_config_dir: Path,
    reviewer: str = "auto",
) -> ConferencePageProcessingResult:
    return process_conference_page(
        source,
        content,
        now=now,
        content_hash=content_hash,
        snapshot_text=snapshot_text,
        review_config_dir=review_config_dir,
        reviewer=reviewer,
    )


def retry_conference_page_with_metadata(
    source: Source,
    content: bytes,
    *,
    now: datetime,
    content_hash: str,
    metadata: dict[str, Any],
) -> list[Any]:
    merged_metadata = {**(source.metadata or {}), **metadata}
    retry_source = replace(source, metadata=merged_metadata)
    return extract_conference_page_papers(
        source=retry_source,
        content=content,
        now=now,
        content_hash=content_hash,
    )


def layout_metadata_for_name(layout_name: str) -> dict[str, str]:
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


def summarize_page_html(content: bytes, snapshot_text: str) -> dict[str, Any]:
    soup = BeautifulSoup(content, "html.parser")
    headings = [tag.get_text(" ", strip=True) for tag in soup.select("h1, h2, h3") if tag.get_text(" ", strip=True)]
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if not isinstance(href, str) or not href.strip():
            continue
        text = anchor.get_text(" ", strip=True).strip()
        key = (text, href.strip())
        if key in seen:
            continue
        seen.add(key)
        links.append({"text": text, "href": href.strip()})
    return {
        "title": soup.title.get_text(" ", strip=True) if soup.title else None,
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

