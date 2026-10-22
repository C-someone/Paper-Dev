from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from paper_watcher.fetchers.website_watcher import WebsiteWatcherFetcher
from paper_watcher.models import AppConfig, CcfLevel, Source, SourceStatus, SourceType, VenueType
from paper_watcher.network import build_http_client
from paper_watcher.settings import resolve_project_path
from paper_watcher.storage.file_storage import FileStateStore
from paper_watcher.verifier import classify_error


@dataclass(frozen=True)
class UrlPattern:
    kind: str
    url: str
    confidence: float = 0.5
    css_selector: str | None = None
    paper_selector: str | None = None
    paper_title_selector: str | None = None
    paper_link_selector: str | None = None
    source_id_template: str | None = None
    name_template: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UrlPattern:
        if not isinstance(data, dict):
            raise ValueError("url_patterns entries must be mappings")
        kind = _required_text(data, "kind")
        return cls(
            kind=kind,
            url=_required_text(data, "url"),
            confidence=float(data.get("confidence", 0.5)),
            css_selector=_optional_text(data, "css_selector"),
            paper_selector=_optional_text(data, "paper_selector"),
            paper_title_selector=_optional_text(data, "paper_title_selector"),
            paper_link_selector=_optional_text(data, "paper_link_selector"),
            source_id_template=_optional_text(data, "source_id_template"),
            name_template=_optional_text(data, "name_template"),
        )


@dataclass(frozen=True)
class VenueProfile:
    venue_id: str
    short_name: str
    full_name: str
    aliases: list[str]
    official_domains: list[str]
    dblp_venue_keys: list[str]
    ccf_level: str
    area: str | None
    venue_type: str
    priority: int
    default_css_selector: str
    default_schedule_interval_seconds: int
    default_metadata: dict[str, Any]
    tags: list[str]
    url_patterns: list[UrlPattern]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VenueProfile:
        if not isinstance(data, dict):
            raise ValueError("venue profile must be a mapping")
        raw_patterns = data.get("url_patterns", [])
        if not isinstance(raw_patterns, list):
            raise ValueError("url_patterns must be a list")
        return cls(
            venue_id=_required_text(data, "venue_id"),
            short_name=_required_text(data, "short_name"),
            full_name=_required_text(data, "full_name"),
            aliases=_string_list(data, "aliases"),
            official_domains=_string_list(data, "official_domains"),
            dblp_venue_keys=_string_list(data, "dblp_venue_keys"),
            ccf_level=str(data.get("ccf_level", "unknown")),
            area=_optional_text(data, "area"),
            venue_type=str(data.get("venue_type", "conference")),
            priority=int(data.get("priority", 3)),
            default_css_selector=str(data.get("default_css_selector", "main")),
            default_schedule_interval_seconds=int(data.get("default_schedule_interval_seconds", 86400)),
            default_metadata=_mapping(data, "default_metadata"),
            tags=_string_list(data, "tags"),
            url_patterns=[UrlPattern.from_dict(item) for item in raw_patterns],
        )


