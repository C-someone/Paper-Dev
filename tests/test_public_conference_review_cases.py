from __future__ import annotations

import unittest
from pathlib import Path

from paper_watcher.agent_review.search_review import SearchResultItem, SearchReviewInput, review_search_input
from paper_watcher.config_loader import load_config


class PublicConferenceReviewCaseTests(unittest.TestCase):
    def test_public_accepted_pages_are_monitor_accepted_page_candidates(self) -> None:
        config = load_config(Path("config"))

        cases = [
            SearchReviewInput(
                venue_id="usenix_security",
                year=2026,
                query="USENIX Security 2026 Cycle 1 accepted papers",
                official_domains=["usenix.org"],
                aliases=["USENIX Security", "USENIX Security Symposium", "USENIX Sec"],
                results=[
                    SearchResultItem(
                        title="USENIX Security '26 Cycle 1 Accepted Papers",
                        url="https://www.usenix.org/conference/usenixsecurity26/cycle1-accepted-papers",
                        snippet=(
                            "Prepublication versions of the accepted papers from the first submission "
                            "deadline are available below."
                        ),
                    )
                ],
            ),
            SearchReviewInput(
                venue_id="nsdi",
                year=2026,
                query="NSDI 2026 technical sessions accepted papers",
                official_domains=["usenix.org"],
                aliases=["NSDI", "USENIX NSDI", "USENIX Symposium on Networked Systems Design and Implementation"],
                results=[
                    SearchResultItem(
                        title="NSDI '26 Technical Sessions",
                        url="https://www.usenix.org/conference/nsdi26/technical-sessions",
                        snippet="Papers and proceedings for the NSDI '26 technical sessions are available.",
                    )
                ],
            ),
            SearchReviewInput(
                venue_id="ndss",
                year=2026,
                query="NDSS 2026 accepted papers",
                official_domains=["ndss-symposium.org"],
                aliases=["NDSS", "NDSS Symposium", "Network and Distributed System Security Symposium"],
                results=[
                    SearchResultItem(
                        title="NDSS Symposium 2026 Accepted Papers",
                        url="https://www.ndss-symposium.org/ndss2026/accepted-papers/",
                        snippet=(
                            "This year, 265 papers were accepted. View the detailed program page to learn "
                            "when papers will be presented."
                        ),
                    )
                ],
            ),
            SearchReviewInput(
                venue_id="ieee_sp",
                year=2026,
                query="IEEE Symposium on Security and Privacy 2026 accepted papers",
                official_domains=["ieee-security.org"],
                aliases=["IEEE S&P", "IEEE Security and Privacy", "Oakland"],
                results=[
                    SearchResultItem(
                        title="IEEE Symposium on Security and Privacy 2026 Accepted Papers",
                        url="https://sp2026.ieee-security.org/accepted-papers.html",
                        snippet="Accepted Papers for the 47th IEEE Symposium on Security and Privacy, May 18-21, 2026.",
                    )
                ],
            ),
            SearchReviewInput(
                venue_id="sigcomm",
                year=2025,
                query="ACM SIGCOMM 2025 accepted papers",
                official_domains=["conferences.sigcomm.org"],
                aliases=["SIGCOMM", "ACM SIGCOMM", "ACM SIGCOMM Conference"],
                results=[
                    SearchResultItem(
                        title="ACM SIGCOMM 2025 List of Accepted Papers",
                        url="https://conferences.sigcomm.org/sigcomm/2025/accepted-papers/",
                        snippet="This page announces the acceptance of the following full papers and short papers.",
                    )
                ],
            ),
            SearchReviewInput(
                venue_id="ccs",
                year=2025,
                query="ACM CCS 2025 accepted papers",
                official_domains=["sigsac.org", "acm.org"],
                aliases=["ACM CCS", "CCS", "ACM Conference on Computer and Communications Security"],
                results=[
                    SearchResultItem(
                        title="ACM CCS 2025 Accepted Papers",
                        url="https://www.sigsac.org/ccs/CCS2025/accepted-papers/",
                        snippet="Accepted papers for the 32nd ACM Conference on Computer and Communications Security.",
                    )
                ],
            ),
        ]

        for case in cases:
            with self.subTest(venue_id=case.venue_id, year=case.year):
                result = review_search_input(config, case, reviewer="rule_based", dry_run=True)

                self.assertEqual(result.review.conference_status, "scheduled")
                self.assertEqual(result.review.accepted_info_status, "public")
                self.assertEqual(result.review.action, "monitor_accepted_page")
                self.assertGreaterEqual(result.review.confidence, 0.85)
                self.assertEqual(result.review.accepted_info_url, case.results[0].url)


if __name__ == "__main__":
    unittest.main()
