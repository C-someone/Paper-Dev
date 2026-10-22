from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml

from paper_watcher.conference_discovery import SourceCandidate, SourceCandidateStore
from paper_watcher.monitor_web import MonitorWebHandler, build_monitor_payload
from paper_watcher.storage.file_storage import FileStateStore


class MonitorWebTests(unittest.TestCase):
    def test_build_monitor_payload_contains_dashboard_sections(self) -> None:
        payload = build_monitor_payload(Path("config"), "event_limit=5")

        self.assertIn("status", payload)
        self.assertIn("events", payload)
        self.assertIn("conference_pages", payload)
        self.assertIn("sources", payload)
        self.assertIn("source_health", payload)
        self.assertGreaterEqual(payload["status"]["sources"]["total"], 1)

    def test_api_requires_token_when_configured(self) -> None:
        class Handler(MonitorWebHandler):
            active_config_dir = Path("config")
            access_token = "test-token"

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with self.assertRaises(HTTPError) as context:
                urlopen(base_url + "/api/dashboard", timeout=5)
            self.assertEqual(context.exception.code, 401)

            request = Request(base_url + "/api/dashboard", headers={"X-PaperWatcher-Token": "test-token"})
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertIn("status", payload)
        finally:
            server.shutdown()
            server.server_close()

    def test_api_can_approve_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            config_dir = root / "config"
            state_dir = root / "state"
            shutil.copytree(Path("config"), config_dir)
            _set_state_dir(config_dir, state_dir)
            candidate = _candidate()
            SourceCandidateStore(FileStateStore(state_dir)).upsert_candidates([candidate])

            class Handler(MonitorWebHandler):
                active_config_dir = config_dir
                access_token = "test-token"

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                request = Request(
                    base_url + "/api/candidates/approve",
                    data=json.dumps({"candidate_id": candidate.candidate_id, "actor": "astrbot:test-user"}).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-PaperWatcher-Token": "test-token",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))

                self.assertTrue(payload["ok"])
                self.assertEqual(payload["status"], "approved")
                self.assertEqual(payload["source_id"], candidate.source_id)
                self.assertEqual(payload["action"]["actor"], "astrbot:test-user")
                self.assertEqual(payload["action"]["action"], "approve")

                sources = yaml.safe_load((config_dir / "sources.yaml").read_text(encoding="utf-8"))
                users = yaml.safe_load((config_dir / "users.yaml").read_text(encoding="utf-8"))
                self.assertIn(candidate.source_id, {source["id"] for source in sources["sources"]})
                root_user = next(user for user in users["users"] if user["id"] == "root")
                root_sources = {item["source_id"] for item in root_user["subscriptions"]["website_watch"]}
                self.assertIn(candidate.source_id, root_sources)
                actions = FileStateStore(state_dir).load_candidate_actions()
                self.assertEqual(len(actions), 1)
                self.assertEqual(actions[0]["candidate_id"], candidate.candidate_id)
                self.assertEqual(actions[0]["actor"], "astrbot:test-user")
            finally:
                server.shutdown()
                server.server_close()

    def test_api_lists_and_rejects_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            config_dir = root / "config"
            state_dir = root / "state"
            shutil.copytree(Path("config"), config_dir)
            _set_state_dir(config_dir, state_dir)
            candidate = _candidate()
            SourceCandidateStore(FileStateStore(state_dir)).upsert_candidates([candidate])

            class Handler(MonitorWebHandler):
                active_config_dir = config_dir
                access_token = "test-token"

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                request = Request(base_url + "/api/candidates?status=pending&limit=5", headers={"X-PaperWatcher-Token": "test-token"})
                with urlopen(request, timeout=5) as response:
                    listed = json.loads(response.read().decode("utf-8"))
                self.assertEqual(listed["count"], 1)
                self.assertEqual(listed["candidates"][0]["candidate_id"], candidate.candidate_id)

                request = Request(
                    base_url + "/api/candidates/reject",
                    data=json.dumps(
                        {
                            "candidate_id": candidate.candidate_id,
                            "reason": "wrong year",
                            "actor": "astrbot:test-user",
                        }
                    ).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-PaperWatcher-Token": "test-token",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    rejected = json.loads(response.read().decode("utf-8"))
                self.assertTrue(rejected["ok"])
                self.assertEqual(rejected["status"], "rejected")
                self.assertEqual(rejected["candidate"]["status"], "rejected")
                self.assertEqual(rejected["action"]["reason"], "wrong year")

                request = Request(base_url + "/api/candidates?status=pending", headers={"X-PaperWatcher-Token": "test-token"})
                with urlopen(request, timeout=5) as response:
                    pending = json.loads(response.read().decode("utf-8"))
                self.assertEqual(pending["count"], 0)

                actions = FileStateStore(state_dir).load_candidate_actions()
                self.assertEqual(len(actions), 1)
                self.assertEqual(actions[0]["action"], "reject")
                self.assertEqual(actions[0]["reason"], "wrong year")
            finally:
                server.shutdown()
                server.server_close()


def _set_state_dir(config_dir: Path, state_dir: Path) -> None:
    settings_path = config_dir / "settings.yaml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["paths"]["state_dir"] = str(state_dir)
    settings_path.write_text(yaml.safe_dump(settings, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _candidate() -> SourceCandidate:
    return SourceCandidate(
        candidate_id="cand_web_ndss_2026",
        venue_id="ndss",
        year=2026,
        kind="accepted_papers",
        url="https://example.test/ndss2026/accepted-papers/",
        source_id="ndss_2026_web_accepted",
        source_name="NDSS 2026 Web Accepted Papers",
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
