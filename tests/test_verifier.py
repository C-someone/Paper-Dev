from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from paper_watcher.config_loader import load_config
from paper_watcher.fetchers.base import FetchResult
from paper_watcher.models import Source, SourceType
from paper_watcher.storage.file_storage import FileStateStore
from paper_watcher.verifier import classify_error, verify_sources


class VerifierTests(unittest.TestCase):
    def test_classify_error(self) -> None:
        self.assertEqual(classify_error("429 Too Many Requests"), "http_429")
        self.assertEqual(classify_error("503 Service Unavailable"), "http_503")
        self.assertEqual(classify_error("Connection reset by peer"), "network_error")
        self.assertEqual(classify_error("invalid DBLP XML"), "parse_error")
        self.assertEqual(classify_error("missing venue_key"), "missing_required_field")

    def test_verify_supported_source_writes_state(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            config = replace(config, settings=replace(config.settings, state_dir=Path(directory_name)))
            fake_fetcher = FakeFetcher(FetchResult(source_id="debug_fake_rss", papers=[], fetched_count=3))
            with patch("paper_watcher.verifier.RSSFetcher", return_value=fake_fetcher):
                results = verify_sources(
                    config,
                    source_id="debug_fake_rss",
                    include_disabled=True,
                )

            verification = FileStateStore(Path(directory_name)).load_source_verification()
            self.assertEqual(results[0].status, "ok")
            self.assertEqual(results[0].item_count, 3)
            self.assertEqual(verification["debug_fake_rss"]["status"], "ok")

    def test_verify_unsupported_source(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            config = replace(config, settings=replace(config.settings, state_dir=Path(directory_name)))
            unsupported_source = Source(
                id="openreview_test",
                name="OpenReview Test",
                source_type=SourceType.OPENREVIEW,
                openreview_venue_id="test/venue",
            )
            config = replace(
                config,
                sources=replace(config.sources, sources=[*config.sources.sources, unsupported_source]),
            )
            results = verify_sources(
                config,
                source_id="openreview_test",
                include_disabled=True,
            )

            self.assertEqual(results[0].status, "unsupported_source_type")


class FakeFetcher:
    def __init__(self, result: FetchResult) -> None:
        self.result = result

    def fetch(self, source, state):
        return self.result


if __name__ == "__main__":
    unittest.main()
