from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from paper_watcher.agent_review.search_review import _extract_json_object, list_search_reviews, review_search_results
from paper_watcher.config_loader import load_config
from paper_watcher.storage.file_storage import FileStateStore


class SearchReviewTests(unittest.TestCase):
    def test_rule_based_review_detects_public_accepted_info(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            state_dir = root / "state"
            input_path = root / "results.json"
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            input_path.write_text(
                json.dumps(
                    {
                        "venue_id": "ndss",
                        "year": 2027,
                        "query": "NDSS 2027 accepted papers",
                        "results": [
                            {
                                "title": "NDSS Symposium 2027 Accepted Papers",
                                "url": "https://www.ndss-symposium.org/ndss2027/accepted-papers/",
                                "snippet": "Accepted papers for NDSS 2027 are now available.",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = review_search_results(
                config,
                input_path=input_path,
                reviewer="rule_based",
            )

            self.assertEqual(result.review.conference_status, "scheduled")
            self.assertEqual(result.review.accepted_info_status, "public")
            self.assertEqual(result.review.action, "monitor_accepted_page")
            self.assertIn("accepted", result.response_text.lower())

            stored = FileStateStore(state_dir).load_conference_search_reviews()
            self.assertEqual(len(stored), 1)
            listed = list_search_reviews(config, venue_id="ndss")
            self.assertIn("monitor_accepted_page", listed)

    def test_search_review_dry_run_does_not_write_state(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            state_dir = root / "state"
            input_path = root / "results.json"
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            input_path.write_text(
                json.dumps(
                    {
                        "venue_id": "ndss",
                        "year": 2027,
                        "results": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            review_search_results(config, input_path=input_path, reviewer="rule_based", dry_run=True)

            stored = FileStateStore(state_dir).load_conference_search_reviews()
            self.assertEqual(stored, [])

    def test_rule_based_review_does_not_treat_negative_accepted_summary_as_public(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            state_dir = root / "state"
            input_path = root / "results.json"
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            input_path.write_text(
                json.dumps(
                    {
                        "venue_id": "ndss",
                        "year": 2027,
                        "query": "NDSS 2027 accepted papers",
                        "official_domains": ["ndss-symposium.org"],
                        "aliases": ["NDSS", "NDSS Symposium"],
                        "results": [
                            {
                                "title": "NDSS Symposium 2027",
                                "url": "https://www.ndss-symposium.org/ndss2027/",
                                "snippet": (
                                    "The site outlines submission options. It does not provide information "
                                    "about accepted papers on the public page."
                                ),
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = review_search_results(
                config,
                input_path=input_path,
                reviewer="rule_based",
                dry_run=True,
            )

            self.assertEqual(result.review.conference_status, "likely_scheduled")
            self.assertEqual(result.review.accepted_info_status, "not_public")
            self.assertEqual(result.review.action, "monitor_cfp_page")

    def test_rule_based_review_rejects_wrong_year_program_page(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            state_dir = root / "state"
            input_path = root / "results.json"
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            input_path.write_text(
                json.dumps(
                    {
                        "venue_id": "dsn",
                        "year": 2026,
                        "query": "DSN 2026 program",
                        "official_domains": ["dsn.org"],
                        "aliases": ["DSN", "Dependable Systems and Networks"],
                        "results": [
                            {
                                "title": "DSN-2006 Full Program",
                                "url": "http://2006.dsn.org/FullProgram.html",
                                "snippet": (
                                    "The page is for DSN 2006. The user query asks about DSN 2026 program; "
                                    "this page is not current to 2026."
                                ),
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = review_search_results(config, input_path=input_path, reviewer="rule_based", dry_run=True)

            self.assertNotEqual(result.review.accepted_info_status, "public")
            self.assertNotEqual(result.review.action, "monitor_accepted_page")

    def test_extract_json_object_accepts_markdown_wrapped_json(self) -> None:
        data = _extract_json_object(
            """
```json
{"conference_status": "likely_scheduled", "confidence": 0.78}
```
            """
        )

        self.assertEqual(data["conference_status"], "likely_scheduled")
        self.assertEqual(data["confidence"], 0.78)


if __name__ == "__main__":
    unittest.main()
