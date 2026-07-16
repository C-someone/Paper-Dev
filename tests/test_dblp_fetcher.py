from __future__ import annotations

import unittest

from paper_watcher.config_loader import load_config
from paper_watcher.fetchers.dblp_fetcher import DBLPFetcher


class DBLPFetcherTests(unittest.TestCase):
    def test_parse_dblp_xml(self) -> None:
        config = load_config("config")
        source = next(item for item in config.sources.sources if item.id == "dblp_ccs")
        xml = b"""
        <dblp>
          <inproceedings key="conf/ccs/Test2026">
            <author>Alice Example</author>
            <author>Bob Example</author>
            <title>A Security Paper.</title>
            <year>2026</year>
            <ee>https://doi.org/10.1145/1234567.7654321</ee>
          </inproceedings>
        </dblp>
        """

        papers = DBLPFetcher()._parse_xml(source, xml, "https://dblp.org/db/conf/ccs/index.xml")

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].title, "A Security Paper.")
        self.assertEqual(papers[0].authors, ["Alice Example", "Bob Example"])
        self.assertEqual(papers[0].dblp_key, "conf/ccs/Test2026")
        self.assertEqual(papers[0].doi, "10.1145/1234567.7654321")


if __name__ == "__main__":
    unittest.main()
