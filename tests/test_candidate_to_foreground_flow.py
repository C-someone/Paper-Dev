from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from paper_watcher.background import run_background_once
from paper_watcher.conference_discovery import SourceCandidate, SourceCandidateStore, approve_candidate
from paper_watcher.config_loader import load_config
from paper_watcher.foreground import pull_user_updates
from paper_watcher.http_client import HttpResponse
from paper_watcher.storage.file_storage import FileStateStore


class CandidateToForegroundFlowTests(unittest.TestCase):
    def test_approved_candidate_becomes_website_watch_and_foreground_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            config_dir = root / "config"
            state_dir = root / "state"
            shutil.copytree(Path("config"), config_dir)
            _set_state_dir(config_dir, state_dir)
            config = load_config(config_dir)

            candidate = _candidate()
            SourceCandidateStore(FileStateStore(state_dir)).upsert_candidates([candidate])
            approve_candidate(config, candidate_id=candidate.candidate_id)

            config = load_config(config_dir)
            fake_client = FakeHttpClient(
                [
                    b"""
                    <main>
                      <h1>Accepted Papers</h1>
                      <ul><li><a href="/paper-a">Paper A</a></li></ul>
                    </main>
                    """,
                    b"""
                    <main>
                      <h1>Accepted Papers</h1>
                      <ul>
                        <li><a href="/paper-a">Paper A</a></li>
                        <li><a href="/paper-b">Paper B</a></li>
                      </ul>
                    </main>
                    """,
                ]
            )

            from unittest.mock import patch

            with patch("paper_watcher.background.build_http_client", return_value=fake_client):
                first = run_background_once(config, source_id=candidate.source_id, include_disabled=True)
                second = run_background_once(config, source_id=candidate.source_id, include_disabled=True)

            pull = pull_user_updates(config, "root", update_cursor=False)

            self.assertEqual(first, (1, 0, 0))
            self.assertEqual(second, (1, 2, 0))
            self.assertIn("Paper B", pull.response_text)
            self.assertIn("https://example.test/paper-b", pull.response_text)
            self.assertTrue(any(event.title == "Paper B" for event in pull.events))


class FakeHttpClient:
    def __init__(self, contents: list[bytes]) -> None:
        self.contents = contents
        self.index = 0

    def get(self, url: str, *, headers=None, allow_cached_on_error=True):
        content = self.contents[min(self.index, len(self.contents) - 1)]
        self.index += 1
        return HttpResponse(status_code=200, content=content, headers={}, url=url)


def _set_state_dir(config_dir: Path, state_dir: Path) -> None:
    settings_path = config_dir / "settings.yaml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["paths"]["state_dir"] = str(state_dir)
    settings_path.write_text(yaml.safe_dump(settings, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _candidate() -> SourceCandidate:
    return SourceCandidate(
        candidate_id="cand_e2e_ndss_2026",
        venue_id="ndss",
        year=2026,
        kind="accepted_papers",
        url="https://example.test/ndss2026/accepted-papers/",
        source_id="ndss_2026_e2e_accepted",
        source_name="NDSS 2026 E2E Accepted Papers",
        css_selector="main",
        ccf_level="A",
        area="security",
        venue_type="conference",
        priority=5,
        confidence=0.95,
        reason="test candidate",
        probe_status="reviewed",
        status="pending",
        first_seen_at="2026-07-19T00:00:00+00:00",
        last_checked_at="2026-07-19T00:00:00+00:00",
        metadata={
            "paper_selector": "main li",
            "paper_title_selector": "a",
            "paper_link_selector": "a",
        },
        tags=["ndss", "accepted_papers", "test"],
    )


if __name__ == "__main__":
    unittest.main()
