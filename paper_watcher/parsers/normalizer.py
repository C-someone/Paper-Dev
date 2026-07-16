from __future__ import annotations

import hashlib
import re
from datetime import datetime


ARXIV_ID_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)


def normalize_title(title: str) -> str:
    normalized = title.lower()
    normalized = re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def stable_hash(value: str, prefix: str = "paper") -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def extract_arxiv_id(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        match = ARXIV_ID_RE.search(value)
        if match:
            return match.group("id")
    return None


def extract_doi(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        match = DOI_RE.search(value)
        if match:
            return match.group(0).rstrip(".").lower()
    return None


def paper_identity(
    normalized_title: str,
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    dblp_key: str | None = None,
    openreview_id: str | None = None,
    first_author: str | None = None,
    year: int | None = None,
) -> str:
    if doi:
        return stable_hash(f"doi:{doi}", "paper")
    if arxiv_id:
        return stable_hash(f"arxiv:{arxiv_id}", "paper")
    if dblp_key:
        return stable_hash(f"dblp:{dblp_key}", "paper")
    if openreview_id:
        return stable_hash(f"openreview:{openreview_id}", "paper")
    suffix = f"{first_author or ''}:{year or ''}"
    return stable_hash(f"title:{normalized_title}:{suffix}", "paper")


def parse_year(value: datetime | None) -> int | None:
    if value is None:
        return None
    return value.year
