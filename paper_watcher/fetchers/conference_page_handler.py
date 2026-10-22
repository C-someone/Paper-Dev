from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from paper_watcher.models import Paper, Recommendation, Source
from paper_watcher.parsers.normalizer import normalize_title


@dataclass(frozen=True)
class ConferencePageLayout:
    name: str
    item_selector: str
    title_selector: str
    link_selector: str | None = None
    author_selector: str | None = None
    allow_text_fallback: bool = False


DEFAULT_LAYOUTS: tuple[ConferencePageLayout, ...] = (
    ConferencePageLayout(
        name="bootstrap_list_group",
        item_selector="div.list-group-item",
        title_selector="a",
        link_selector="a",
        author_selector="div.collapse.authorlist",
    ),
    ConferencePageLayout(
        name="table_rows",
        item_selector="div.main-content tr, table tr",
        title_selector="b",
        link_selector=None,
        author_selector="span.table-description",
    ),
    ConferencePageLayout(
        name="list_items",
        item_selector="li",
        title_selector="a",
        link_selector="a",
        author_selector=None,
    ),
)

NAVIGATION_KEYWORDS = {
    "home",
    "program",
    "accepted papers",
    "accepted",
    "call for papers",
    "registration",
    "artifacts",
    "posters",
    "workshops",
    "donors",
    "travel grants",
    "student travel grants",
    "attendee code of conduct",
    "overview",
    "keynote",
    "papers",
    "information for student attendees",
    "slack channels",
}


def extract_conference_page_snapshot_text(source: Source, content: bytes) -> str:
    soup = BeautifulSoup(content, "html.parser")
    metadata = source.metadata or {}

    for selector_key in ("conference_content_selector", "content_selector"):
        selector = _metadata_text(metadata, selector_key)
        if selector:
            text = _select_text(soup, selector)
            if text:
                return text

    for candidate in _conference_body_candidates(soup):
        text = _normalize_text(candidate.get_text(" ", strip=True))
        if text:
            return text

    return _normalize_text(soup.get_text(" ", strip=True))


def extract_conference_page_papers(
    *,
    source: Source,
    content: bytes,
    now: datetime,
    content_hash: str,
) -> list[Paper]:
    soup = BeautifulSoup(content, "html.parser")
    metadata = source.metadata or {}
    seen_ids: set[str] = set()

    for layout in _candidate_layouts(metadata):
        papers = _extract_with_layout(
            source=source,
            soup=soup,
            layout=layout,
            now=now,
            content_hash=content_hash,
            seen_ids=seen_ids,
            metadata=metadata,
        )
        if papers:
            return papers
    return []


def _candidate_layouts(metadata: dict[str, Any]) -> tuple[ConferencePageLayout, ...]:
    explicit_selector = _metadata_text(metadata, "paper_selector")
    title_selector = _metadata_text(metadata, "paper_title_selector")
    link_selector = _metadata_text(metadata, "paper_link_selector")
    author_selector = _metadata_text(metadata, "paper_author_selector") or _metadata_text(metadata, "conference_author_selector")
    mode = (_metadata_text(metadata, "conference_page_mode") or "auto").lower()

    layouts: list[ConferencePageLayout] = []

    if explicit_selector:
        layouts.append(
            ConferencePageLayout(
                name=mode if mode != "auto" else "explicit",
                item_selector=explicit_selector,
                title_selector=title_selector or _default_title_selector_for_mode(mode),
                link_selector=link_selector or _default_link_selector_for_mode(mode),
                author_selector=author_selector or _default_author_selector_for_mode(mode),
                allow_text_fallback=not title_selector,
            )
        )

    if mode in {"bootstrap_list_group", "list_group", "list_group_item"}:
        layouts.append(_layout_for_mode("bootstrap_list_group"))
    elif mode in {"table_rows", "table_row"}:
        layouts.append(_layout_for_mode("table_rows"))
    elif mode in {"list_items", "li_items", "accepted_list"}:
        layouts.append(_layout_for_mode("list_items"))

    layouts.extend(DEFAULT_LAYOUTS)
    return tuple(layouts)


def _layout_for_mode(mode: str) -> ConferencePageLayout:
    for layout in DEFAULT_LAYOUTS:
        if layout.name == mode:
            return layout
    return DEFAULT_LAYOUTS[0]


