from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from paper_watcher.agent_review.search_review import ConferenceSearchReview
from paper_watcher.conference_discovery import load_venue_profiles
from paper_watcher.conference_review_promoter import promote_conference_review
from paper_watcher.conference_search import search_and_review_conference
from paper_watcher.models import AppConfig, Source, SourceType, VenueType
from paper_watcher.settings import resolve_project_path
from paper_watcher.storage.file_storage import FileStateStore, WatchEvent


@dataclass(frozen=True)
class ConferenceSignalReviewResult:
    task_key: str
    venue_id: str
    year: int
    reviewed: bool
    promoted_candidate: bool = False
    error: str | None = None


def process_conference_signal_events(
    config: AppConfig,
    events: list[WatchEvent],
    *,
    reviewer: str = "auto",
    num_results: int = 10,
) -> list[ConferenceSignalReviewResult]:
    results: list[ConferenceSignalReviewResult] = []
    for event in events:
        signal = detect_conference_signal(config, event)
        if signal is None:
            continue
        results.append(
            review_conference_signal(
                config,
                signal,
                reviewer=reviewer,
                num_results=num_results,
            )
        )
    return results


def run_due_conference_signal_reviews(
    config: AppConfig,
    *,
    reviewer: str = "auto",
    num_results: int = 10,
) -> list[ConferenceSignalReviewResult]:
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    tasks = store.load_scheduled_tasks()
    now = datetime.now(UTC)
    results: list[ConferenceSignalReviewResult] = []
    for task_key, task in sorted(tasks.items()):
        if not task_key.startswith("conference_signal_review:"):
            continue
        next_check_after = _parse_datetime(task.get("next_check_after"))
        if next_check_after is None or next_check_after > now:
            continue
        venue_id = task.get("venue_id")
        year = task.get("year")
        if not isinstance(venue_id, str) or not isinstance(year, int):
            continue
        signal = ConferenceSignal(
            event_id=str(task.get("last_signal_event_id") or task_key),
            seen_at=str(task.get("last_signal_at") or datetime.now(UTC).isoformat()),
            source_id=str(task.get("source_id") or ""),
            source_name=str(task.get("source_name") or venue_id),
            venue_id=venue_id,
            year=year,
            signal_type=str(task.get("signal_type") or "scheduled_followup"),
            title=str(task.get("signal_title") or ""),
            link=task.get("signal_link") if isinstance(task.get("signal_link"), str) else None,
            raw=task.get("signal_raw") if isinstance(task.get("signal_raw"), dict) else {},
        )
        results.append(
            review_conference_signal(
                config,
                signal,
                reviewer=str(task.get("reviewer") or reviewer),
                num_results=int(task.get("num_results") or num_results),
                triggered_by_due_task=True,
            )
        )
    return results


@dataclass(frozen=True)
class ConferenceSignal:
    event_id: str
    seen_at: str
    source_id: str
    source_name: str
    venue_id: str
    year: int
    signal_type: str
    title: str
    link: str | None
    raw: dict[str, Any]


def detect_conference_signal(config: AppConfig, event: WatchEvent) -> ConferenceSignal | None:
    if event.source_type != SourceType.DBLP.value:
        return None
    source = next((item for item in config.sources.sources if item.id == event.source_id), None)
    if source is None or source.source_type != SourceType.DBLP:
        return None
    if source.venue_type != VenueType.CONFERENCE:
        return None
    year = _event_year(event)
    if year is None:
        return None
    signal_type = _dblp_signal_type(event)
    if signal_type is None:
        return None
    venue_id = _venue_id_for_dblp_source(config, source)
    if venue_id is None:
        return None
    return ConferenceSignal(
        event_id=event.event_id,
        seen_at=event.seen_at,
        source_id=source.id,
        source_name=source.name,
        venue_id=venue_id,
        year=year,
        signal_type=signal_type,
        title=event.title,
        link=event.link,
        raw=event.raw,
    )


