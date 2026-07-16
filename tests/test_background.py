from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from paper_watcher.background import run_background_once
from paper_watcher.config_loader import load_config
from paper_watcher.fetchers.base import FetchResult
from paper_watcher.models import (
    CcfLevel,
    NotificationPolicy,
    Paper,
    Recommendation,
    RssSubscription,
    User,
    UserDelivery,
    UserSubscriptions,
    UsersConfig,
    VenueType,
)
from paper_watcher.storage.file_storage import FileStateStore


class BackgroundTests(unittest.TestCase):
    def test_first_rss_scan_sets_baseline_without_events(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            config = debug_only_config(config, Path(directory_name))
            fake_fetcher = FakeRSSFetcher(
                [
                    [make_paper("paper_1", "Existing Paper")],
                    [make_paper("paper_1", "Existing Paper"), make_paper("paper_2", "New Paper")],
                ]
            )

            with patch("paper_watcher.background.RSSFetcher", return_value=fake_fetcher):
                first = run_background_once(
                    config,
                    source_id="debug_fake_rss",
                    include_disabled=True,
                )
                second = run_background_once(
                    config,
                    source_id="debug_fake_rss",
                    include_disabled=True,
                )

            store = FileStateStore(Path(directory_name))
            events = store.load_events()
            source_state = store.load_source_state()["debug_fake_rss"]

            self.assertEqual(first, (1, 0, 0))
            self.assertEqual(second, (1, 1, 0))
            self.assertEqual([event.title for event in events], ["New Paper"])
            self.assertIn("paper_1", source_state["known_paper_ids"])
            self.assertIn("paper_2", source_state["known_paper_ids"])

    def test_record_only_source_records_without_matched_users(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            config = debug_only_config(config, Path(directory_name))
            sources = []
            for source in config.sources.sources:
                if source.id == "debug_fake_rss":
                    sources.append(replace(source, notification_policy=NotificationPolicy.RECORD_ONLY))
                else:
                    sources.append(source)
            config = replace(config, sources=replace(config.sources, sources=sources))
            fake_fetcher = FakeRSSFetcher(
                [
                    [make_paper("paper_1", "Existing Paper")],
                    [make_paper("paper_1", "Existing Paper"), make_paper("paper_2", "Record Only Paper")],
                ]
            )

            with patch("paper_watcher.background.RSSFetcher", return_value=fake_fetcher):
                run_background_once(config, source_id="debug_fake_rss", include_disabled=True)
                run_background_once(config, source_id="debug_fake_rss", include_disabled=True)

            events = FileStateStore(Path(directory_name)).load_events()

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].title, "Record Only Paper")
            self.assertEqual(events[0].matched_users, [])

    def test_respect_schedule_skips_source_until_next_scan_time(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            config = debug_only_config(config, Path(directory_name))
            store = FileStateStore(Path(directory_name))
            store.save_source_state(
                {
                    "debug_fake_rss": {
                        "initialized_at": "2026-07-15T00:00:00+00:00",
                        "next_scan_after": "2999-01-01T00:00:00+00:00",
                        "known_paper_ids": [],
                    }
                }
            )
            fake_fetcher = FakeRSSFetcher([[make_paper("paper_1", "Skipped Paper")]])

            with patch("paper_watcher.background.RSSFetcher", return_value=fake_fetcher):
                skipped = run_background_once(
                    config,
                    include_disabled=True,
                    respect_schedule=True,
                )
                forced = run_background_once(
                    config,
                    source_id="debug_fake_rss",
                    include_disabled=True,
                    respect_schedule=True,
                )

            self.assertEqual(skipped, (0, 0, 0))
            self.assertEqual(forced, (1, 1, 0))
            source_state = FileStateStore(Path(directory_name)).load_source_state()["debug_fake_rss"]
            self.assertIn("last_scan_at", source_state)


class FakeRSSFetcher:
    def __init__(self, batches: list[list[Paper]]) -> None:
        self.batches = batches
        self.index = 0

    def fetch(self, source, state):
        batch = self.batches[min(self.index, len(self.batches) - 1)]
        self.index += 1
        return FetchResult(source_id=source.id, papers=batch, fetched_count=len(batch), etag=f"etag-{self.index}")


def debug_only_config(config, state_dir: Path):
    debug_user = User(
        id="debug_user",
        display_name="Debug User",
        subscriptions=UserSubscriptions(
            rss=[RssSubscription(source_id="debug_fake_rss")],
            indexed_venues=[],
            website_watch=[],
        ),
        delivery=UserDelivery(),
    )
    return replace(
        config,
        users=UsersConfig(users=[debug_user]),
        settings=replace(config.settings, state_dir=state_dir),
    )


def make_paper(paper_id: str, title: str) -> Paper:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    return Paper(
        id=paper_id,
        title=title,
        normalized_title=title.lower(),
        authors=[],
        abstract=None,
        venue="Debug Fake RSS",
        venue_type=VenueType.PREPRINT,
        ccf_level=CcfLevel.NON_CCF,
        area="debug",
        source_id="debug_fake_rss",
        source_url="http://127.0.0.1:8766/feed.xml",
        paper_url=f"https://example.com/{paper_id}",
        pdf_url=None,
        doi=None,
        arxiv_id=None,
        dblp_key=None,
        openreview_id=None,
        year=2026,
        published_at=now,
        first_seen_at=now,
        last_seen_at=now,
        score=0,
        tags=[],
        summary=None,
        recommendation=Recommendation.IGNORE,
        raw={},
    )


if __name__ == "__main__":
    unittest.main()
