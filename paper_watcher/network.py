from __future__ import annotations

from paper_watcher.http_client import RateLimitedHttpClient
from paper_watcher.models import AppConfig
from paper_watcher.settings import resolve_project_path


def build_http_client(config: AppConfig) -> RateLimitedHttpClient:
    network = config.settings.network
    cache_dir = resolve_project_path(config, network.cache.dir)
    return RateLimitedHttpClient(
        timeout_seconds=config.settings.request_timeout_seconds,
        user_agent=config.settings.user_agent,
        per_host_delay_seconds=network.per_host_delay_seconds,
        max_attempts=network.retries.max_attempts,
        backoff_seconds=network.retries.backoff_seconds,
        cache_dir=cache_dir,
        cache_enabled=network.cache.enabled,
    )
