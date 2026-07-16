from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WatchEvent:
    event_id: str
    seen_at: str
    source_id: str
    source_type: str
    paper_id: str
    title: str
    link: str | None
    matched_users: list[str]
    raw: dict[str, Any]


class FileStateStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.events_path = state_dir / "events.jsonl"
        self.source_state_path = state_dir / "source_state.json"
        self.user_cursors_path = state_dir / "user_cursors.json"
        self.source_verification_path = state_dir / "source_verification.json"
        self.config_reload_errors_path = state_dir / "config_reload_errors.jsonl"

    def ensure(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if not self.events_path.exists():
            self.events_path.write_text("", encoding="utf-8")
        if not self.source_state_path.exists():
            self._write_json(self.source_state_path, {})
        if not self.user_cursors_path.exists():
            self._write_json(self.user_cursors_path, {})
        if not self.source_verification_path.exists():
            self._write_json(self.source_verification_path, {})
        if not self.config_reload_errors_path.exists():
            self.config_reload_errors_path.write_text("", encoding="utf-8")

    def load_source_state(self) -> dict[str, dict[str, Any]]:
        self.ensure()
        return self._read_json(self.source_state_path)

    def save_source_state(self, state: dict[str, dict[str, Any]]) -> None:
        self.ensure()
        self._write_json(self.source_state_path, state)

    def append_events(self, events: list[WatchEvent]) -> None:
        self.ensure()
        if not events:
            return
        with self.events_path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(asdict(event), ensure_ascii=False, sort_keys=True))
                handle.write("\n")

    def load_events(self) -> list[WatchEvent]:
        self.ensure()
        events: list[WatchEvent] = []
        with self.events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                events.append(WatchEvent(**data))
        return events

    def known_paper_ids(self) -> set[str]:
        return {event.paper_id for event in self.load_events()}

    def load_user_cursors(self) -> dict[str, dict[str, Any]]:
        self.ensure()
        return self._read_json(self.user_cursors_path)

    def save_user_cursors(self, cursors: dict[str, dict[str, Any]]) -> None:
        self.ensure()
        self._write_json(self.user_cursors_path, cursors)

    def update_user_cursor_now(self, user_id: str) -> None:
        self.update_user_cursor(user_id, datetime.now(UTC).isoformat())

    def update_user_cursor(self, user_id: str, last_pulled_at: str) -> None:
        cursors = self.load_user_cursors()
        cursors[user_id] = {"last_pulled_at": last_pulled_at}
        self.save_user_cursors(cursors)

    def load_source_verification(self) -> dict[str, dict[str, Any]]:
        self.ensure()
        return self._read_json(self.source_verification_path)

    def save_source_verification(self, verification: dict[str, dict[str, Any]]) -> None:
        self.ensure()
        self._write_json(self.source_verification_path, verification)

    def append_config_reload_error(self, error: dict[str, Any]) -> None:
        self.ensure()
        with self.config_reload_errors_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(error, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return {}
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError(f"JSON file must contain an object: {path}")
        return data

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
