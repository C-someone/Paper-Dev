from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from paper_watcher.config_loader import load_config
from paper_watcher.models import CcfLevel, Paper, Recommendation, VenueType
from paper_watcher.storage.database import connect
from paper_watcher.storage.migrations import init_db
from paper_watcher.storage.repository import Repository


class RepositoryTests(unittest.TestCase):
    def test_init_db_and_sync_sources(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            db_path = Path(directory_name) / "paper_watcher.sqlite3"
            connection = connect(db_path)
            try:
                init_db(connection)
                repository = Repository(connection)
                repository.upsert_sources(config.sources.sources)

                self.assertEqual(repository.count_sources(), 20)
                source_ids = {row["id"] for row in repository.list_sources()}
                self.assertIn("arxiv_cs_cr", source_ids)
                self.assertIn("usenix_security_2026_accepted", source_ids)
            finally:
                connection.close()

    def test_upsert_paper_is_idempotent(self) -> None:
        config = load_config(Path("config"))
        source = config.sources.sources[0]

        with tempfile.TemporaryDirectory() as directory_name:
            db_path = Path(directory_name) / "paper_watcher.sqlite3"
            connection = connect(db_path)
            try:
                init_db(connection)
                repository = Repository(connection)
                repository.upsert_sources(config.sources.sources)
                paper = Paper(
                    id="paper_1",
                    title="A Paper",
                    normalized_title="a paper",
                    authors=["A"],
                    abstract=None,
                    venue="arXiv",
                    venue_type=VenueType.PREPRINT,
                    ccf_level=CcfLevel.NON_CCF,
                    area=None,
                    source_id=source.id,
                    source_url=source.feed_url,
                    paper_url="https://example.com",
                    pdf_url=None,
                    doi=None,
                    arxiv_id=None,
                    dblp_key=None,
                    openreview_id=None,
                    year=2026,
                    published_at=None,
                    first_seen_at=datetime(2026, 7, 15, tzinfo=UTC),
                    last_seen_at=datetime(2026, 7, 15, tzinfo=UTC),
                    score=3,
                    tags=[],
                    summary=None,
                    recommendation=Recommendation.ARCHIVE,
                    raw={},
                )

                self.assertTrue(repository.upsert_paper(paper))
                self.assertFalse(repository.upsert_paper(paper))
                self.assertEqual(repository.count_papers(), 1)
                self.assertEqual(len(repository.list_papers(recommendation="archive")), 1)
                self.assertEqual(len(repository.search_papers("paper")), 1)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