@dataclass(frozen=True)
class SourceCandidate:
    candidate_id: str
    venue_id: str
    year: int
    kind: str
    url: str
    source_id: str
    source_name: str
    css_selector: str
    ccf_level: str
    area: str | None
    venue_type: str
    priority: int
    confidence: float
    reason: str
    probe_status: str
    status: str
    first_seen_at: str
    last_checked_at: str
    error: str | None = None
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = None
    approved_at: str | None = None
    rejected_at: str | None = None
    note: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceCandidate:
        return cls(
            candidate_id=str(data["candidate_id"]),
            venue_id=str(data["venue_id"]),
            year=int(data["year"]),
            kind=str(data["kind"]),
            url=str(data["url"]),
            source_id=str(data["source_id"]),
            source_name=str(data["source_name"]),
            css_selector=str(data["css_selector"]),
            ccf_level=str(data["ccf_level"]),
            area=data.get("area") if isinstance(data.get("area"), str) else None,
            venue_type=str(data["venue_type"]),
            priority=int(data["priority"]),
            confidence=float(data["confidence"]),
            reason=str(data["reason"]),
            probe_status=str(data["probe_status"]),
            status=str(data["status"]),
            first_seen_at=str(data["first_seen_at"]),
            last_checked_at=str(data["last_checked_at"]),
            error=data.get("error") if isinstance(data.get("error"), str) else None,
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            tags=data.get("tags") if isinstance(data.get("tags"), list) else [],
            approved_at=data.get("approved_at") if isinstance(data.get("approved_at"), str) else None,
            rejected_at=data.get("rejected_at") if isinstance(data.get("rejected_at"), str) else None,
            note=data.get("note") if isinstance(data.get("note"), str) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiscoveryResult:
    candidates: list[SourceCandidate]
    response_text: str


@dataclass(frozen=True)
class CandidateActionResult:
    candidate: SourceCandidate
    response_text: str


def load_venue_profiles(config_dir: Path) -> list[VenueProfile]:
    path = config_dir / "venue_profiles.yaml"
    if not path.exists():
        raise ValueError(f"missing venue profile config: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"venue profile config must be a mapping: {path}")
    raw_profiles = data.get("venue_profiles", [])
    if not isinstance(raw_profiles, list):
        raise ValueError("venue_profiles must be a list")
    profiles = [VenueProfile.from_dict(item) for item in raw_profiles]
    ids = [profile.venue_id for profile in profiles]
    duplicates = sorted({profile_id for profile_id in ids if ids.count(profile_id) > 1})
    if duplicates:
        raise ValueError("duplicate venue profile ids: " + ", ".join(duplicates))
    return profiles


def discover_conferences(
    config: AppConfig,
    *,
    venue_id: str | None = None,
    year: int | None = None,
    include_existing: bool = False,
    output_format: str = "text",
) -> DiscoveryResult:
    profiles = _filter_profiles(load_venue_profiles(config.config_dir), venue_id)
    target_year = year or datetime.now(UTC).year
    existing_urls = {source.watch_url for source in config.sources.sources if source.watch_url}
    store = SourceCandidateStore(FileStateStore(resolve_project_path(config, config.settings.state_dir)))
    http_client = build_http_client(config)
    fetcher = WebsiteWatcherFetcher(
        timeout_seconds=config.settings.request_timeout_seconds,
        user_agent=config.settings.user_agent,
        http_client=http_client,
        allow_cached_on_error=True,
    )
    candidates: list[SourceCandidate] = []

    for profile in profiles:
        for pattern in profile.url_patterns:
            candidate = _build_candidate(profile, pattern, target_year)
            if candidate.url in existing_urls and not include_existing:
                continue
            probed = _probe_candidate(fetcher, candidate)
            candidates.append(probed)

    store.upsert_candidates(candidates)
    return DiscoveryResult(
        candidates=candidates,
        response_text=render_candidates(candidates, output_format=output_format),
    )


def list_candidates(
    config: AppConfig,
    *,
    status: str | None = None,
    venue_id: str | None = None,
    output_format: str = "text",
) -> DiscoveryResult:
    store = SourceCandidateStore(FileStateStore(resolve_project_path(config, config.settings.state_dir)))
    candidates = store.load_candidates()
    if status:
        candidates = [candidate for candidate in candidates if candidate.status == status]
    if venue_id:
        candidates = [candidate for candidate in candidates if candidate.venue_id == venue_id]
    candidates.sort(key=lambda item: (item.last_checked_at, item.confidence), reverse=True)
    return DiscoveryResult(
        candidates=candidates,
        response_text=render_candidates(candidates, output_format=output_format),
    )


def approve_candidate(
    config: AppConfig,
    *,
    candidate_id: str,
    dry_run: bool = False,
) -> CandidateActionResult:
    store = SourceCandidateStore(FileStateStore(resolve_project_path(config, config.settings.state_dir)))
    candidate = store.get_candidate(candidate_id)
    if candidate is None:
        raise ValueError(f"candidate not found: {candidate_id}")
    if candidate.status == "rejected":
        raise ValueError(f"candidate is rejected: {candidate_id}")

    if dry_run:
        return CandidateActionResult(
            candidate=candidate,
            response_text=_candidate_source_yaml_preview(candidate),
        )

    _append_candidate_to_config(config.config_dir, candidate)
    updated = store.update_status(candidate_id, "approved", note="approved into config/sources.yaml")
    return CandidateActionResult(
        candidate=updated,
        response_text=f"Approved candidate {candidate_id} as source {candidate.source_id}.",
    )


def reject_candidate(config: AppConfig, *, candidate_id: str, reason: str | None = None) -> CandidateActionResult:
    store = SourceCandidateStore(FileStateStore(resolve_project_path(config, config.settings.state_dir)))
    candidate = store.get_candidate(candidate_id)
    if candidate is None:
        raise ValueError(f"candidate not found: {candidate_id}")
    updated = store.update_status(candidate_id, "rejected", note=reason)
    return CandidateActionResult(candidate=updated, response_text=f"Rejected candidate {candidate_id}.")


def render_candidates(candidates: list[SourceCandidate], *, output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(
            {"count": len(candidates), "candidates": [candidate.to_dict() for candidate in candidates]},
            ensure_ascii=False,
            indent=2,
        )
    if output_format != "text":
        raise ValueError(f"unsupported output format: {output_format}")
    if not candidates:
        return "No conference source candidates found."
    lines = ["Conference source candidates:", ""]
    for candidate in candidates:
        lines.append(
            f"- {candidate.candidate_id} [{candidate.status}] "
            f"{candidate.venue_id} {candidate.year} {candidate.kind}"
        )
        lines.append(
            f"  source_id={candidate.source_id} probe={candidate.probe_status} "
            f"confidence={candidate.confidence:.2f}"
        )
        lines.append(f"  url={candidate.url}")
        if candidate.error:
            lines.append(f"  error={candidate.error}")
    return "\n".join(lines)


class SourceCandidateStore:
    def __init__(self, file_store: FileStateStore) -> None:
        self.file_store = file_store

    def load_candidates(self) -> list[SourceCandidate]:
        return [SourceCandidate.from_dict(item) for item in self.file_store.load_source_candidates()]

    def save_candidates(self, candidates: list[SourceCandidate]) -> None:
        candidates = sorted(candidates, key=lambda item: (item.venue_id, item.year, item.kind, item.url))
        self.file_store.save_source_candidates([candidate.to_dict() for candidate in candidates])

    def upsert_candidates(self, candidates: list[SourceCandidate]) -> None:
        existing = {candidate.candidate_id: candidate for candidate in self.load_candidates()}
        for candidate in candidates:
            previous = existing.get(candidate.candidate_id)
            if previous is not None:
                candidate = replace(
                    candidate,
                    status=previous.status,
                    first_seen_at=previous.first_seen_at,
                    approved_at=previous.approved_at,
                    rejected_at=previous.rejected_at,
                    note=previous.note,
                )
            existing[candidate.candidate_id] = candidate
        self.save_candidates(list(existing.values()))

    def get_candidate(self, candidate_id: str) -> SourceCandidate | None:
        for candidate in self.load_candidates():
            if candidate.candidate_id == candidate_id:
                return candidate
        return None

    def update_status(self, candidate_id: str, status: str, note: str | None = None) -> SourceCandidate:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"unsupported candidate status: {status}")
        now = _iso_now()
        candidates = self.load_candidates()
        updated: SourceCandidate | None = None
        result: list[SourceCandidate] = []
        for candidate in candidates:
            if candidate.candidate_id == candidate_id:
                candidate = replace(
                    candidate,
                    status=status,
                    approved_at=now if status == "approved" else candidate.approved_at,
                    rejected_at=now if status == "rejected" else candidate.rejected_at,
                    note=note,
                )
                updated = candidate
            result.append(candidate)
        if updated is None:
            raise ValueError(f"candidate not found: {candidate_id}")
        self.save_candidates(result)
        return updated


def _build_candidate(profile: VenueProfile, pattern: UrlPattern, year: int) -> SourceCandidate:
    values = {"year": year, "yy": str(year)[-2:], "venue_id": profile.venue_id, "kind": pattern.kind}
    url = pattern.url.format(**values)
    source_id_template = pattern.source_id_template or "{venue_id}_{year}_{kind}"
    source_id = _slug(source_id_template.format(**values))
    source_name_template = pattern.name_template or "{short_name} {year} {kind}"
    source_name = source_name_template.format(
        short_name=profile.short_name,
        full_name=profile.full_name,
        year=year,
        kind=pattern.kind.replace("_", " ").title(),
    )
    metadata = dict(profile.default_metadata)
    _copy_if_set(metadata, "paper_selector", pattern.paper_selector)
    _copy_if_set(metadata, "paper_title_selector", pattern.paper_title_selector)
    _copy_if_set(metadata, "paper_link_selector", pattern.paper_link_selector)
    now = _iso_now()
    reason = _candidate_reason(profile, url)
    candidate_id = "cand_" + hashlib.sha256(f"{profile.venue_id}|{year}|{pattern.kind}|{url}".encode()).hexdigest()[:16]
    return SourceCandidate(
        candidate_id=candidate_id,
        venue_id=profile.venue_id,
        year=year,
        kind=pattern.kind,
        url=url,
        source_id=source_id,
        source_name=source_name,
        css_selector=pattern.css_selector or profile.default_css_selector,
        ccf_level=profile.ccf_level,
        area=profile.area,
        venue_type=profile.venue_type,
        priority=profile.priority,
        confidence=float(pattern.confidence),
        reason=reason,
        probe_status="unprobed",
        status="pending",
        first_seen_at=now,
        last_checked_at=now,
        metadata=metadata,
        tags=sorted(set(profile.tags + [profile.venue_id, pattern.kind])),
    )


def _probe_candidate(fetcher: WebsiteWatcherFetcher, candidate: SourceCandidate) -> SourceCandidate:
    checked_at = _iso_now()
    source = Source(
        id=candidate.source_id,
        name=candidate.source_name,
        source_type=SourceType.WEBSITE_WATCH,
        enabled=True,
        watch_url=candidate.url,
        css_selector=candidate.css_selector,
        ccf_level=CcfLevel(candidate.ccf_level),
        area=candidate.area,
        venue_type=VenueType(candidate.venue_type),
        priority=candidate.priority,
        status=SourceStatus.NEEDS_VERIFICATION,
        tags=list(candidate.tags or []),
        metadata=dict(candidate.metadata or {}),
    )
    result = fetcher.fetch(source)
    if result.ok:
        return replace(
            candidate,
            probe_status="ok",
            confidence=min(1.0, max(candidate.confidence, 0.8)),
            last_checked_at=checked_at,
            error=None,
        )
    status = classify_error(result.error or "")
    return replace(
        candidate,
        probe_status=status,
        confidence=max(0.0, candidate.confidence - 0.25),
        last_checked_at=checked_at,
        error=result.error,
    )


def _append_candidate_to_config(config_dir: Path, candidate: SourceCandidate) -> None:
    sources_path = config_dir / "sources.yaml"
    users_path = config_dir / "users.yaml"
    sources_data = _read_yaml_mapping(sources_path)
    users_data = _read_yaml_mapping(users_path)
    sources = sources_data.setdefault("sources", [])
    if not isinstance(sources, list):
        raise ValueError("sources.yaml sources must be a list")
    source_ids = {item.get("id") for item in sources if isinstance(item, dict)}
    if candidate.source_id not in source_ids:
        sources.append(_candidate_to_source_config(candidate))
        _write_yaml_mapping(sources_path, sources_data)

    users = users_data.setdefault("users", [])
    if not isinstance(users, list):
        raise ValueError("users.yaml users must be a list")
    root = next((item for item in users if isinstance(item, dict) and item.get("id") == "root"), None)
    if root is not None:
        subscriptions = root.setdefault("subscriptions", {})
        if not isinstance(subscriptions, dict):
            raise ValueError("root subscriptions must be a mapping")
        website_watch = subscriptions.setdefault("website_watch", [])
        if not isinstance(website_watch, list):
            raise ValueError("root website_watch subscriptions must be a list")
        if not any(isinstance(item, dict) and item.get("source_id") == candidate.source_id for item in website_watch):
            website_watch.append({"source_id": candidate.source_id})
            _write_yaml_mapping(users_path, users_data)


def _candidate_to_source_config(candidate: SourceCandidate) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": candidate.source_id,
        "name": candidate.source_name,
        "source_type": "website_watch",
        "enabled": True,
        "watch_url": candidate.url,
        "css_selector": candidate.css_selector,
        "ccf_level": candidate.ccf_level,
        "area": candidate.area,
        "venue_type": candidate.venue_type,
        "priority": candidate.priority,
        "status": "needs_verification",
        "schedule": {"interval_seconds": 86400},
        "metadata": candidate.metadata or {},
        "tags": candidate.tags or [],
    }
    return {key: value for key, value in data.items() if value not in (None, {}, [])}


def _candidate_source_yaml_preview(candidate: SourceCandidate) -> str:
    return yaml.safe_dump(_candidate_to_source_config(candidate), allow_unicode=True, sort_keys=False)


def _filter_profiles(profiles: list[VenueProfile], venue_id: str | None) -> list[VenueProfile]:
    if venue_id is None:
        return profiles
    result = [profile for profile in profiles if profile.venue_id == venue_id]
    if not result:
        raise ValueError(f"venue profile not found: {venue_id}")
    return result


def _candidate_reason(profile: VenueProfile, url: str) -> str:
    host = urlparse(url).netloc.lower()
    if any(host == domain or host.endswith("." + domain) for domain in profile.official_domains):
        return "matched official domain and configured URL pattern"
    return "matched configured URL pattern"


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return data


def _write_yaml_mapping(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _required_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _optional_text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value.strip() or None


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return value


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping")
    return value


def _copy_if_set(target: dict[str, Any], key: str, value: str | None) -> None:
    if value:
        target[key] = value


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()