def review_conference_signal(
    config: AppConfig,
    signal: ConferenceSignal,
    *,
    reviewer: str = "auto",
    num_results: int = 10,
    triggered_by_due_task: bool = False,
) -> ConferenceSignalReviewResult:
    task_key = _task_key(signal.venue_id, signal.year)
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    tasks = store.load_scheduled_tasks()
    previous = tasks.get(task_key, {})
    started_at = datetime.now(UTC).isoformat()
    tasks[task_key] = {
        **previous,
        "type": "conference_signal_review",
        "venue_id": signal.venue_id,
        "year": signal.year,
        "source_id": signal.source_id,
        "source_name": signal.source_name,
        "signal_type": signal.signal_type,
        "signal_title": signal.title,
        "signal_link": signal.link,
        "signal_raw": signal.raw,
        "last_signal_event_id": signal.event_id,
        "last_signal_at": signal.seen_at,
        "last_started_at": started_at,
        "reviewer": reviewer,
        "num_results": num_results,
        "triggered_by_due_task": triggered_by_due_task,
    }
    store.save_scheduled_tasks(tasks)

    try:
        _search_result, review_result = search_and_review_conference(
            config,
            venue_id=signal.venue_id,
            year=signal.year,
            reviewer=reviewer,
            num_results=num_results,
            dry_run=False,
        )
        promoted_candidate = _promote_if_monitorable(config, review_result.review)
        tasks = store.load_scheduled_tasks()
        tasks[task_key] = _updated_task_after_review(
            tasks.get(task_key, {}),
            signal=signal,
            review=review_result.review,
            promoted_candidate=promoted_candidate,
            reviewer=reviewer,
            num_results=num_results,
        )
        store.save_scheduled_tasks(tasks)
        return ConferenceSignalReviewResult(
            task_key=task_key,
            venue_id=signal.venue_id,
            year=signal.year,
            reviewed=True,
            promoted_candidate=promoted_candidate,
        )
    except Exception as exc:
        tasks = store.load_scheduled_tasks()
        task = tasks.get(task_key, {})
        task = {
            **task,
            "last_error_at": datetime.now(UTC).isoformat(),
            "last_error": str(exc),
            "next_check_after": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "next_check_reason": "retry after signal review failure",
        }
        tasks[task_key] = task
        store.save_scheduled_tasks(tasks)
        return ConferenceSignalReviewResult(
            task_key=task_key,
            venue_id=signal.venue_id,
            year=signal.year,
            reviewed=False,
            error=str(exc),
        )


