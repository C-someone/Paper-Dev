from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from paper_watcher.http_client import RateLimitedHttpClient


class RateLimitedHttpClientTests(unittest.TestCase):
    def setUp(self) -> None:
        RateLimitedHttpClient._last_request_at_by_host.clear()

    def test_writes_successful_response_to_cache_and_uses_cache_on_retryable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            client = RateLimitedHttpClient(
                timeout_seconds=5,
                user_agent="PaperWatcherTest/0.1",
                max_attempts=2,
                backoff_seconds=0,
                cache_dir=Path(directory_name),
                cache_enabled=True,
            )
            url = "https://example.com/feed.xml"

            with patch(
                "paper_watcher.http_client.httpx.get",
                return_value=httpx.Response(200, content=b"<rss />", request=httpx.Request("GET", url)),
            ):
                first = client.get(url)

            self.assertFalse(first.from_cache)
            self.assertEqual(first.content, b"<rss />")

            with patch(
                "paper_watcher.http_client.httpx.get",
                return_value=httpx.Response(503, content=b"busy", request=httpx.Request("GET", url)),
            ):
                second = client.get(url)

            self.assertTrue(second.from_cache)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.content, b"<rss />")

    def test_does_not_overwrite_cache_with_304(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            client = RateLimitedHttpClient(
                timeout_seconds=5,
                user_agent="PaperWatcherTest/0.1",
                cache_dir=Path(directory_name),
                cache_enabled=True,
            )
            url = "https://example.com/feed.xml"

            with patch(
                "paper_watcher.http_client.httpx.get",
                return_value=httpx.Response(200, content=b"cached body", request=httpx.Request("GET", url)),
            ):
                client.get(url)

            with patch(
                "paper_watcher.http_client.httpx.get",
                return_value=httpx.Response(304, content=b"", request=httpx.Request("GET", url)),
            ):
                response = client.get(url)

            self.assertEqual(response.status_code, 304)

            with patch(
                "paper_watcher.http_client.httpx.get",
                return_value=httpx.Response(503, content=b"busy", request=httpx.Request("GET", url)),
            ):
                cached = client.get(url)

            self.assertTrue(cached.from_cache)
            self.assertEqual(cached.content, b"cached body")

    def test_retries_429_and_applies_backoff(self) -> None:
        sleeps: list[float] = []
        url = "https://example.com/feed.xml"
        responses = [
            httpx.Response(429, content=b"slow down", request=httpx.Request("GET", url)),
            httpx.Response(200, content=b"ok", request=httpx.Request("GET", url)),
        ]
        client = RateLimitedHttpClient(
            timeout_seconds=5,
            user_agent="PaperWatcherTest/0.1",
            max_attempts=2,
            backoff_seconds=3,
            cache_enabled=False,
            sleep_fn=sleeps.append,
        )

        with patch("paper_watcher.http_client.httpx.get", side_effect=responses) as get_mock:
            response = client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(get_mock.call_count, 2)
        self.assertEqual(sleeps, [3])

    def test_applies_per_host_delay(self) -> None:
        sleeps: list[float] = []
        ticks = iter([10.0, 10.0, 12.0, 12.0])
        url = "https://dblp.org/db/conf/ccs/index.xml"
        client = RateLimitedHttpClient(
            timeout_seconds=5,
            user_agent="PaperWatcherTest/0.1",
            per_host_delay_seconds={"dblp.org": 5},
            cache_enabled=False,
            sleep_fn=sleeps.append,
            monotonic_fn=lambda: next(ticks),
        )

        with patch(
            "paper_watcher.http_client.httpx.get",
            return_value=httpx.Response(200, content=b"ok", request=httpx.Request("GET", url)),
        ):
            client.get(url)
            client.get(url)

        self.assertEqual(sleeps, [3.0])


if __name__ == "__main__":
    unittest.main()
