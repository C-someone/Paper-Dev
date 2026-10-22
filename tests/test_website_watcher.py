from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from paper_watcher.agent_review.conference_page_review import ConferencePageReviewResult
from paper_watcher.background import run_background_once
from paper_watcher.config_loader import load_config
from paper_watcher.fetchers.base import FetchResult
from paper_watcher.fetchers.website_watcher import WebsiteWatcherFetcher
from paper_watcher.http_client import HttpResponse
from paper_watcher.models import VenueType
from paper_watcher.storage.file_storage import FileStateStore
from paper_watcher.verifier import verify_sources


class WebsiteWatcherFetcherTests(unittest.TestCase):
    def test_fetch_extracts_conference_list_group_items(self) -> None:
        config = load_config(Path("config"))
        source = next(item for item in config.sources.sources if item.id == "ieee_sp_2026_accepted")
        html = b"""
        <html>
          <body>
            <div class="navbar">Ignored</div>
            <div class="container">
              <h1>Accepted Papers</h1>
              <div class="list-group-item">
                <b><a href="#collapse-0">Paper A</a></b>
                <div class="collapse authorlist" id="collapse-0">Alice<br/>University A</div>
              </div>
              <div class="list-group-item">
                <b><a href="#collapse-1">Paper B</a></b>
                <div class="collapse authorlist" id="collapse-1">Bob<br/>University B</div>
              </div>
            </div>
          </body>
        </html>
        """
        fetcher = WebsiteWatcherFetcher(http_client=FakeHttpClient([html]))

        result = fetcher.fetch(source)

        self.assertTrue(result.ok)
        self.assertEqual(result.fetched_count, 3)
        self.assertIsNotNone(result.content_hash)
        self.assertEqual(result.papers[0].paper_url, source.watch_url)
        self.assertIn("Accepted Papers", result.papers[0].raw["excerpt"])
        self.assertNotIn("Ignored", result.papers[0].raw["excerpt"])
        self.assertEqual([paper.title for paper in result.papers[1:]], ["Paper A", "Paper B"])
        self.assertEqual(result.papers[1].raw["conference_page_layout"], "bootstrap_list_group")
        self.assertEqual(result.papers[1].raw["conference_page_authors_text"], "Alice")

    def test_fetch_extracts_conference_table_rows(self) -> None:
        config = load_config(Path("config"))
        source = next(item for item in config.sources.sources if item.id == "sigcomm_2026_accepted")
        html = b"""
        <html>
          <body>
            <div class="main-container">
              <div class="main-content">
                <table>
                  <tr><th>Title / Authors</th></tr>
                  <tr>
                    <td>
                      <b>Paper A: Security</b><br/>
                      <span class="table-description">Alice, Bob</span>
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <b>Paper B: Networks</b><br/>
                      <span class="table-description">Carol</span>
                    </td>
                  </tr>
                </table>
              </div>
            </div>
          </body>
        </html>
        """
        fetcher = WebsiteWatcherFetcher(http_client=FakeHttpClient([html]))

        result = fetcher.fetch(source)

        self.assertTrue(result.ok)
        self.assertEqual(result.fetched_count, 3)
        self.assertEqual([paper.title for paper in result.papers[1:]], ["Paper A: Security", "Paper B: Networks"])
        self.assertEqual(result.papers[1].paper_url, source.watch_url)
        self.assertEqual(result.papers[1].raw["website_watch_item"], True)
        self.assertEqual(result.papers[1].raw["conference_page_layout"], "table_rows")
        self.assertEqual(result.papers[1].raw["conference_page_authors_text"], "Alice, Bob")

    def test_fetch_reports_missing_selector(self) -> None:
        config = load_config(Path("config"))
        source = replace(
            next(item for item in config.sources.sources if item.id == "usenix_security_2026_accepted"),
            venue_type=VenueType.UNKNOWN,
        )
        fetcher = WebsiteWatcherFetcher(http_client=FakeHttpClient([b"<html><body>No main</body></html>"]))

        result = fetcher.fetch(source)

        self.assertFalse(result.ok)
        self.assertIn("selector did not match", result.error or "")

    def test_fetch_uses_supervisor_for_known_layout_when_enabled(self) -> None:
        config = load_config(Path("config"))
        source = next(item for item in config.sources.sources if item.id == "ieee_sp_2026_accepted")
        html = b"""
        <html>
          <body>
            <div class="container">
              <div class="list-group-item">
                <b><a href="#collapse-0">Paper A</a></b>
                <div class="collapse authorlist" id="collapse-0">Alice</div>
              </div>
              <div class="list-group-item">
                <b><a href="#collapse-1">Paper B</a></b>
                <div class="collapse authorlist" id="collapse-1">Bob</div>
              </div>
            </div>
          </body>
        </html>
        """
        review = make_page_review(
            decision="accept",
            mode="matched_layout",
            reason="layout looks valid",
            evidence=["paper-like titles"],
        )
        fetcher = WebsiteWatcherFetcher(
            http_client=FakeHttpClient([html]),
            conference_page_review_enabled=True,
        )

        with patch("paper_watcher.agent_review.conference_page_review.review_conference_page", return_value=review):
            result = fetcher.fetch(source)

        self.assertTrue(result.ok)
        self.assertEqual(result.fetched_count, 3)
        self.assertEqual([paper.title for paper in result.papers[1:]], ["Paper A", "Paper B"])
        self.assertEqual(result.papers[0].raw["conference_page_supervisor"]["analysis_mode"], "matched_layout")
        self.assertEqual(result.papers[0].raw["conference_page_supervisor"]["review"]["decision"], "accept")

    def test_fetch_uses_supervisor_snapshot_only_when_unknown_layout_stays_unclear(self) -> None:
        config = load_config(Path("config"))
        source = next(item for item in config.sources.sources if item.id == "ieee_sp_2026_accepted")
        html = b"""
        <html>
          <body>
            <main>
              <div class="mystery-panel">
                <span>Just a homepage block</span>
              </div>
            </main>
          </body>
        </html>
        """
        review = make_page_review(
            decision="snapshot_only",
            mode="unknown_layout",
            reason="cannot infer a paper layout",
            evidence=["no useful structure"],
        )
        fetcher = WebsiteWatcherFetcher(
            http_client=FakeHttpClient([html]),
            conference_page_review_enabled=True,
        )

        with patch("paper_watcher.agent_review.conference_page_review.review_conference_page", return_value=review):
            result = fetcher.fetch(source)

        self.assertTrue(result.ok)
        self.assertEqual(result.fetched_count, 1)
        self.assertEqual(len(result.papers), 1)
        self.assertEqual(result.papers[0].raw["conference_page_supervisor"]["review"]["decision"], "snapshot_only")

    def test_fetch_uses_supervisor_retry_for_new_layout(self) -> None:
        config = load_config(Path("config"))
        source = next(item for item in config.sources.sources if item.id == "ieee_sp_2026_accepted")
        html = b"""
        <html>
          <body>
            <main>
              <section class="paper-card">
                <h3><a href="/papers/a">Paper A</a></h3>
              </section>
              <section class="paper-card">
                <h3><a href="/papers/b">Paper B</a></h3>
              </section>
            </main>
          </body>
        </html>
        """
        review = make_page_review(
            decision="suggest_new_layout",
            mode="unknown_layout",
            reason="paper cards are visible",
            evidence=["paper-card blocks"],
            paper_selector="section.paper-card",
            paper_title_selector="h3 a",
            paper_link_selector="a",
            conference_page_mode="explicit",
        )
        fetcher = WebsiteWatcherFetcher(
            http_client=FakeHttpClient([html]),
            conference_page_review_enabled=True,
        )

        with patch("paper_watcher.agent_review.conference_page_review.review_conference_page", return_value=review):
            result = fetcher.fetch(source)

        self.assertTrue(result.ok)
        self.assertEqual(result.fetched_count, 3)
        self.assertEqual([paper.title for paper in result.papers[1:]], ["Paper A", "Paper B"])
        self.assertEqual(result.papers[1].raw["conference_page_layout"], "explicit")
        self.assertEqual(result.papers[0].raw["conference_page_supervisor"]["review"]["decision"], "suggest_new_layout")


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
            self.assertEqual(events[0].raw["content_hash"], result_content_hash(config))
            self.assertIn("excerpt", events[0].raw)

    def test_website_watch_baselines_existing_titles_and_emits_new_titles(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            config = replace(config, settings=replace(config.settings, state_dir=Path(directory_name)))
            source = next(item for item in config.sources.sources if item.id == "usenix_security_2026_accepted")
            first = WebsiteWatcherFetcher(
                http_client=FakeHttpClient(
                    [
                        b"""
                        <main>
                          <h1>Accepted Papers</h1>
                          <ul><li><a href="/paper-a">Paper A</a></li></ul>
                        </main>
                        """
                    ]
                )
            ).fetch(source)
            second = WebsiteWatcherFetcher(
                http_client=FakeHttpClient(
                    [
                        b"""
                        <main>
                          <h1>Accepted Papers</h1>
                          <ul>
                            <li><a href="/paper-a">Paper A</a></li>
                            <li><a href="/paper-b">Paper B</a></li>
                          </ul>
                        </main>
                        """
                    ]
                )
            ).fetch(source)
            fake_fetcher = FakeWebsiteFetcher([first, second])

            with patch("paper_watcher.background.WebsiteWatcherFetcher", return_value=fake_fetcher):
                run_background_once(
                    config,
                    source_id="usenix_security_2026_accepted",
                    include_disabled=True,
                )
                run_background_once(
                    config,
                    source_id="usenix_security_2026_accepted",
                    include_disabled=True,
                )

            events = FileStateStore(Path(directory_name)).load_events()

            self.assertEqual([event.title for event in events], ["USENIX Security 2026 Cycle 1 Accepted Papers updated", "Paper B"])
            self.assertEqual(events[1].raw["website_watch_item"], True)
            self.assertEqual(events[1].link, "https://www.usenix.org/paper-b")

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


def result_content_hash(config) -> str:
    source = next(item for item in config.sources.sources if item.id == "usenix_security_2026_accepted")
    result = WebsiteWatcherFetcher(http_client=FakeHttpClient([b"<main>Paper B</main>"])).fetch(source)
    return result.content_hash or ""


def make_page_review(
    *,
    decision: str,
    mode: str,
    reason: str,
    evidence: list[str],
    suggested_layout_name: str | None = None,
    conference_page_mode: str | None = None,
    conference_content_selector: str | None = None,
    paper_selector: str | None = None,
    paper_title_selector: str | None = None,
    paper_link_selector: str | None = None,
    paper_author_selector: str | None = None,
    conference_author_selector: str | None = None,
) -> ConferencePageReviewResult:
    return ConferencePageReviewResult(
        review_id="page_review_test",
        reviewed_at="2026-01-01T00:00:00+00:00",
        reviewer="rule_based",
        mode=mode,  # type: ignore[arg-type]
        decision=decision,  # type: ignore[arg-type]
        confidence=0.9,
        reason=reason,
        evidence=evidence,
        suggested_layout_name=suggested_layout_name,
        conference_page_mode=conference_page_mode,
        conference_content_selector=conference_content_selector,
        paper_selector=paper_selector,
        paper_title_selector=paper_title_selector,
        paper_link_selector=paper_link_selector,
        paper_author_selector=paper_author_selector,
        conference_author_selector=conference_author_selector,
    )


if __name__ == "__main__":
    unittest.main()
