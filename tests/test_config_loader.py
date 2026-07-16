from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from paper_watcher.config_loader import ConfigError, load_config
from paper_watcher.models import Source, SourceType


class ConfigLoaderTests(unittest.TestCase):
    def test_load_default_config(self) -> None:
        config = load_config(Path("config"))

        self.assertEqual(len(config.sources.sources), 16)
        self.assertEqual(len(config.venues.venues), 2)
        self.assertEqual(len(config.users.users), 3)
        self.assertEqual(config.sources.sources[0].source_type, SourceType.ARXIV)

    def test_rss_source_requires_feed_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires feed_url"):
            Source.from_dict(
                {
                    "id": "bad_rss",
                    "name": "Bad RSS",
                    "source_type": "rss",
                }
            )

    def test_duplicate_source_ids_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            self._write_minimal_config(directory)
            sources = {
                "sources": [
                    {
                        "id": "duplicate",
                        "name": "One",
                        "source_type": "rss",
                        "feed_url": "https://example.com/one.xml",
                    },
                    {
                        "id": "duplicate",
                        "name": "Two",
                        "source_type": "rss",
                        "feed_url": "https://example.com/two.xml",
                    },
                ]
            }
            (directory / "sources.yaml").write_text(yaml.safe_dump(sources), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "duplicate source ids"):
                load_config(directory)

    def _write_minimal_config(self, directory: Path) -> None:
        files = {
            "sources.yaml": {"sources": []},
            "venues.yaml": {"venues": []},
            "users.yaml": {"users": []},
            "keywords.yaml": {
                "strong_keywords": {},
                "medium_keywords": {},
                "negative_keywords": {},
            },
            "scoring.yaml": {
                "base_scores": {"ccf": {}, "venue_type": {}},
                "priority_weight": 0.5,
                "recommendation_thresholds": {
                    "read": 9,
                    "skim": 6,
                    "archive": 3,
                    "ignore": 0,
                },
                "llm_summary": {"enabled": False},
            },
            "report.yaml": {
                "daily_report": {"enabled": True},
                "weekly_report": {"enabled": True},
            },
            "settings.yaml": {
                "database": {"path": "data/test.sqlite3"},
                "runtime": {},
                "paths": {},
            },
        }
        for filename, content in files.items():
            (directory / filename).write_text(yaml.safe_dump(content), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
