from __future__ import annotations

import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

from paper_watcher.models import AppConfig
from paper_watcher.settings import resolve_project_path
from paper_watcher.storage.file_storage import FileStateStore, WatchEvent


def run_debug_server(config: AppConfig, host: str = "127.0.0.1", port: int = 8765) -> None:
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    store.ensure()
    source_ids = {source.id for source in config.sources.sources}

    class Handler(DebugUpdateHandler):
        state_store = store
        known_source_ids = source_ids

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Debug update server listening on http://{host}:{port}")
    print("POST /debug/update with JSON: title, link, source_id")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDebug update server stopped.")
    finally:
        server.server_close()


class DebugUpdateHandler(BaseHTTPRequestHandler):
    state_store: FileStateStore
    known_source_ids: set[str]

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write_json(200, {"ok": True})
            return
        self._write_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/debug/update":
            self._write_json(404, {"error": "not found"})
            return

        try:
            payload = self._read_payload()
            event = self._payload_to_event(payload)
        except ValueError as exc:
            self._write_json(400, {"error": str(exc)})
            return

        self.state_store.append_events([event])
        self._write_json(
            201,
            {
                "ok": True,
                "event_id": event.event_id,
                "source_id": event.source_id,
                "matched_users": event.matched_users,
            },
        )

    def log_message(self, format: str, *args) -> None:
        return

    def _read_payload(self) -> dict:
        length_text = self.headers.get("Content-Length")
        if not length_text:
            raise ValueError("missing Content-Length")
        try:
            length = int(length_text)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length <= 0 or length > 1024 * 1024:
            raise ValueError("invalid payload size")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        return payload

    def _payload_to_event(self, payload: dict) -> WatchEvent:
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title is required")
        link = payload.get("link")
        if link is not None and not isinstance(link, str):
            raise ValueError("link must be a string")
        paper_id = payload.get("paper_id")
        if paper_id is not None and not isinstance(paper_id, str):
            raise ValueError("paper_id must be a string")
        source_id = payload.get("source_id", "debug_fake_rss")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id must be a string")
        if source_id not in self.known_source_ids:
            raise ValueError(f"unknown source_id: {source_id}")
        raw = payload.get("raw", {})
        if not isinstance(raw, dict):
            raise ValueError("raw must be a JSON object")

        return WatchEvent(
            event_id=f"evt_debug_{uuid4().hex}",
            seen_at=datetime.now(UTC).isoformat(),
            source_id=source_id,
            source_type="debug",
            paper_id=paper_id or f"debug_{uuid4().hex}",
            title=title.strip(),
            link=link.strip() if isinstance(link, str) and link.strip() else None,
            matched_users=[],
            raw=raw,
        )

    def _write_json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
