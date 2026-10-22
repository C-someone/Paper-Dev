from __future__ import annotations

import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import yaml

from paper_watcher.conference_discovery import approve_candidate, discover_conferences, list_candidates
from paper_watcher.config_loader import load_config
from paper_watcher.fetchers.base import FetchResult
from paper_watcher.storage.file_storage import FileStateStore


class ConferenceDiscoveryTests(unittest.TestCase):
    def test_discovers_and_persists_candidates(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            state_dir = Path(directory_name)
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))

            with patch("paper_watcher.conference_discovery.WebsiteWatcherFetcher", return_value=FakeWebsiteFetcher()):
                result = discover_conferences(config, venue_id="ndss", year=2027)

            self.assertEqual(len(result.candidates), 2)
            self.assertIn("ndss 2027", result.response_text)
            self.assertTrue(any(candidate.probe_status == "ok" for candidate in result.candidates))

            stored = FileStateStore(state_dir).load_source_candidates()
            self.assertEqual(len(stored), 2)
            listed = list_candidates(config, status="pending", venue_id="ndss")
            self.assertEqual(len(listed.candidates), 2)

    def test_approve_candidate_writes_source_and_root_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            config_dir = Path(directory_name) / "config"
            shutil.copytree(Path("config"), config_dir)
            state_dir = Path(directory_name) / "state"
            settings_path = config_dir / "settings.yaml"
            settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
            settings["paths"]["state_dir"] = str(state_dir)
            settings_path.write_text(yaml.safe_dump(settings, allow_unicode=True, sort_keys=False), encoding="utf-8")
            config = load_config(config_dir)

            with patch("paper_watcher.conference_discovery.WebsiteWatcherFetcher", return_value=FakeWebsiteFetcher()):
                result = discover_conferences(config, venue_id="ndss", year=2027)

            candidate = next(item for item in result.candidates if item.kind == "accepted_papers")
            preview = approve_candidate(config, candidate_id=candidate.candidate_id, dry_run=True)
            self.assertIn("source_type: website_watch", preview.response_text)

            approved = approve_candidate(config, candidate_id=candidate.candidate_id)
            self.assertIn(candidate.source_id, approved.response_text)

            sources = yaml.safe_load((config_dir / "sources.yaml").read_text(encoding="utf-8"))
            users = yaml.safe_load((config_dir / "users.yaml").read_text(encoding="utf-8"))
            source_ids = {source["id"] for source in sources["sources"]}
            self.assertIn(candidate.source_id, source_ids)
            root = next(user for user in users["users"] if user["id"] == "root")
            root_website_sources = {item["source_id"] for item in root["subscriptions"]["website_watch"]}
            self.assertIn(candidate.source_id, root_website_sources)


class FakeWebsiteFetcher:
    def fetch(self, source, state=None):
        if "accepted-papers" in source.watch_url:
            return FetchResult(
                source_id=source.id,
                papers=[],
                fetched_count=1,
                content_hash="hash-ok",
            )
        return FetchResult(source_id=source.id, error="404 error for test")


if __name__ == "__main__":
    unittest.main()
