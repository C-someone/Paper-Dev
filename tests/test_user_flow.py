from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from paper_watcher.config_loader import load_config
from paper_watcher.foreground import pull_user_updates
from paper_watcher.storage.file_storage import FileStateStore, WatchEvent


class UserFlowTests(unittest.TestCase):
    def test_user_config_loads(self) -> None:
        config = load_config(Path("config"))

        user_ids = {user.id for user in config.users.users}
        self.assertIn("root", user_ids)
        self.assertIn("default", user_ids)
        self.assertIn("debug_user", user_ids)

    def test_foreground_pull_updates_cursor(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            state_dir = Path(directory_name)
            config = replace(
                config,
                settings=replace(config.settings, state_dir=state_dir),
            )
            store = FileStateStore(state_dir)
            store.append_events(
                [
                    WatchEvent(
                        event_id="evt_1",
                        seen_at="2026-07-15T00:00:00+00:00",
                        source_id="dblp_ccs",
                        source_type="dblp",
                        paper_id="paper_1",
                        title="A Useful Paper",
                        link="https://example.com/paper",
                        matched_users=[],
                        raw={},
                    )
                ]
            )

            first = pull_user_updates(config, "default")
            second = pull_user_updates(config, "default")

            self.assertEqual(len(first.events), 1)
            self.assertIn("A Useful Paper", first.response_text)
            self.assertEqual(len(second.events), 0)
            self.assertIn("No new papers", second.response_text)

    def test_foreground_pull_pages_by_last_delivered_event(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            state_dir = Path(directory_name)
            default_user = next(user for user in config.users.users if user.id == "default")
            user = replace(default_user, delivery=replace(default_user.delivery, max_items=1))
            users = replace(config.users, users=[user])
            config = replace(
                config,
                users=users,
                settings=replace(config.settings, state_dir=state_dir),
            )
            store = FileStateStore(state_dir)
            store.append_events(
                [
                    WatchEvent(
                        event_id="evt_1",
                        seen_at="2026-07-15T00:00:00+00:00",
                        source_id="dblp_ccs",
                        source_type="dblp",
                        paper_id="paper_1",
                        title="First Paper",
                        link="https://example.com/first",
                        matched_users=[],
                        raw={},
                    ),
                    WatchEvent(
                        event_id="evt_2",
                        seen_at="2026-07-15T00:00:01+00:00",
                        source_id="dblp_ccs",
                        source_type="dblp",
                        paper_id="paper_2",
                        title="Second Paper",
                        link="https://example.com/second",
                        matched_users=[],
                        raw={},
                    ),
                ]
            )

            first = pull_user_updates(config, "default")
            second = pull_user_updates(config, "default")

            self.assertEqual([event.title for event in first.events], ["First Paper"])
            self.assertEqual([event.title for event in second.events], ["Second Paper"])

    def test_peek_and_json_do_not_update_cursor(self) -> None:
        config = load_config(Path("config"))

        with tempfile.TemporaryDirectory() as directory_name:
            state_dir = Path(directory_name)
            config = replace(config, settings=replace(config.settings, state_dir=state_dir))
            store = FileStateStore(state_dir)
            store.append_events(
                [
                    WatchEvent(
                        event_id="evt_1",
                        seen_at="2026-07-15T00:00:00+00:00",
                        source_id="debug_fake_rss",
                        source_type="debug",
                        paper_id="paper_1",
                        title="Debug Paper",
                        link="https://example.com/debug",
                        matched_users=[],
                        raw={},
                    )
                ]
            )

            first = pull_user_updates(
                config,
                "debug_user",
                update_cursor=False,
                output_format="json",
                source_id="debug_fake_rss",
                limit=1,
            )
            second = pull_user_updates(config, "debug_user", update_cursor=False, source_id="debug_fake_rss", limit=1)

            self.assertIn('"count": 1', first.response_text)
            self.assertEqual(len(second.events), 1)


if __name__ == "__main__":
    unittest.main()
