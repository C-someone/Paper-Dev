from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from paper_watcher.agent_review.search_review import ConferenceSearchReview, ReviewResult
from paper_watcher.conference_signal_review import (
    detect_conference_signal,
    review_conference_signal,
    run_due_conference_signal_reviews,
)
from paper_watcher.config_loader import load_config
from paper_watcher.storage.file_storage import FileStateStore, WatchEvent


class ConferenceSignalReviewTests(unittest.TestCase):
    def test_detects_dblp_proceedings_signal(self) -> None:
        config = load_config(Path("config"))
        event = make_dsn_event()

        signal = detect_conference_signal(config, event)

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.venue_id, "dsn")
        self.assertEqual(signal.year, 2026)
        self.assertEqual(signal.signal_type, "proceedings_indexed")

    def test_review_signal_stores_followup_task(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            config = replace(config, settings=replace(config.settings, state_dir=Path(directory_name)))
            event = make_dsn_event()
            signal = detect_conference_signal(config, event)
            assert signal is not None
            review = make_review(
                accepted_info_status="not_public",
                action="monitor_cfp_page",
                dates_text="June 22-25, 2027",
            )

            with patch("paper_watcher.conference_signal_review.search_and_review_conference", return_value=(object(), ReviewResult(review, ""))):
                result = review_conference_signal(config, signal, reviewer="rule_based", num_results=2)

            self.assertTrue(result.reviewed)
            task = FileStateStore(Path(directory_name)).load_scheduled_tasks()["conference_signal_review:dsn:2026"]
            self.assertEqual(task["signal_type"], "proceedings_indexed")
            self.assertEqual(task["last_review_id"], "review_dsn")
            self.assertEqual(task["accepted_info_status"], "not_public")
            self.assertEqual(task["next_check_reason"], "after visible conference date")
            self.assertTrue(task["next_check_after"].startswith("2027-06-26T"))

    def test_public_accepted_info_promotes_candidate_and_stops_followup(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            config = replace(config, settings=replace(config.settings, state_dir=Path(directory_name)))
            signal = detect_conference_signal(config, make_dsn_event())
            assert signal is not None
            review = make_review(
                accepted_info_status="public",
                action="monitor_accepted_page",
                accepted_info_url="https://dsn2026.example/accepted-papers/",
            )

            with patch("paper_watcher.conference_signal_review.search_and_review_conference", return_value=(object(), ReviewResult(review, ""))):
                with patch("paper_watcher.conference_signal_review.promote_conference_review", return_value=object()) as promote:
                    result = review_conference_signal(config, signal, reviewer="rule_based", num_results=2)

            self.assertTrue(result.promoted_candidate)
            promote.assert_called_once()
            task = FileStateStore(Path(directory_name)).load_scheduled_tasks()["conference_signal_review:dsn:2026"]
            self.assertIsNone(task["next_check_after"])
            self.assertEqual(task["next_check_reason"], "accepted/program information already public")

    def test_due_followup_runs_once(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            config = replace(config, settings=replace(config.settings, state_dir=Path(directory_name)))
            store = FileStateStore(Path(directory_name))
            store.save_scheduled_tasks(
                {
                    "conference_signal_review:dsn:2026": {
                        "type": "conference_signal_review",
                        "venue_id": "dsn",
                        "year": 2026,
                        "source_id": "dblp_dsn",
                        "source_name": "DBLP DSN",
                        "signal_type": "proceedings_indexed",
                        "signal_title": "DSN 2026",
                        "last_signal_event_id": "evt_dsn",
                        "last_signal_at": "2026-07-27T00:00:00+00:00",
                        "next_check_after": "2000-01-01T00:00:00+00:00",
                    }
                }
            )
            review = make_review(accepted_info_status="not_public", action="monitor_cfp_page")

            with patch("paper_watcher.conference_signal_review.search_and_review_conference", return_value=(object(), ReviewResult(review, ""))) as search:
                results = run_due_conference_signal_reviews(config, reviewer="rule_based", num_results=2)

            self.assertEqual(len(results), 1)
            search.assert_called_once()


def make_dsn_event() -> WatchEvent:
    return WatchEvent(
        event_id="evt_dsn",
        seen_at="2026-07-27T09:05:40.594096+00:00",
        source_id="dblp_dsn",
        source_type="dblp",
        paper_id="paper_dsn",
        title="56th Annual IEEE International Conference on Dependable Systems and Networks, DSN 2026",
        link="https://doi.org/10.1109/DSN69566.2026",
        matched_users=[],
        raw={
            "authors": [],
            "dblp_key": "conf/dsn/2026",
            "published_at": "2026-01-01T00:00:00+00:00",
            "source_url": "https://dblp.org/db/conf/dsn/index.xml",
            "venue": "DBLP DSN",
            "venue_key": "conf/dsn",
        },
    )


def make_review(
    *,
    accepted_info_status: str,
    action: str,
    dates_text: str | None = None,
    accepted_info_url: str | None = None,
) -> ConferenceSearchReview:
    return ConferenceSearchReview(
        review_id="review_dsn",
        reviewed_at=datetime.now(UTC).isoformat(),
        reviewer="rule_based",
        venue_id="dsn",
        year=2026,
        conference_status="scheduled",
        accepted_info_status=accepted_info_status,
        action=action,
        confidence=0.9,
        reason="test review",
        evidence=["test evidence"],
        official_url="https://dsn2026.example/",
        accepted_info_url=accepted_info_url,
        dates_text=dates_text,
    )


if __name__ == "__main__":
    unittest.main()
