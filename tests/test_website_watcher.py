from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from paper_watcher.background import run_background_once
from paper_watcher.config_loader import load_config
from paper_watcher.fetchers.base import FetchResult
from paper_watcher.fetchers.website_watcher import WebsiteWatcherFetcher
from paper_watcher.http_client import HttpResponse
from paper_watcher.storage.file_storage import FileStateStore
from paper_watcher.verifier import verify_sources


class WebsiteWatcherFetcherTests(unittest.TestCase):
    def test_fetch_extracts_selected_content(self) -> None:
        config = load_config(Path("config"))
        source = next(item for item in config.sources.sources if item.id == "usenix_security_2026_accepted")
        html = b"""
        <html>
          <body>
            <nav>Ignored</nav>
            <main><h1>Accepted Papers</h1><p>Paper A</p></main>
          </body>
        </html>
        """
        fetcher = WebsiteWatcherFetcher(http_client=FakeHttpClient([html]))

        result = fetcher.fetch(source)

        self.assertTrue(result.ok)
        self.assertEqual(result.fetched_count, 1)
        self.assertIsNotNone(result.content_hash)
        self.assertEqual(result.papers[0].paper_url, source.watch_url)
        self.assertIn("Accepted Papers", result.papers[0].raw["excerpt"])
        self.assertNotIn("Ignored", result.papers[0].raw["excerpt"])

    def test_fetch_reports_missing_selector(self) -> None:
        config = load_config(Path("config"))
        source = next(item for item in config.sources.sources if item.id == "usenix_security_2026_accepted")
        fetcher = WebsiteWatcherFetcher(http_client=FakeHttpClient([b"<html><body>No main</body></html>"]))

        result = fetcher.fetch(source)

        self.assertFalse(result.ok)
        self.assertIn("selector did not match", result.error or "")


class WebsiteWatcherBackgroundTests(unittest.TestCase):
    def test_first_scan_baselines_and_second_changed_page_writes_event(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            config = replace(config, settings=replace(config.settings, state_dir=Path(directory_name)))
            fake_fetcher = FakeWebsiteFetcher(
                [
                    FetchResult(source_id="usenix_security_2026_accepted", papers=[], fetched_count=1, content_hash="hash-old"),
                    FetchResult(
                        source_id="usenix_security_2026_accepted",
                        papers=[
                            make_website_paper(
                                config,
                                "website:usenix_security_2026_accepted:hash-new",
                                "USENIX Security 2026 Accepted Papers updated",
                            )
                        ],
                        fetched_count=1,
                        content_hash="hash-new",
                    ),
                ]
            )

            with patch("paper_watcher.background.WebsiteWatcherFetcher", return_value=fake_fetcher):
                first = run_background_once(
                    config,
                    source_id="usenix_security_2026_accepted",
                    include_disabled=True,
                )
                second = run_background_once(
                    config,
                    source_id="usenix_security_2026_accepted",
                    include_disabled=True,
                )

            store = FileStateStore(Path(directory_name))
            events = store.load_events()
            source_state = store.load_source_state()["usenix_security_2026_accepted"]

            self.assertEqual(first, (1, 0, 0))
            self.assertEqual(second, (1, 1, 0))
            self.assertEqual(source_state["content_hash"], "hash-new")
            self.assertEqual(events[0].source_type, "website_watch")
            self.assertEqual(events[0].title, "USENIX Security 2026 Accepted Papers updated")

    def test_verify_supports_website_watch(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            config = replace(config, settings=replace(config.settings, state_dir=Path(directory_name)))
            fake_fetcher = FakeWebsiteFetcher(
                [FetchResult(source_id="usenix_security_2026_accepted", papers=[], fetched_count=1, content_hash="hash")]
            )
            with patch("paper_watcher.verifier.WebsiteWatcherFetcher", return_value=fake_fetcher):
                results = verify_sources(
                    config,
                    source_id="usenix_security_2026_accepted",
                    include_disabled=True,
                )

            self.assertEqual(results[0].status, "ok")
            self.assertEqual(results[0].item_count, 1)


class FakeHttpClient:
    def __init__(self, contents: list[bytes]) -> None:
        self.contents = contents
        self.index = 0

    def get(self, url: str, *, headers=None, allow_cached_on_error=True):
        content = self.contents[min(self.index, len(self.contents) - 1)]
        self.index += 1
        return HttpResponse(status_code=200, content=content, headers={}, url=url)


class FakeWebsiteFetcher:
    def __init__(self, results: list[FetchResult]) -> None:
        self.results = results
        self.index = 0

    def fetch(self, source, state):
        result = self.results[min(self.index, len(self.results) - 1)]
        self.index += 1
        return result


def make_website_paper(config, paper_id: str, title: str):
    source = next(item for item in config.sources.sources if item.id == "usenix_security_2026_accepted")
    html_fetcher = WebsiteWatcherFetcher(http_client=FakeHttpClient([b"<main>Paper B</main>"]))
    result = html_fetcher.fetch(source)
    return replace(result.papers[0], id=paper_id, title=title, normalized_title=title.lower())


if __name__ == "__main__":
    unittest.main()