def render_signal_review_results(results: list[ConferenceSignalReviewResult], *, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps({"count": len(results), "results": [result.__dict__ for result in results]}, ensure_ascii=False, indent=2)
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    if not results:
        return "No conference signal reviews were triggered."
    lines = ["Conference signal reviews:", ""]
    for result in results:
        status = "reviewed" if result.reviewed else "failed"
        lines.append(f"- {result.task_key}: {status} venue={result.venue_id} year={result.year}")
        if result.promoted_candidate:
            lines.append("  promoted_candidate=true")
        if result.error:
            lines.append(f"  error={result.error}")
    return "\n".join(lines)


def _updated_task_after_review(
    task: dict[str, Any],
    *,
    signal: ConferenceSignal,
    review: ConferenceSearchReview,
    promoted_candidate: bool,
    reviewer: str,
    num_results: int,
) -> dict[str, Any]:
    fallback_dates_text = signal.title if _after_visible_conference_date(signal.title, signal.year) is not None else None
    dates_text = review.dates_text or fallback_dates_text
    next_check_after, next_check_reason = _next_check_from_review(review, fallback_dates_text=fallback_dates_text)
    return {
        **task,
        "type": "conference_signal_review",
        "venue_id": signal.venue_id,
        "year": signal.year,
        "source_id": signal.source_id,
        "source_name": signal.source_name,
        "signal_type": signal.signal_type,
        "signal_title": signal.title,
        "signal_link": signal.link,
        "signal_raw": signal.raw,
        "last_signal_event_id": signal.event_id,
        "last_signal_at": signal.seen_at,
        "last_success_at": datetime.now(UTC).isoformat(),
        "last_review_id": review.review_id,
        "conference_status": review.conference_status,
        "accepted_info_status": review.accepted_info_status,
        "action": review.action,
        "confidence": review.confidence,
        "official_url": review.official_url,
        "accepted_info_url": review.accepted_info_url,
        "dates_text": dates_text,
        "promoted_candidate": promoted_candidate,
        "reviewer": reviewer,
        "num_results": num_results,
        "next_check_after": next_check_after,
        "next_check_reason": next_check_reason,
        "last_error": None,
        "last_error_at": None,
    }


def _promote_if_monitorable(config: AppConfig, review: ConferenceSearchReview) -> bool:
    if review.action != "monitor_accepted_page" or review.accepted_info_status != "public":
        return False
    try:
        promote_conference_review(config, review_id=review.review_id, dry_run=False)
    except ValueError:
        return False
    return True


def _next_check_from_review(
    review: ConferenceSearchReview,
    *,
    fallback_dates_text: str | None = None,
) -> tuple[str | None, str | None]:
    if review.accepted_info_status == "public":
        return None, "accepted/program information already public"
    now = datetime.now(UTC)
    date_after = _after_visible_conference_date(review.dates_text or fallback_dates_text, review.year)
    if date_after is not None:
        if date_after <= now:
            return (now + timedelta(days=1)).isoformat(), "visible conference date has passed"
        return date_after.isoformat(), "after visible conference date"
    if review.conference_status in {"scheduled", "likely_scheduled"}:
        return (now + timedelta(days=30)).isoformat(), "scheduled but accepted information not public"
    return (now + timedelta(days=7)).isoformat(), "weak or unclear signal"


def _after_visible_conference_date(dates_text: str | None, default_year: int) -> datetime | None:
    if not dates_text:
        return None
    text = dates_text.replace(",", " ")
    month_names = "|".join(_MONTHS)
    range_match = re.search(
        rf"\b({month_names})\.?\s+(\d{{1,2}})\s*(?:-|to|–|—)\s*(?:(?:{month_names})\.?\s+)?(\d{{1,2}})\s+(\d{{4}})\b",
        text,
        flags=re.IGNORECASE,
    )
    if range_match:
        month = _month_number(range_match.group(1))
        day = int(range_match.group(3))
        year = int(range_match.group(4))
        return datetime(year, month, day, tzinfo=UTC) + timedelta(days=1)
    single_match = re.search(rf"\b({month_names})\.?\s+(\d{{1,2}})\s+(\d{{4}})\b", text, flags=re.IGNORECASE)
    if single_match:
        month = _month_number(single_match.group(1))
        day = int(single_match.group(2))
        year = int(single_match.group(3))
        return datetime(year, month, day, tzinfo=UTC) + timedelta(days=1)
    no_year_match = re.search(
        rf"\b({month_names})\.?\s+(\d{{1,2}})\s*(?:-|to|–|—)\s*(?:(?:{month_names})\.?\s+)?(\d{{1,2}})\b",
        text,
        flags=re.IGNORECASE,
    )
    if no_year_match:
        month = _month_number(no_year_match.group(1))
        day = int(no_year_match.group(3))
        return datetime(default_year, month, day, tzinfo=UTC) + timedelta(days=1)
    return None


def _venue_id_for_dblp_source(config: AppConfig, source: Source) -> str | None:
    profiles = load_venue_profiles(config.config_dir)
    for profile in profiles:
        keys = profile.dblp_venue_keys
        if source.venue_key and source.venue_key in keys:
            return profile.venue_id
    if source.id.startswith("dblp_"):
        source_suffix = source.id.removeprefix("dblp_")
        for profile in profiles:
            if profile.venue_id == source_suffix:
                return profile.venue_id
    return None


def _event_year(event: WatchEvent) -> int | None:
    published_at = event.raw.get("published_at")
    if isinstance(published_at, str) and len(published_at) >= 4 and published_at[:4].isdigit():
        return int(published_at[:4])
    title_match = re.search(r"\b(20\d{2})\b", event.title)
    if title_match:
        return int(title_match.group(1))
    key = event.raw.get("dblp_key")
    if isinstance(key, str):
        key_match = re.search(r"/(20\d{2})(?:/|$)", key)
        if key_match:
            return int(key_match.group(1))
    return None


def _dblp_signal_type(event: WatchEvent) -> str | None:
    key = event.raw.get("dblp_key")
    if isinstance(key, str) and re.fullmatch(r"conf/[^/]+/20\d{2}", key):
        return "proceedings_indexed"
    if not event.raw.get("authors") and event.raw.get("venue_key") and re.search(r"\bproceedings\b", event.title, re.IGNORECASE):
        return "proceedings_indexed"
    return None


def _task_key(venue_id: str, year: int) -> str:
    return f"conference_signal_review:{venue_id}:{year}"


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def _month_number(value: str) -> int:
    return _MONTHS[value.lower().rstrip(".")]