def _extract_with_layout(
    *,
    source: Source,
    soup: BeautifulSoup,
    layout: ConferencePageLayout,
    now: datetime,
    content_hash: str,
    seen_ids: set[str],
    metadata: dict[str, Any],
) -> list[Paper]:
    items = soup.select(layout.item_selector)
    papers: list[Paper] = []
    for item in items:
        if not isinstance(item, Tag):
            continue
        if _is_navigation_item(item):
            continue
        title = _extract_item_title(item, layout, metadata)
        if not title:
            continue
        link = _extract_item_link(item, layout, source.watch_url)
        paper_id = f"website-paper:{source.id}:{hashlib.sha256(normalize_title(title).encode('utf-8')).hexdigest()}"
        if paper_id in seen_ids:
            continue
        seen_ids.add(paper_id)
        authors_text = _extract_item_authors(item, layout, metadata)
        papers.append(
            Paper(
                id=paper_id,
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
                paper_url=link or source.watch_url,
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
                    "website_watch_item": True,
                    "conference_page_item": True,
                    "conference_page_layout": layout.name,
                    "conference_page_item_selector": layout.item_selector,
                    "conference_page_title_selector": layout.title_selector,
                    "conference_page_link_selector": layout.link_selector,
                    "conference_page_author_selector": layout.author_selector,
                    "conference_page_authors_text": authors_text,
                    "parent_content_hash": content_hash,
                },
            )
        )
    return papers


def _extract_item_title(item: Tag, layout: ConferencePageLayout, metadata: dict[str, Any]) -> str | None:
    selectors = [layout.title_selector]
    selectors.extend(_selector_aliases(metadata, "paper_title_selector"))
    selectors.extend(["a", "b", "h2", "h3", "h4"])
    for selector in selectors:
        if not selector:
            continue
        title_element = item.select_one(selector)
        if title_element:
            title = _normalize_text(title_element.get_text(" ", strip=True))
            if title and not _is_navigation_title(title):
                return title
    if not layout.allow_text_fallback:
        return None
    title = _normalize_text(item.get_text(" ", strip=True))
    if title and not _is_navigation_title(title):
        return title
    return None


def _extract_item_link(item: Tag, layout: ConferencePageLayout, base_url: str | None) -> str | None:
    selectors = [layout.link_selector]
    for selector in selectors:
        if not selector:
            continue
        link_element = item.select_one(selector)
        if link_element is None:
            continue
        href = link_element.get("href")
        if isinstance(href, str):
            href = href.strip()
            if href and not href.startswith("#"):
                return urljoin(base_url or "", href)
    anchor = item.select_one("a")
    href = anchor.get("href") if anchor else None
    if isinstance(href, str):
        href = href.strip()
        if href and not href.startswith("#"):
            return urljoin(base_url or "", href)
    return None


def _extract_item_authors(item: Tag, layout: ConferencePageLayout, metadata: dict[str, Any]) -> str | None:
    selectors = [layout.author_selector]
    selectors.extend(_selector_aliases(metadata, "paper_author_selector"))
    selectors.extend(_selector_aliases(metadata, "conference_author_selector"))
    for selector in selectors:
        if not selector:
            continue
        author_element = item.select_one(selector)
        if author_element:
            authors_text = _normalize_text(_element_direct_text(author_element))
            if authors_text:
                return authors_text
    return None


def _element_direct_text(element: Tag) -> str:
    parts: list[str] = []
    for child in element.children:
        if isinstance(child, Tag):
            if child.name == "br":
                break
            parts.append(child.get_text(" ", strip=True))
        else:
            parts.append(str(child))
    return " ".join(parts)


def _is_navigation_item(item: Tag) -> bool:
    if any(parent.name in {"nav", "header", "footer"} for parent in item.parents if isinstance(parent, Tag)):
        return True
    title = _normalize_text(item.get_text(" ", strip=True))
    return _is_navigation_title(title)


def _is_navigation_title(title: str) -> bool:
    normalized = _normalize_text(title).lower()
    return normalized in NAVIGATION_KEYWORDS


def _default_title_selector_for_mode(mode: str) -> str | None:
    return {
        "bootstrap_list_group": "a",
        "table_rows": "b",
        "list_items": "a",
    }.get(mode)


def _default_link_selector_for_mode(mode: str) -> str | None:
    return {
        "bootstrap_list_group": "a",
        "table_rows": None,
        "list_items": "a",
    }.get(mode)


def _default_author_selector_for_mode(mode: str) -> str | None:
    return {
        "bootstrap_list_group": "div.collapse.authorlist",
        "table_rows": "span.table-description",
        "list_items": None,
    }.get(mode)


def _select_text(soup: BeautifulSoup, selector: str) -> str:
    elements = soup.select(selector)
    if not elements:
        return ""
    text = "\n".join(element.get_text(" ", strip=True) for element in elements)
    normalized = _normalize_text(text)
    return normalized


def _conference_body_candidates(soup: BeautifulSoup) -> list[Tag]:
    body = soup.body
    if body is None:
        return []
    candidates: list[Tag] = []
    for child in body.find_all(recursive=False):
        if not isinstance(child, Tag):
            continue
        if child.name in {"script", "style", "footer"}:
            continue
        text = _normalize_text(child.get_text(" ", strip=True))
        if text:
            candidates.append(child)
    candidates.sort(key=lambda item: len(_normalize_text(item.get_text(" ", strip=True))), reverse=True)
    return candidates


def _metadata_text(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _selector_aliases(metadata: dict[str, Any], key: str) -> list[str]:
    value = _metadata_text(metadata, key)
    if not value:
        return []
    return [value]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
