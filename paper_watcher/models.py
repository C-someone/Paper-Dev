from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal


class SourceType(StrEnum):
    RSS = "rss"
    ARXIV = "arxiv"
    DBLP = "dblp"
    OPENREVIEW = "openreview"
    WEBSITE_WATCH = "website_watch"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    EMAIL_IMPORT = "email_import"


class CcfLevel(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    NON_CCF_HIGH_VALUE = "non_ccf_high_value"
    NON_CCF = "non_ccf"
    UNKNOWN = "unknown"


class VenueType(StrEnum):
    JOURNAL = "journal"
    CONFERENCE = "conference"
    PREPRINT = "preprint"
    UNKNOWN = "unknown"


class SourceStatus(StrEnum):
    VERIFIED = "verified"
    NEEDS_VERIFICATION = "needs_verification"
    DEPRECATED = "deprecated"


class Recommendation(StrEnum):
    READ = "read"
    SKIM = "skim"
    ARCHIVE = "archive"
    IGNORE = "ignore"


class NotificationPolicy(StrEnum):
    NOTIFY = "notify"
    RECORD_ONLY = "record_only"


class ModelError(ValueError):
    """Raised when config data cannot be converted into a valid model."""


def _required_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelError(f"{key} is required and must be a non-empty string")
    return value.strip()


def _optional_text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ModelError(f"{key} must be a string")
    return value.strip() or None


def _enum(enum_type: type[StrEnum], value: Any, key: str):
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ModelError(f"{key} must be one of: {allowed}") from exc


def _priority(data: dict[str, Any], key: str = "priority", default: int = 3) -> int:
    value = data.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ModelError(f"{key} must be an integer")
    if value < 1 or value > 5:
        raise ModelError(f"{key} must be between 1 and 5")
    return value


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ModelError(f"{key} must be a list of strings")
    return value


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ModelError(f"{key} must be a mapping")
    return value


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    source_type: SourceType
    enabled: bool = True
    url: str | None = None
    feed_url: str | None = None
    watch_url: str | None = None
    css_selector: str | None = None
    venue_key: str | None = None
    openreview_venue_id: str | None = None
    mailbox_label: str | None = None
    ccf_level: CcfLevel = CcfLevel.UNKNOWN
    area: str | None = None
    venue_type: VenueType = VenueType.UNKNOWN
    priority: int = 3
    status: SourceStatus = SourceStatus.NEEDS_VERIFICATION
    notification_policy: NotificationPolicy = NotificationPolicy.NOTIFY
    tags: list[str] = field(default_factory=list)
    schedule: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Source:
        if not isinstance(data, dict):
            raise ModelError("source must be a mapping")
        source = cls(
            id=_required_text(data, "id"),
            name=_required_text(data, "name"),
            source_type=_enum(SourceType, data.get("source_type"), "source_type"),
            enabled=bool(data.get("enabled", True)),
            url=_optional_text(data, "url"),
            feed_url=_optional_text(data, "feed_url"),
            watch_url=_optional_text(data, "watch_url"),
            css_selector=_optional_text(data, "css_selector"),
            venue_key=_optional_text(data, "venue_key"),
            openreview_venue_id=_optional_text(data, "openreview_venue_id"),
            mailbox_label=_optional_text(data, "mailbox_label"),
            ccf_level=_enum(CcfLevel, data.get("ccf_level", CcfLevel.UNKNOWN.value), "ccf_level"),
            area=_optional_text(data, "area"),
            venue_type=_enum(VenueType, data.get("venue_type", VenueType.UNKNOWN.value), "venue_type"),
            priority=_priority(data),
            status=_enum(SourceStatus, data.get("status", SourceStatus.NEEDS_VERIFICATION.value), "status"),
            notification_policy=_enum(
                NotificationPolicy,
                data.get("notification_policy", NotificationPolicy.NOTIFY.value),
                "notification_policy",
            ),
            tags=_string_list(data, "tags"),
            schedule=_mapping(data, "schedule"),
            filters=_mapping(data, "filters"),
            metadata=_mapping(data, "metadata"),
        )
        source.validate_type_specific_fields()
        return source

    def validate_type_specific_fields(self) -> None:
        if self.source_type in {SourceType.RSS, SourceType.ARXIV} and not self.feed_url:
            raise ModelError(f"{self.id}: {self.source_type.value} source requires feed_url")
        if self.source_type == SourceType.DBLP and not self.venue_key:
            raise ModelError(f"{self.id}: dblp source requires venue_key")
        if self.source_type == SourceType.OPENREVIEW and not self.openreview_venue_id:
            raise ModelError(f"{self.id}: openreview source requires openreview_venue_id")
        if self.source_type == SourceType.WEBSITE_WATCH:
            if not self.watch_url:
                raise ModelError(f"{self.id}: website_watch source requires watch_url")
            if not self.css_selector:
                raise ModelError(f"{self.id}: website_watch source requires css_selector")
        if self.source_type == SourceType.EMAIL_IMPORT and not self.mailbox_label:
            raise ModelError(f"{self.id}: email_import source requires mailbox_label")


@dataclass(frozen=True)
class SourcesConfig:
    sources: list[Source]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourcesConfig:
        raw_sources = data.get("sources")
        if not isinstance(raw_sources, list):
            raise ModelError("sources must be a list")
        sources = [Source.from_dict(item) for item in raw_sources]
        ids = [source.id for source in sources]
        duplicates = sorted({source_id for source_id in ids if ids.count(source_id) > 1})
        if duplicates:
            raise ModelError(f"duplicate source ids: {', '.join(duplicates)}")
        return cls(sources=sources)


@dataclass(frozen=True)
class Venue:
    canonical_id: str
    short_name: str
    full_name: str
    aliases: list[str]
    venue_type: VenueType
    ccf_level: CcfLevel = CcfLevel.UNKNOWN
    area: str | None = None
    default_priority: int = 3

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Venue:
        if not isinstance(data, dict):
            raise ModelError("venue must be a mapping")
        return cls(
            canonical_id=_required_text(data, "canonical_id"),
            short_name=_required_text(data, "short_name"),
            full_name=_required_text(data, "full_name"),
            aliases=_string_list(data, "aliases"),
            venue_type=_enum(VenueType, data.get("venue_type"), "venue_type"),
            ccf_level=_enum(CcfLevel, data.get("ccf_level", CcfLevel.UNKNOWN.value), "ccf_level"),
            area=_optional_text(data, "area"),
            default_priority=_priority(data, "default_priority", 3),
        )


@dataclass(frozen=True)
class VenuesConfig:
    venues: list[Venue]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VenuesConfig:
        raw_venues = data.get("venues")
        if not isinstance(raw_venues, list):
            raise ModelError("venues must be a list")
        venues = [Venue.from_dict(item) for item in raw_venues]
        ids = [venue.canonical_id for venue in venues]
        duplicates = sorted({venue_id for venue_id in ids if ids.count(venue_id) > 1})
        if duplicates:
            raise ModelError(f"duplicate venue ids: {', '.join(duplicates)}")
        return cls(venues=venues)


@dataclass(frozen=True)
class KeywordsConfig:
    strong_keywords: dict[str, float]
    medium_keywords: dict[str, float]
    negative_keywords: dict[str, float]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeywordsConfig:
        return cls(
            strong_keywords=_number_mapping(data, "strong_keywords"),
            medium_keywords=_number_mapping(data, "medium_keywords"),
            negative_keywords=_number_mapping(data, "negative_keywords"),
        )


def _number_mapping(data: dict[str, Any], key: str) -> dict[str, float]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ModelError(f"{key} must be a mapping")
    result: dict[str, float] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not isinstance(item_value, (int, float)):
            raise ModelError(f"{key} must map strings to numbers")
        result[item_key] = float(item_value)
    return result


@dataclass(frozen=True)
class ScoringConfig:
    base_scores: dict[str, dict[str, float]]
    priority_weight: float
    recommendation_thresholds: dict[Recommendation, float]
    llm_summary: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScoringConfig:
        base_scores = data.get("base_scores")
        if not isinstance(base_scores, dict):
            raise ModelError("base_scores must be a mapping")
        priority_weight = data.get("priority_weight", 0.5)
        if not isinstance(priority_weight, (int, float)):
            raise ModelError("priority_weight must be a number")
        thresholds_raw = data.get("recommendation_thresholds")
        if not isinstance(thresholds_raw, dict):
            raise ModelError("recommendation_thresholds must be a mapping")
        thresholds: dict[Recommendation, float] = {}
        for key, value in thresholds_raw.items():
            if not isinstance(value, (int, float)):
                raise ModelError("recommendation threshold values must be numbers")
            thresholds[_enum(Recommendation, key, "recommendation")] = float(value)
        missing = set(Recommendation).difference(thresholds)
        if missing:
            raise ModelError("missing recommendation thresholds: " + ", ".join(item.value for item in missing))
        llm_summary = data.get("llm_summary", {})
        if not isinstance(llm_summary, dict):
            raise ModelError("llm_summary must be a mapping")
        return cls(
            base_scores=base_scores,
            priority_weight=float(priority_weight),
            recommendation_thresholds=thresholds,
            llm_summary=llm_summary,
        )


@dataclass(frozen=True)
class ReportConfig:
    daily_report: dict[str, Any]
    weekly_report: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReportConfig:
        daily_report = data.get("daily_report")
        weekly_report = data.get("weekly_report")
        if not isinstance(daily_report, dict):
            raise ModelError("daily_report must be a mapping")
        if not isinstance(weekly_report, dict):
            raise ModelError("weekly_report must be a mapping")
        return cls(daily_report=daily_report, weekly_report=weekly_report)


@dataclass(frozen=True)
class NetworkRetrySettings:
    max_attempts: int = 1
    backoff_seconds: float = 0


@dataclass(frozen=True)
class NetworkCacheSettings:
    enabled: bool = True
    dir: Path = Path("state/http_cache")


@dataclass(frozen=True)
class NetworkSettings:
    per_host_delay_seconds: dict[str, float] = field(default_factory=dict)
    retries: NetworkRetrySettings = field(default_factory=NetworkRetrySettings)
    cache: NetworkCacheSettings = field(default_factory=NetworkCacheSettings)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> NetworkSettings:
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ModelError("network must be a mapping")
        raw_delays = data.get("per_host_delay_seconds", {})
        if not isinstance(raw_delays, dict):
            raise ModelError("network.per_host_delay_seconds must be a mapping")
        delays: dict[str, float] = {}
        for host, seconds in raw_delays.items():
            if not isinstance(host, str) or not isinstance(seconds, (int, float)):
                raise ModelError("network.per_host_delay_seconds must map host strings to numbers")
            delays[host] = float(seconds)

        raw_retries = data.get("retries", {})
        if raw_retries is None:
            raw_retries = {}
        if not isinstance(raw_retries, dict):
            raise ModelError("network.retries must be a mapping")
        max_attempts = int(raw_retries.get("max_attempts", 1))
        backoff_seconds = float(raw_retries.get("backoff_seconds", 0))
        if max_attempts < 1:
            raise ModelError("network.retries.max_attempts must be >= 1")
        if backoff_seconds < 0:
            raise ModelError("network.retries.backoff_seconds must be >= 0")

        raw_cache = data.get("cache", {})
        if raw_cache is None:
            raw_cache = {}
        if not isinstance(raw_cache, dict):
            raise ModelError("network.cache must be a mapping")
        return cls(
            per_host_delay_seconds=delays,
            retries=NetworkRetrySettings(max_attempts=max_attempts, backoff_seconds=backoff_seconds),
            cache=NetworkCacheSettings(
                enabled=bool(raw_cache.get("enabled", True)),
                dir=Path(str(raw_cache.get("dir", "state/http_cache"))),
            ),
        )


@dataclass(frozen=True)
class SettingsConfig:
    database_path: Path = Path("data/paper_watcher.sqlite3")
    request_timeout_seconds: float = 20
    request_retries: int = 2
    user_agent: str = "PaperWatcher/0.1"
    reports_dir: Path = Path("reports")
    logs_dir: Path = Path("logs")
    snapshots_dir: Path = Path("data/snapshots")
    state_dir: Path = Path("state")
    network: NetworkSettings = field(default_factory=NetworkSettings)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SettingsConfig:
        database = data.get("database", {})
        runtime = data.get("runtime", {})
        paths = data.get("paths", {})
        network = data.get("network", {})
        if not isinstance(database, dict) or not isinstance(runtime, dict) or not isinstance(paths, dict):
            raise ModelError("settings database, runtime, and paths must be mappings")
        return cls(
            database_path=Path(str(database.get("path", "data/paper_watcher.sqlite3"))),
            request_timeout_seconds=float(runtime.get("request_timeout_seconds", 20)),
            request_retries=int(runtime.get("request_retries", 2)),
            user_agent=str(runtime.get("user_agent", "PaperWatcher/0.1")),
            reports_dir=Path(str(paths.get("reports_dir", "reports"))),
            logs_dir=Path(str(paths.get("logs_dir", "logs"))),
            snapshots_dir=Path(str(paths.get("snapshots_dir", "data/snapshots"))),
            state_dir=Path(str(paths.get("state_dir", "state"))),
            network=NetworkSettings.from_dict(network),
        )


@dataclass(frozen=True)
class RssSubscription:
    source_id: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RssSubscription:
        if not isinstance(data, dict):
            raise ModelError("rss subscription must be a mapping")
        return cls(source_id=_required_text(data, "source_id"))


@dataclass(frozen=True)
class UserSubscriptions:
    rss: list[RssSubscription]
    indexed_venues: list[dict[str, Any]]
    website_watch: list[dict[str, Any]]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserSubscriptions:
        if not isinstance(data, dict):
            raise ModelError("subscriptions must be a mapping")
        raw_rss = data.get("rss", [])
        raw_indexed = data.get("indexed_venues", [])
        raw_web = data.get("website_watch", [])
        if not isinstance(raw_rss, list):
            raise ModelError("subscriptions.rss must be a list")
        if not isinstance(raw_indexed, list):
            raise ModelError("subscriptions.indexed_venues must be a list")
        if not isinstance(raw_web, list):
            raise ModelError("subscriptions.website_watch must be a list")
        return cls(
            rss=[RssSubscription.from_dict(item) for item in raw_rss],
            indexed_venues=raw_indexed,
            website_watch=raw_web,
        )


@dataclass(frozen=True)
class UserDelivery:
    format: str = "text"
    max_items: int = 20

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> UserDelivery:
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ModelError("delivery must be a mapping")
        max_items = data.get("max_items", 20)
        if not isinstance(max_items, int) or max_items < 1:
            raise ModelError("delivery.max_items must be a positive integer")
        return cls(format=str(data.get("format", "text")), max_items=max_items)


@dataclass(frozen=True)
class User:
    id: str
    display_name: str
    subscriptions: UserSubscriptions
    delivery: UserDelivery

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> User:
        if not isinstance(data, dict):
            raise ModelError("user must be a mapping")
        user_id = _required_text(data, "id")
        return cls(
            id=user_id,
            display_name=_optional_text(data, "display_name") or user_id,
            subscriptions=UserSubscriptions.from_dict(data.get("subscriptions", {})),
            delivery=UserDelivery.from_dict(data.get("delivery")),
        )


@dataclass(frozen=True)
class UsersConfig:
    users: list[User]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UsersConfig:
        raw_users = data.get("users")
        if not isinstance(raw_users, list):
            raise ModelError("users must be a list")
        users = [User.from_dict(item) for item in raw_users]
        ids = [user.id for user in users]
        duplicates = sorted({user_id for user_id in ids if ids.count(user_id) > 1})
        if duplicates:
            raise ModelError(f"duplicate user ids: {', '.join(duplicates)}")
        return cls(users=users)


@dataclass(frozen=True)
class AppConfig:
    sources: SourcesConfig
    venues: VenuesConfig
    users: UsersConfig
    keywords: KeywordsConfig
    scoring: ScoringConfig
    report: ReportConfig
    settings: SettingsConfig
    config_dir: Path


@dataclass(frozen=True)
class Paper:
    id: str | None
    title: str
    normalized_title: str
    authors: list[str]
    abstract: str | None
    venue: str | None
    venue_type: VenueType
    ccf_level: CcfLevel
    area: str | None
    source_id: str
    source_url: str | None
    paper_url: str | None
    pdf_url: str | None
    doi: str | None
    arxiv_id: str | None
    dblp_key: str | None
    openreview_id: str | None
    year: int | None
    published_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    score: float = 0.0
    tags: list[str] = field(default_factory=list)
    summary: str | None = None
    recommendation: Recommendation = Recommendation.ARCHIVE
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScanRun:
    id: str
    started_at: datetime
    finished_at: datetime | None
    status: Literal["running", "success", "partial_failure", "failed"]
    source_id: str | None
    fetched_count: int = 0
    new_count: int = 0
    updated_count: int = 0
    error_count: int = 0
    log: str | None = None
