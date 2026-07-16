from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_watcher.background import run_background_loop


class BackgroundLoopTests(unittest.TestCase):
    def test_loop_reloads_changed_valid_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            config_dir = copy_config(Path(directory_name))
            seen_user_agents: list[str] = []

            def fake_scan(config, **kwargs):
                seen_user_agents.append(config.settings.user_agent)
                return (0, 0, 0)

            def fake_sleep(seconds: float) -> None:
                settings_path = config_dir / "settings.yaml"
                settings_path.write_text(
                    settings_path.read_text(encoding="utf-8").replace(
                        "user_agent: PaperWatcher/0.1",
                        "user_agent: PaperWatcherTest/0.2",
                    ),
                    encoding="utf-8",
                )

            with patch("paper_watcher.background.run_background_once", side_effect=fake_scan):
                run_background_loop(
                    config_dir,
                    interval_seconds=0,
                    watch_config=True,
                    sleep_fn=fake_sleep,
                    max_iterations=2,
                )

            self.assertEqual(seen_user_agents, ["PaperWatcher/0.1", "PaperWatcherTest/0.2"])

    def test_loop_keeps_old_config_and_logs_bad_reload_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            config_dir = copy_config(Path(directory_name))
            seen_user_agents: list[str] = []
            invalid_written = False

            def fake_scan(config, **kwargs):
                seen_user_agents.append(config.settings.user_agent)
                return (0, 0, 0)

            def fake_sleep(seconds: float) -> None:
                nonlocal invalid_written
                if invalid_written:
                    return
                invalid_written = True
                (config_dir / "users.yaml").write_text("users: [\n", encoding="utf-8")

            with patch("paper_watcher.background.run_background_once", side_effect=fake_scan):
                run_background_loop(
                    config_dir,
                    interval_seconds=0,
                    watch_config=True,
                    sleep_fn=fake_sleep,
                    max_iterations=3,
                )

            self.assertEqual(seen_user_agents, ["PaperWatcher/0.1", "PaperWatcher/0.1", "PaperWatcher/0.1"])
            error_log = Path(directory_name) / "state" / "config_reload_errors.jsonl"
            lines = [line for line in error_log.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)
            self.assertIn("invalid YAML", lines[0])


def copy_config(directory_name: Path) -> Path:
    source = Path("config")
    target = directory_name / "config"
    shutil.copytree(source, target)
    return target


if __name__ == "__main__":
    unittest.main()
