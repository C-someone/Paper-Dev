from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from paper_watcher.config_loader import load_config
from paper_watcher.storage.database import connect
from paper_watcher.storage.file_storage import FileStateStore, WatchEvent
from paper_watcher.storage.index_store import LocalSqliteStateIndex


class StateIndexTests(unittest.TestCase):
    def test_rebuilds_and_queries_local_sqlite_index(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            state_dir = root / "state"
            database_path = root / "index.sqlite3"
            config = replace(
                config,
                settings=replace(config.settings, state_dir=state_dir, database_path=database_path),
            )

            store = FileStateStore(state_dir)
            store.append_events(
                [
                    make_event("evt_1", "2026-07-15T00:00:00+00:00", "dblp_ccs", "First"),
                    make_event("evt_2", "2026-07-15T00:00:01+00:00", "dblp_ccs", "Second"),
                ]
            )
            store.save_source_state(
                {
                    "dblp_ccs": {
                        "last_scan_at": "2026-07-16T00:00:00+00:00",
                        "next_scan_after": "2026-07-17T00:00:00+00:00",
                        "content_hash": "hash-1",
                    }
                }
            )
            store.save_user_cursors({"default": {"last_pulled_at": "2026-07-16T12:00:00+00:00"}})
            store.save_source_verification(
                {"dblp_ccs": {"status": "ok", "checked_at": "2026-07-16T00:00:00+00:00"}}
            )

            connection = connect(database_path)
            try:
                index = LocalSqliteStateIndex(connection)
                result = index.rebuild_from_store(store)
                self.assertEqual(result.event_count, 2)
                self.assertEqual(result.source_state_count, 1)
                self.assertEqual(result.user_cursor_count, 1)
                self.assertEqual(result.source_verification_count, 1)
                self.assertIsNotNone(result.synced_at)
            finally:
                connection.close()

            connection = connect(database_path)
            try:
                index = LocalSqliteStateIndex(connection)
                status = index.status()
                events = index.list_events(limit=10)
                source_state = index.load_source_state()
                user_cursors = index.load_user_cursors()
                verification = index.load_source_verification()
            finally:
                connection.close()

            self.assertTrue(status.initialized)
            self.assertEqual(status.event_count, 2)
            self.assertEqual([event.title for event in events], ["Second", "First"])
            self.assertEqual(source_state["dblp_ccs"]["content_hash"], "hash-1")
            self.assertEqual(user_cursors["default"]["last_pulled_at"], "2026-07-16T12:00:00+00:00")
            self.assertEqual(verification["dblp_ccs"]["status"], "ok")


def make_event(event_id: str, seen_at: str, source_id: str, title: str) -> WatchEvent:
    return WatchEvent(
        event_id=event_id,
        seen_at=seen_at,
        source_id=source_id,
        source_type="dblp",
        paper_id=f"paper_{event_id}",
        title=title,
        link=f"https://example.com/{event_id}",
        matched_users=[],
        raw={"title": title},
    )


if __name__ == "__main__":
    unittest.main()
