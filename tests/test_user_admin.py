from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from paper_watcher.config_loader import load_config
from paper_watcher.user_admin import list_users_for_admin, subscribe_user_to_source, unsubscribe_user_from_source


class UserAdminTests(unittest.TestCase):
    def test_list_users_reports_subscriptions(self) -> None:
        config = load_config(Path("config"))

        result = list_users_for_admin(config)

        self.assertIn("root", result.response_text)
        self.assertIn("dblp_ccs", result.response_text)

    def test_subscribe_and_unsubscribe_user_to_website_watch_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            config_dir = Path(directory_name) / "config"
            shutil.copytree(Path("config"), config_dir)
            config = load_config(config_dir)

            subscribe = subscribe_user_to_source(
                config,
                user_id="default",
                source_id="ndss_2026_accepted",
            )
            self.assertIn("website_watch", subscribe.response_text)

            config = load_config(config_dir)
            default = next(user for user in config.users.users if user.id == "default")
            self.assertTrue(
                any(item.get("source_id") == "ndss_2026_accepted" for item in default.subscriptions.website_watch)
            )

            unsubscribe = unsubscribe_user_from_source(
                config,
                user_id="default",
                source_id="ndss_2026_accepted",
            )
            self.assertIn("Unsubscribed default", unsubscribe.response_text)

            config = load_config(config_dir)
            default = next(user for user in config.users.users if user.id == "default")
            self.assertFalse(
                any(item.get("source_id") == "ndss_2026_accepted" for item in default.subscriptions.website_watch)
            )


if __name__ == "__main__":
    unittest.main()
