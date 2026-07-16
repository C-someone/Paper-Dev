from __future__ import annotations

import unittest

from paper_watcher.parsers.normalizer import extract_arxiv_id, extract_doi, normalize_title, paper_identity


class NormalizerTests(unittest.TestCase):
    def test_normalize_title(self) -> None:
        self.assertEqual(normalize_title("  LLM-Security: A  Survey! "), "llm security a survey")

    def test_extract_ids(self) -> None:
        self.assertEqual(extract_arxiv_id("https://arxiv.org/abs/2607.12345v2"), "2607.12345")
        self.assertEqual(extract_doi("doi:10.1145/1234567.1234568."), "10.1145/1234567.1234568")

    def test_identity_prefers_arxiv(self) -> None:
        first = paper_identity("same title", arxiv_id="2607.12345")
        second = paper_identity("different title", arxiv_id="2607.12345")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
