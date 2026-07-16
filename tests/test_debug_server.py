from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from paper_watcher.debug_server import DebugUpdateHandler
from paper_watcher.storage.file_storage import FileStateStore
from scripts.send_debug_update import build_fake_rss


class DebugServerTests(unittest.TestCase):
    def test_payload_to_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            handler = object.__new__(DebugUpdateHandler)
            handler.state_store = FileStateStore(Path(directory_name))
            handler.known_source_ids = {"debug_fake_rss"}

            event = handler._payload_to_event(
                {
                    "title": "Injected Paper",
                    "link": "https://example.com/injected",
                    "source_id": "debug_fake_rss",
                    "paper_id": "debug_paper_1",
                }
            )

            self.assertEqual(event.title, "Injected Paper")
            self.assertEqual(event.link, "https://example.com/injected")
            self.assertEqual(event.paper_id, "debug_paper_1")
            self.assertEqual(event.matched_users, [])
            self.assertEqual(event.source_type, "debug")

    def test_payload_rejects_unknown_source(self) -> None:
        handler = object.__new__(DebugUpdateHandler)
        handler.known_source_ids = {"debug_fake_rss"}

        with self.assertRaisesRegex(ValueError, "unknown source_id"):
            handler._payload_to_event(
                {
                    "title": "Injected Paper",
                    "source_id": "missing",
                }
            )

    def test_build_fake_rss(self) -> None:
        xml = build_fake_rss(title="Fake Title", link="https://example.com/fake", guid="guid-1")

        self.assertIn("Fake Title", xml)
        self.assertIn("https://example.com/fake", xml)
        self.assertIn("guid-1", xml)


if __name__ == "__main__":
    unittest.main()
