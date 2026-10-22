from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from paper_watcher.storage.file_storage import FileStateStore, WatchEvent


def iso_now() -> str:
    return datetime.now(UTC).isoformat()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS state_events (
    event_id TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    title TEXT NOT NULL,
    link TEXT,
    matched_users_json TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_state_events_seen_at
    ON state_events(seen_at DESC, event_id DESC);

CREATE INDEX IF NOT EXISTS idx_state_events_source_seen_at
    ON state_events(source_id, seen_at DESC, event_id DESC);

CREATE INDEX IF NOT EXISTS idx_state_events_paper_id
    ON state_events(paper_id);

CREATE TABLE IF NOT EXISTS state_source_state (
    source_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    last_scan_at TEXT,
    last_success_at TEXT,
    last_error_at TEXT,
    last_error TEXT,
    next_scan_after TEXT,
    content_hash TEXT,
    etag TEXT,
    last_modified TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_state_source_state_next_scan_after
    ON state_source_state(next_scan_after);

CREATE TABLE IF NOT EXISTS state_user_cursors (
    user_id TEXT PRIMARY KEY,
    last_pulled_at TEXT,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state_source_verification (
    source_id TEXT PRIMARY KEY,
    status TEXT,
    checked_at TEXT,
    error TEXT,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state_index_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class LocalIndexSyncResult:
    event_count: int
    source_state_count: int
    user_cursor_count: int
    source_verification_count: int
    synced_at: str


@dataclass(frozen=True)
class LocalIndexStatus:
    initialized: bool
    last_synced_at: str | None
    event_count: int
    source_state_count: int
    user_cursor_count: int
    source_verification_count: int


class LocalSqliteStateIndex:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def ensure_schema(self) -> None:
        self.connection.executescript(SCHEMA_SQL)
        self.connection.commit()

    def rebuild_from_store(self, store: FileStateStore) -> LocalIndexSyncResult:
        store.ensure()
        self.ensure_schema()
        events = store.load_events()
        source_state = store.load_source_state()
        user_cursors = store.load_user_cursors()
        source_verification = store.load_source_verification()
        synced_at = iso_now()

        with self.connection:
            self.connection.execute("DELETE FROM state_events")
            self.connection.execute("DELETE FROM state_source_state")
            self.connection.execute("DELETE FROM state_user_cursors")
            self.connection.execute("DELETE FROM state_source_verification")
            self.connection.execute("DELETE FROM state_index_meta")

            for event in events:
                self._insert_event(event)

            for source_id, payload in source_state.items():
                self.connection.execute(
                    """
                    INSERT INTO state_source_state (
                        source_id, payload_json, last_scan_at, last_success_at, last_error_at,
                        last_error, next_scan_after, content_hash, etag, last_modified, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        self._json_dump(payload),
                        self._optional_text(payload, "last_scan_at"),
                        self._optional_text(payload, "last_success_at"),
                        self._optional_text(payload, "last_error_at"),
                        self._optional_text(payload, "last_error"),
                        self._optional_text(payload, "next_scan_after"),
                        self._optional_text(payload, "content_hash"),
                        self._optional_text(payload, "etag"),
                        self._optional_text(payload, "last_modified"),
                        synced_at,
                    ),
                )

            for user_id, payload in user_cursors.items():
                self.connection.execute(
                    """
                    INSERT INTO state_user_cursors (
                        user_id, last_pulled_at, payload_json, updated_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        self._optional_text(payload, "last_pulled_at"),
                        self._json_dump(payload),
                        synced_at,
                    ),
                )

            for source_id, payload in source_verification.items():
                self.connection.execute(
                    """
                    INSERT INTO state_source_verification (
                        source_id, status, checked_at, error, payload_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        self._optional_text(payload, "status"),
                        self._optional_text(payload, "checked_at"),
                        self._optional_text(payload, "error"),
                        self._json_dump(payload),
                        synced_at,
                    ),
                )

            self._set_meta("last_synced_at", synced_at)
            self._set_meta("event_count", str(len(events)))
            self._set_meta("source_state_count", str(len(source_state)))
            self._set_meta("user_cursor_count", str(len(user_cursors)))
            self._set_meta("source_verification_count", str(len(source_verification)))

        return LocalIndexSyncResult(
            event_count=len(events),
            source_state_count=len(source_state),
            user_cursor_count=len(user_cursors),
            source_verification_count=len(source_verification),
            synced_at=synced_at,
        )

    def status(self) -> LocalIndexStatus:
        initialized = self._table_exists("state_index_meta")
        if not initialized:
            return LocalIndexStatus(
                initialized=False,
                last_synced_at=None,
                event_count=0,
                source_state_count=0,
                user_cursor_count=0,
                source_verification_count=0,
            )
        return LocalIndexStatus(
            initialized=True,
            last_synced_at=self._get_meta("last_synced_at"),
            event_count=self._count_rows("state_events"),
            source_state_count=self._count_rows("state_source_state"),
            user_cursor_count=self._count_rows("state_user_cursors"),
            source_verification_count=self._count_rows("state_source_verification"),
        )

    def list_events(self, *, limit: int = 10, source_id: str | None = None) -> list[WatchEvent]:
        if limit <= 0:
            return []
        clauses = []
        params: list[Any] = []
        if source_id:
            clauses.append("source_id = ?")
            params.append(source_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.connection.execute(
            f"""
            SELECT event_id, seen_at, source_id, source_type, paper_id, title, link,
                   matched_users_json, raw_json
            FROM state_events
            {where}
            ORDER BY seen_at DESC, event_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def load_source_state(self) -> dict[str, dict[str, Any]]:
        if not self._table_exists("state_source_state"):
            return {}
        rows = self.connection.execute("SELECT source_id, payload_json FROM state_source_state").fetchall()
        return {row["source_id"]: self._json_loads(row["payload_json"]) for row in rows}

    def load_user_cursors(self) -> dict[str, dict[str, Any]]:
        if not self._table_exists("state_user_cursors"):
            return {}
        rows = self.connection.execute("SELECT user_id, payload_json FROM state_user_cursors").fetchall()
        return {row["user_id"]: self._json_loads(row["payload_json"]) for row in rows}

    def load_source_verification(self) -> dict[str, dict[str, Any]]:
        if not self._table_exists("state_source_verification"):
            return {}
        rows = self.connection.execute("SELECT source_id, payload_json FROM state_source_verification").fetchall()
        return {row["source_id"]: self._json_loads(row["payload_json"]) for row in rows}

    def _insert_event(self, event: WatchEvent) -> None:
        self.connection.execute(
            """
            INSERT INTO state_events (
                event_id, seen_at, source_id, source_type, paper_id, title, link,
                matched_users_json, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.seen_at,
                event.source_id,
                event.source_type,
                event.paper_id,
                event.title,
                event.link,
                self._json_dump(event.matched_users),
                self._json_dump(event.raw),
            ),
        )

    def _row_to_event(self, row: sqlite3.Row) -> WatchEvent:
        return WatchEvent(
            event_id=row["event_id"],
            seen_at=row["seen_at"],
            source_id=row["source_id"],
            source_type=row["source_type"],
            paper_id=row["paper_id"],
            title=row["title"],
            link=row["link"],
            matched_users=self._json_loads(row["matched_users_json"]),
            raw=self._json_loads(row["raw_json"]),
        )

    def _count_rows(self, table_name: str) -> int:
        row = self.connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
        return int(row["count"])

    def _set_meta(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO state_index_meta (key, value) VALUES (?, ?)",
            (key, value),
        )

    def _get_meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM state_index_meta WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        return row["value"]

    def _table_exists(self, name: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        return row is not None

    def _json_dump(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _json_loads(self, value: str | None) -> Any:
        if not value:
            return {}
        return json.loads(value)

    def _optional_text(self, payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            return str(value)
        return value or None
