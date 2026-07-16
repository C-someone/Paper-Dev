from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    content: bytes
    headers: dict[str, str]
    url: str
    from_cache: bool = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code} error for {self.url}",
                request=httpx.Request("GET", self.url),
                response=httpx.Response(self.status_code, content=self.content),
            )


class RateLimitedHttpClient:
    _last_request_at_by_host: dict[str, float] = {}

    def __init__(
        self,
        *,
        timeout_seconds: float,
        user_agent: str,
        per_host_delay_seconds: dict[str, float] | None = None,
        max_attempts: int = 1,
        backoff_seconds: float = 0,
        cache_dir: Path | None = None,
        cache_enabled: bool = True,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.per_host_delay_seconds = per_host_delay_seconds or {}
        self.max_attempts = max(1, max_attempts)
        self.backoff_seconds = max(0, backoff_seconds)
        self.cache_dir = cache_dir
        self.cache_enabled = cache_enabled
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn

    def get(self, url: str, *, headers: dict[str, str] | None = None, allow_cached_on_error: bool = True) -> HttpResponse:
        request_headers = {"User-Agent": self.user_agent}
        request_headers.update(headers or {})
        host = urlparse(url).netloc
        last_error: Exception | None = None
        last_response: HttpResponse | None = None

        for attempt in range(1, self.max_attempts + 1):
            self._respect_delay(host)
            try:
                response = httpx.get(
                    url,
                    headers=request_headers,
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                )
                wrapped = HttpResponse(
                    status_code=response.status_code,
                    content=response.content,
                    headers=dict(response.headers),
                    url=str(response.url),
                )
                if response.status_code < 400:
                    if response.status_code != 304:
                        self._write_cache(url, wrapped)
                    return wrapped
                last_response = wrapped
                if response.status_code not in {429, 503}:
                    return wrapped
            except Exception as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    break
            if self.backoff_seconds and attempt < self.max_attempts:
                self.sleep_fn(self.backoff_seconds * attempt)

        cached = self._read_cache(url) if allow_cached_on_error else None
        if cached is not None:
            return cached
        if last_response is not None:
            return last_response
        if last_error:
            raise last_error
        raise RuntimeError(f"request failed: {url}")

    def _respect_delay(self, host: str) -> None:
        delay = self.per_host_delay_seconds.get(host, 0)
        if delay <= 0:
            self._last_request_at_by_host[host] = self.monotonic_fn()
            return
        now = self.monotonic_fn()
        last = self._last_request_at_by_host.get(host)
        if last is not None:
            wait_seconds = delay - (now - last)
            if wait_seconds > 0:
                self.sleep_fn(wait_seconds)
        self._last_request_at_by_host[host] = self.monotonic_fn()

    def _cache_paths(self, url: str) -> tuple[Path, Path] | None:
        if not self.cache_enabled or self.cache_dir is None:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.body", self.cache_dir / f"{digest}.meta.json"

    def _write_cache(self, url: str, response: HttpResponse) -> None:
        paths = self._cache_paths(url)
        if paths is None:
            return
        body_path, meta_path = paths
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(response.content)
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "final_url": response.url,
                    "status_code": response.status_code,
                    "headers": response.headers,
                    "cached_at": datetime.now(UTC).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def _read_cache(self, url: str) -> HttpResponse | None:
        paths = self._cache_paths(url)
        if paths is None:
            return None
        body_path, meta_path = paths
        if not body_path.exists() or not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return HttpResponse(
            status_code=int(meta.get("status_code", 200)),
            content=body_path.read_bytes(),
            headers=dict(meta.get("headers", {})),
            url=str(meta.get("final_url") or url),
            from_cache=True,
        )
