from __future__ import annotations

from dataclasses import dataclass, field

from paper_watcher.models import Paper


@dataclass(frozen=True)
class SourceState:
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str | None = None
    cursor: str | None = None


@dataclass(frozen=True)
class FetchResult:
    source_id: str
    papers: list[Paper] = field(default_factory=list)
    fetched_count: int = 0
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str | None = None
    error: str | None = None
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None
