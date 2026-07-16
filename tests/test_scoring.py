from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from paper_watcher.config_loader import load_config
from paper_watcher.filters.scoring import score_paper
from paper_watcher.models import CcfLevel, Paper, Recommendation, VenueType


class ScoringTests(unittest.TestCase):
    def test_keyword_score_recommends_read(self) -> None:
        config = load_config(Path("config"))
        source = config.sources.sources[0]
        paper = Paper(
            id="paper_test",
            title="Prompt Injection for LLM Security in Fraud Detection",
            normalized_title="prompt injection for llm security in fraud detection",
            authors=["A. Researcher"],
            abstract="We study prompt injection and scam detection for agent security.",
            venue="arXiv cs.CR",
            venue_type=VenueType.PREPRINT,
            ccf_level=CcfLevel.NON_CCF,
            area="security",
            source_id=source.id,
            source_url=source.feed_url,
            paper_url="https://example.com/paper",
            pdf_url=None,
            doi=None,
            arxiv_id=None,
            dblp_key=None,
            openreview_id=None,
            year=2026,
            published_at=datetime(2026, 7, 15, tzinfo=UTC),
            first_seen_at=datetime(2026, 7, 15, tzinfo=UTC),
            last_seen_at=datetime(2026, 7, 15, tzinfo=UTC),
            score=0,
            tags=[],
            recommendation=Recommendation.IGNORE,
            raw={},
        )

        scored = score_paper(paper, source, config)

        self.assertGreaterEqual(scored.score, 9)
        self.assertEqual(scored.recommendation, Recommendation.READ)
        self.assertIn("strong:prompt injection", scored.tags)

    def test_negative_keyword_lowers_score(self) -> None:
        config = load_config(Path("config"))
        source = config.sources.sources[0]
        paper = replace(
            Paper(
                id="paper_test",
                title="Image Segmentation Only",
                normalized_title="image segmentation only",
                authors=[],
                abstract="This is image segmentation only.",
                venue="arXiv",
                venue_type=VenueType.PREPRINT,
                ccf_level=CcfLevel.NON_CCF,
                area=None,
                source_id=source.id,
                source_url=source.feed_url,
                paper_url=None,
                pdf_url=None,
                doi=None,
                arxiv_id=None,
                dblp_key=None,
                openreview_id=None,
                year=None,
                published_at=None,
                first_seen_at=datetime(2026, 7, 15, tzinfo=UTC),
                last_seen_at=datetime(2026, 7, 15, tzinfo=UTC),
            ),
        )

        scored = score_paper(paper, source, config)

        self.assertEqual(scored.recommendation, Recommendation.IGNORE)


if __name__ == "__main__":
    unittest.main()
