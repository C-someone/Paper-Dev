from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_watcher.conference_search import search_and_review_conference, search_conference
from paper_watcher.config_loader import load_config


class ConferenceSearchTests(unittest.TestCase):
    def test_search_conference_normalizes_exa_results(self) -> None:
        config = load_config(Path("config"))

        with patch.dict(os.environ, {"EXA_API_KEY": "test-key"}, clear=False):
            with patch("paper_watcher.conference_search.httpx.post", return_value=FakeExaResponse()):
                result = search_conference(config, venue_id="ndss", year=2027)

            self.assertGreaterEqual(len(result.search_input.results), 1)
            self.assertIn("NDSS 2027", result.response_text)
            self.assertIn("accepted papers", result.response_text.lower())

    def test_search_then_review_uses_rule_based_fallback(self) -> None:
        config = load_config(Path("config"))

        with patch.dict(os.environ, {"EXA_API_KEY": "test-key"}, clear=False):
            with patch("paper_watcher.conference_search.httpx.post", return_value=FakeExaResponse()):
                search_result, review_result = search_and_review_conference(
                    config,
                    venue_id="ndss",
                    year=2027,
                    reviewer="rule_based",
                    dry_run=True,
                )

        self.assertGreaterEqual(len(search_result.search_input.results), 1)
        self.assertEqual(review_result.review.conference_status, "scheduled")
        self.assertEqual(review_result.review.accepted_info_status, "public")


class FakeExaResponse:
    status_code = 200
    text = "ok"

    def json(self) -> dict:
        return {
            "results": [
                {
                    "title": "NDSS Symposium 2027 Accepted Papers",
                    "url": "https://www.ndss-symposium.org/ndss2027/accepted-papers/",
                    "summary": "Accepted papers for NDSS 2027 are now available.",
                    "publishedDate": "2026-07-01",
                }
            ]
        }


if __name__ == "__main__":
    unittest.main()
