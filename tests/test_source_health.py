from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from paper_watcher.config_loader import load_config
from paper_watcher.source_health import list_source_health
from paper_watcher.storage.file_storage import FileStateStore


class SourceHealthTests(unittest.TestCase):
    def test_lists_source_health_with_due_status(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            state_dir = Path(directory_name)
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            store = FileStateStore(state_dir)
            store.save_source_state(
                {
                    "dblp_ccs": {
                        "last_scan_at": "2026-07-16T00:00:00+00:00",
                        "next_scan_after": "2999-01-01T00:00:00+00:00",
                        "last_success_at": "2026-07-16T00:00:00+00:00",
                    },
                    "arxiv_cs_cr": {
                        "last_scan_at": "2026-07-16T00:00:00+00:00",
                        "next_scan_after": "2000-01-01T00:00:00+00:00",
                        "last_success_at": "2026-07-16T00:00:00+00:00",
                    },
                }
            )

            due = list_source_health(config, due_only=True)

            source_ids = {row.source_id for row in due.rows}
            self.assertIn("arxiv_cs_cr", source_ids)
            self.assertNotIn("dblp_ccs", source_ids)
            self.assertIn("due=True", due.response_text)

    def test_filters_failed_sources_and_json_output(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            state_dir = Path(directory_name)
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            store = FileStateStore(state_dir)
            store.save_source_state(
                {
                    "dblp_ccs": {
                        "last_scan_at": "2026-07-16T00:00:00+00:00",
                        "last_error": "503 Service Unavailable",
                        "last_error_at": "2026-07-16T00:00:01+00:00",
                    }
                }
            )
            store.save_source_verification(
                {
                    "arxiv_cs_cr": {
                        "status": "http_429",
                        "checked_at": "2026-07-16T00:00:02+00:00",
                    }
                }
            )

            failed = list_source_health(config, failed_only=True, output_format="json")

            self.assertIn('"count": 2', failed.response_text)
            self.assertIn('"source_id": "dblp_ccs"', failed.response_text)
            self.assertIn('"verification_status": "http_429"', failed.response_text)


if __name__ == "__main__":
    unittest.main()
