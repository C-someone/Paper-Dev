from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from paper_watcher.agent_review.search_review import ConferenceSearchReview
from paper_watcher.conference_discovery import load_venue_profiles
from paper_watcher.conference_search import ConferenceSearchResult, search_and_review_conference
from paper_watcher.models import AppConfig


@dataclass(frozen=True)
class ConferenceReviewBatchItem:
    venue_id: str
    year: int
    ok: bool
    review: ConferenceSearchReview | None = None
    search: ConferenceSearchResult | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "venue_id": self.venue_id,
            "year": self.year,
            "ok": self.ok,
            "error": self.error,
        }
        if self.review is not None:
            data["review"] = self.review.to_dict()
        if self.search is not None:
            data["search"] = self.search.search_input.to_json_payload()
        return {key: value for key, value in data.items() if value is not None}


@dataclass(frozen=True)
class ConferenceReviewBatchResult:
    started_at: str
    finished_at: str
    target_year: int
    items: list[ConferenceReviewBatchItem]
    response_text: str

    @property
    def reviewed_count(self) -> int:
        return sum(1 for item in self.items if item.ok)

    @property
    def error_count(self) -> int:
        return sum(1 for item in self.items if not item.ok)


def review_conferences_batch(
    config: AppConfig,
    *,
    venue_id: str | None = None,
    year: int | None = None,
    reviewer: str = "auto",
    num_results: int = 10,
    dry_run: bool = False,
    output_format: str = "text",
) -> ConferenceReviewBatchResult:
    target_year = year or datetime.now(UTC).year
    profiles = load_venue_profiles(config.config_dir)
    if venue_id:
        profiles = [profile for profile in profiles if profile.venue_id == venue_id]
        if not profiles:
            raise ValueError(f"venue profile not found: {venue_id}")

    started_at = _iso_now()
    items: list[ConferenceReviewBatchItem] = []
    for profile in profiles:
        try:
            search_result, review_result = search_and_review_conference(
                config,
                venue_id=profile.venue_id,
                year=target_year,
                reviewer=reviewer,
                num_results=num_results,
                dry_run=dry_run,
            )
        except Exception as exc:
            items.append(
                ConferenceReviewBatchItem(
                    venue_id=profile.venue_id,
                    year=target_year,
                    ok=False,
                    error=str(exc),
                )
            )
            continue
        items.append(
            ConferenceReviewBatchItem(
                venue_id=profile.venue_id,
                year=target_year,
                ok=True,
                review=review_result.review,
                search=search_result,
            )
        )

    finished_at = _iso_now()
    result = ConferenceReviewBatchResult(
        started_at=started_at,
        finished_at=finished_at,
        target_year=target_year,
        items=items,
        response_text="",
    )
    return ConferenceReviewBatchResult(
        started_at=result.started_at,
        finished_at=result.finished_at,
        target_year=result.target_year,
        items=result.items,
        response_text=render_batch_result(result, output_format=output_format),
    )


def render_batch_result(result: ConferenceReviewBatchResult, *, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(
            {
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "target_year": result.target_year,
                "reviewed_count": result.reviewed_count,
                "error_count": result.error_count,
                "items": [item.to_dict() for item in result.items],
            },
            ensure_ascii=False,
            indent=2,
        )
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")

    action_counts: dict[str, int] = {}
    for item in result.items:
        if item.review is None:
            continue
        action_counts[item.review.action] = action_counts.get(item.review.action, 0) + 1

    lines = [
        f"Conference review batch: {result.target_year}",
        f"Reviewed: {result.reviewed_count}",
        f"Errors: {result.error_count}",
    ]
    for action in ("monitor_accepted_page", "monitor_cfp_page", "needs_review", "ignore"):
        lines.append(f"{action}: {action_counts.get(action, 0)}")
    lines.append("")
    for item in result.items:
        if item.review is None:
            lines.append(f"- {item.venue_id} {item.year}: ERROR {item.error}")
            continue
        review = item.review
        lines.append(
            f"- {item.venue_id} {item.year}: action={review.action} "
            f"accepted={review.accepted_info_status} confidence={review.confidence:.2f}"
        )
        if review.accepted_info_url:
            lines.append(f"  accepted_info_url={review.accepted_info_url}")
        if review.official_url:
            lines.append(f"  official_url={review.official_url}")
    return "\n".join(lines)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()
