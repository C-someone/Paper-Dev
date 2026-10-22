from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from paper_watcher.agent_review.search_review import ConferenceSearchReview
from paper_watcher.conference_review_promoter import promote_conference_review
from paper_watcher.config_loader import load_config
from paper_watcher.storage.file_storage import FileStateStore


class ConferenceReviewPromoterTests(unittest.TestCase):
    def test_promotes_public_accepted_review_to_pending_candidate(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            state_dir = Path(directory_name)
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            store = FileStateStore(state_dir)
            review = _review()
            store.append_conference_search_reviews([review.to_dict()])

            preview = promote_conference_review(config, review_id=review.review_id, dry_run=True)
            self.assertIn("Promotion preview", preview.response_text)
            self.assertEqual(FileStateStore(state_dir).load_source_candidates(), [])

            result = promote_conference_review(config, review_id=review.review_id)
            self.assertIn("Promoted review", result.response_text)

            candidates = FileStateStore(state_dir).load_source_candidates()
            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertEqual(candidate["venue_id"], "ndss")
            self.assertEqual(candidate["year"], 2026)
            self.assertEqual(candidate["kind"], "accepted_papers")
            self.assertEqual(candidate["url"], "https://www.ndss-symposium.org/ndss2026/accepted-papers/")
            self.assertEqual(candidate["status"], "pending")
            self.assertEqual(candidate["source_id"], "ndss_2026_accepted_papers")

    def test_rejects_non_public_review(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            state_dir = Path(directory_name)
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            review = replace(_review(), accepted_info_status="not_public", action="monitor_cfp_page")
            FileStateStore(state_dir).append_conference_search_reviews([review.to_dict()])

            with self.assertRaisesRegex(ValueError, "action is not promotable"):
                promote_conference_review(config, review_id=review.review_id)


def _review() -> ConferenceSearchReview:
    return ConferenceSearchReview(
        review_id="review_ndss_2026_public",
        reviewed_at="2026-07-19T00:00:00+00:00",
        reviewer="pydantic_ai",
        venue_id="ndss",
        year=2026,
        conference_status="scheduled",
        accepted_info_status="public",
        action="monitor_accepted_page",
        confidence=0.95,
        reason="Official accepted papers page is public.",
        evidence=["official accepted papers page"],
        official_url="https://www.ndss-symposium.org/ndss2026/",
        accepted_info_url="https://www.ndss-symposium.org/ndss2026/accepted-papers/",
    )


if __name__ == "__main__":
    unittest.main()
