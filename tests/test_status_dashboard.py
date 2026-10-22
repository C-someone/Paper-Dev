from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from paper_watcher.config_loader import load_config
from paper_watcher.status_dashboard import build_status_dashboard
from paper_watcher.storage.file_storage import FileStateStore, WatchEvent


class StatusDashboardTests(unittest.TestCase):
    def test_status_dashboard_summarizes_config_and_state(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            state_dir = Path(directory_name)
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            store = FileStateStore(state_dir)
            store.append_events(
                [
                    WatchEvent(
                        event_id="evt_status",
                        seen_at="2026-07-19T00:00:00+00:00",
                        source_id="ndss_2026_accepted",
                        source_type="website_watch",
                        paper_id="paper_status",
                        title="Status Paper",
                        link="https://example.test/status-paper",
                        matched_users=[],
                        raw={},
                    )
                ]
            )
            store.save_source_candidates(
                [
                    {
                        "candidate_id": "cand_status",
                        "venue_id": "ndss",
                        "year": 2026,
                        "kind": "accepted_papers",
                        "url": "https://example.test",
                        "source_id": "ndss_2026_status",
                        "source_name": "NDSS 2026 Status",
                        "css_selector": "main",
                        "ccf_level": "A",
                        "venue_type": "conference",
                        "priority": 5,
                        "confidence": 0.9,
                        "reason": "test",
                        "probe_status": "reviewed",
                        "status": "pending",
                        "first_seen_at": "2026-07-19T00:00:00+00:00",
                        "last_checked_at": "2026-07-19T00:00:00+00:00",
                    }
                ]
            )
            store.save_scheduled_tasks(
                {
                    "conference_review:2026": {
                        "last_run_at": "2026-07-19T00:00:00+00:00",
                        "last_success_at": "2026-07-19T00:00:01+00:00",
                    }
                }
            )

            text = build_status_dashboard(config).response_text
            json_text = build_status_dashboard(config, output_format="json").response_text

        self.assertIn("PaperWatcher status", text)
        self.assertIn("Events: 1", text)
        self.assertIn("1 pending", text)
        data = json.loads(json_text)
        self.assertEqual(data["events"]["total"], 1)
        self.assertEqual(data["candidates"]["pending"], 1)


if __name__ == "__main__":
    unittest.main()
