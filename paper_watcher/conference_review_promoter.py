from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from paper_watcher.agent_review.search_review import ConferenceSearchReview, load_agent_review_config
from paper_watcher.conference_discovery import SourceCandidate, SourceCandidateStore, VenueProfile, load_venue_profiles
from paper_watcher.models import AppConfig
from paper_watcher.settings import resolve_project_path
from paper_watcher.storage.file_storage import FileStateStore


@dataclass(frozen=True)
class ReviewPromotionResult:
    candidate: SourceCandidate
    review: ConferenceSearchReview
    promoted: bool
    response_text: str


def promote_conference_review(
    config: AppConfig,
    *,
    review_id: str | None = None,
    venue_id: str | None = None,
    year: int | None = None,
    dry_run: bool = False,
    output_format: str = "text",
) -> ReviewPromotionResult:
    if review_id is None and (venue_id is None or year is None):
        raise ValueError("provide either review_id or both venue_id and year")
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    reviews = [ConferenceSearchReview.from_dict(item) for item in store.load_conference_search_reviews()]
    review = _select_review(reviews, review_id=review_id, venue_id=venue_id, year=year)
    settings = load_agent_review_config(config.config_dir)
    _validate_review_for_promotion(review, min_confidence=settings.monitor_min_confidence)
    profile = _get_profile(config, review.venue_id)
    candidate = _candidate_from_review(profile, review)
    if not dry_run:
        SourceCandidateStore(store).upsert_candidates([candidate])
    return ReviewPromotionResult(
        candidate=candidate,
        review=review,
        promoted=not dry_run,
        response_text=render_review_promotion(candidate, review=review, dry_run=dry_run, output_format=output_format),
    )


def render_review_promotion(
    candidate: SourceCandidate,
    *,
    review: ConferenceSearchReview,
    dry_run: bool,
    output_format: str = "text",
) -> str:
    if output_format == "json":
        return json.dumps(
            {
                "dry_run": dry_run,
                "promoted": not dry_run,
                "review": review.to_dict(),
                "candidate": candidate.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    prefix = "Promotion preview" if dry_run else "Promoted review"
    return "\n".join(
        [
            f"{prefix}: {review.review_id}",
            f"candidate_id={candidate.candidate_id}",
            f"source_id={candidate.source_id}",
            f"venue={candidate.venue_id} year={candidate.year} kind={candidate.kind}",
            f"confidence={candidate.confidence:.2f}",
            f"url={candidate.url}",
        ]
    )


def _select_review(
    reviews: list[ConferenceSearchReview],
    *,
    review_id: str | None,
    venue_id: str | None,
    year: int | None,
) -> ConferenceSearchReview:
    if review_id:
        for review in reviews:
            if review.review_id == review_id:
                return review
        raise ValueError(f"conference review not found: {review_id}")
    matched = [review for review in reviews if review.venue_id == venue_id and review.year == year]
    if not matched:
        raise ValueError(f"conference review not found for {venue_id} {year}")
    matched.sort(key=lambda item: item.reviewed_at, reverse=True)
    return matched[0]


def _validate_review_for_promotion(review: ConferenceSearchReview, *, min_confidence: float) -> None:
    if review.action != "monitor_accepted_page":
        raise ValueError(f"review action is not promotable: {review.action}")
    if review.accepted_info_status != "public":
        raise ValueError(f"accepted information is not public: {review.accepted_info_status}")
    if review.confidence < min_confidence:
        raise ValueError(f"review confidence {review.confidence:.2f} is below threshold {min_confidence:.2f}")
    if not review.accepted_info_url:
        raise ValueError("review has no accepted_info_url")


def _candidate_from_review(profile: VenueProfile, review: ConferenceSearchReview) -> SourceCandidate:
    kind = "accepted_papers"
    url = review.accepted_info_url
    if url is None:
        raise ValueError("review has no accepted_info_url")
    source_id = _slug(f"{profile.venue_id}_{review.year}_{kind}")
    source_name = f"{profile.short_name} {review.year} Accepted Papers"
    now = _iso_now()
    candidate_id = "cand_" + hashlib.sha256(f"{profile.venue_id}|{review.year}|{kind}|{url}".encode()).hexdigest()[:16]
    metadata = dict(profile.default_metadata)
    metadata["review_id"] = review.review_id
    metadata["reviewer"] = review.reviewer
    return SourceCandidate(
        candidate_id=candidate_id,
        venue_id=profile.venue_id,
        year=review.year,
        kind=kind,
        url=url,
        source_id=source_id,
        source_name=source_name,
        css_selector=profile.default_css_selector,
        ccf_level=profile.ccf_level,
        area=profile.area,
        venue_type=profile.venue_type,
        priority=profile.priority,
        confidence=review.confidence,
        reason=review.reason,
        probe_status="reviewed",
        status="pending",
        first_seen_at=review.reviewed_at or now,
        last_checked_at=now,
        metadata=metadata,
        tags=sorted(set(profile.tags + [profile.venue_id, kind, "agent_review"])),
    )


def _get_profile(config: AppConfig, venue_id: str) -> VenueProfile:
    for profile in load_venue_profiles(config.config_dir):
        if profile.venue_id == venue_id:
            return profile
    raise ValueError(f"venue profile not found: {venue_id}")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()
