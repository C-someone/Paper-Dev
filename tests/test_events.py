from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from paper_watcher.config_loader import load_config
from paper_watcher.events import list_global_events
from paper_watcher.storage.file_storage import FileStateStore, WatchEvent


class EventListTests(unittest.TestCase):
    def test_lists_newest_events_first_with_limit(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            state_dir = Path(directory_name)
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            store = FileStateStore(state_dir)
            store.append_events(
                [
                    make_event("evt_1", "2026-07-15T00:00:00+00:00", "dblp_ccs", "First"),
                    make_event("evt_2", "2026-07-15T00:00:01+00:00", "dblp_ccs", "Second"),
                ]
            )

            result = list_global_events(config, limit=1)

            self.assertEqual([event.title for event in result.events], ["Second"])
            self.assertIn("[dblp_ccs] Second", result.response_text)

    def test_filters_record_only_and_notifiable_events(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            state_dir = Path(directory_name)
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            store = FileStateStore(state_dir)
            store.append_events(
                [
                    make_event("evt_1", "2026-07-15T00:00:00+00:00", "arxiv_cs_cr", "arXiv Paper"),
                    make_event("evt_2", "2026-07-15T00:00:01+00:00", "dblp_ccs", "CCF Paper"),
                ]
            )

            record_only = list_global_events(config, record_only=True)
            notifiable = list_global_events(config, notifiable=True)

            self.assertEqual([event.title for event in record_only.events], ["arXiv Paper"])
            self.assertEqual([event.title for event in notifiable.events], ["CCF Paper"])

    def test_json_output_and_source_filter(self) -> None:
        config = load_config(Path("config"))
        with tempfile.TemporaryDirectory() as directory_name:
            state_dir = Path(directory_name)
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            store = FileStateStore(state_dir)
            store.append_events(
                [
                    make_event("evt_1", "2026-07-15T00:00:00+00:00", "arxiv_cs_cr", "arXiv Paper"),
                    make_event("evt_2", "2026-07-15T00:00:01+00:00", "dblp_ccs", "CCF Paper"),
                ]
            )

            result = list_global_events(config, source_id="dblp_ccs", output_format="json")

            self.assertEqual(len(result.events), 1)
            self.assertIn('"count": 1', result.response_text)
            self.assertIn('"source_id": "dblp_ccs"', result.response_text)

    def test_record_only_and_notifiable_are_mutually_exclusive(self) -> None:
        config = load_config(Path("config"))

        with self.assertRaises(ValueError):
            list_global_events(config, record_only=True, notifiable=True)


def make_event(event_id: str, seen_at: str, source_id: str, title: str) -> WatchEvent:
    return WatchEvent(
        event_id=event_id,
        seen_at=seen_at,
        source_id=source_id,
        source_type="rss",
        paper_id=f"paper_{event_id}",
        title=title,
        link=f"https://example.com/{event_id}",
        matched_users=[],
        raw={},
    )


if __name__ == "__main__":
    unittest.main()
