from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from paper_watcher.agent_review.search_review import ConferenceSearchReview, ReviewResult, SearchReviewInput
from paper_watcher.conference_review_batch import review_conferences_batch
from paper_watcher.conference_search import ConferenceSearchResult
from paper_watcher.config_loader import load_config


class ConferenceReviewBatchTests(unittest.TestCase):
    def test_batch_reviews_matching_profiles_and_continues_after_errors(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            config = replace(config, settings=replace(config.settings, state_dir=Path(directory_name)))

            with patch(
                "paper_watcher.conference_review_batch.search_and_review_conference",
                side_effect=fake_search_and_review,
            ):
                result = review_conferences_batch(
                    config,
                    venue_id="ndss",
                    year=2026,
                    reviewer="rule_based",
                    dry_run=True,
                )

        self.assertEqual(result.reviewed_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertIn("monitor_accepted_page: 1", result.response_text)
        self.assertIn("ndss 2026", result.response_text)

    def test_batch_records_per_venue_error_without_stopping(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            config = replace(config, settings=replace(config.settings, state_dir=Path(directory_name)))

            with patch(
                "paper_watcher.conference_review_batch.search_and_review_conference",
                side_effect=ValueError("search failed for test"),
            ):
                result = review_conferences_batch(
                    config,
                    venue_id="ndss",
                    year=2026,
                    reviewer="rule_based",
                    dry_run=True,
                )

        self.assertEqual(result.reviewed_count, 0)
        self.assertEqual(result.error_count, 1)
        self.assertIn("ERROR search failed for test", result.response_text)


def fake_search_and_review(config, *, venue_id, year, reviewer, num_results, dry_run):
    review = ConferenceSearchReview(
        review_id=f"review_{venue_id}_{year}",
        reviewed_at="2026-07-19T00:00:00+00:00",
        reviewer=reviewer,
        venue_id=venue_id,
        year=year,
        conference_status="scheduled",
        accepted_info_status="public",
        action="monitor_accepted_page",
        confidence=0.95,
        reason="accepted papers are public",
        evidence=["official accepted papers page"],
        accepted_info_url=f"https://example.com/{venue_id}/{year}/accepted-papers/",
    )
    search = ConferenceSearchResult(
        search_input=SearchReviewInput(
            venue_id=venue_id,
            year=year,
            query=None,
            official_domains=[],
            aliases=[],
            results=[],
        ),
        queries=[],
        response_text="",
    )
    return search, ReviewResult(review=review, response_text="")


if __name__ == "__main__":
    unittest.main()
