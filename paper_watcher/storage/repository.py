from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from paper_watcher.models import Paper, Source


def iso_now() -> str:
    return datetime.now(UTC).isoformat()


class Repository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def upsert_sources(self, sources: list[Source]) -> None:
        for source in sources:
            self.connection.execute(
                """
                INSERT INTO sources (
                    id, name, source_type, url, feed_url, watch_url, css_selector,
                    venue_key, openreview_venue_id, mailbox_label, ccf_level, area,
                    venue_type, priority, enabled, status, tags_json, metadata_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    source_type = excluded.source_type,
                    url = excluded.url,
                    feed_url = excluded.feed_url,
                    watch_url = excluded.watch_url,
                    css_selector = excluded.css_selector,
                    venue_key = excluded.venue_key,
                    openreview_venue_id = excluded.openreview_venue_id,
                    mailbox_label = excluded.mailbox_label,
                    ccf_level = excluded.ccf_level,
                    area = excluded.area,
                    venue_type = excluded.venue_type,
                    priority = excluded.priority,
                    enabled = excluded.enabled,
                    status = excluded.status,
                    tags_json = excluded.tags_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    source.id,
                    source.name,
                    source.source_type.value,
                    str(source.url) if source.url else None,
                    str(source.feed_url) if source.feed_url else None,
                    str(source.watch_url) if source.watch_url else None,
                    source.css_selector,
                    source.venue_key,
                    source.openreview_venue_id,
                    source.mailbox_label,
                    source.ccf_level.value,
                    source.area,
                    source.venue_type.value,
                    source.priority,
                    1 if source.enabled else 0,
                    source.status.value,
                    json.dumps(source.tags, ensure_ascii=False),
                    json.dumps(
                        {
                            "schedule": source.schedule,
                            "filters": source.filters,
                            "metadata": source.metadata,
                            "notification_policy": source.notification_policy.value,
                        },
                        ensure_ascii=False,
                    ),
                    iso_now(),
                ),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO source_state (source_id) VALUES (?)",
                (source.id,),
            )
        self.connection.commit()

    def count_sources(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) AS count FROM sources").fetchone()
        return int(row["count"])

    def list_sources(self) -> list[sqlite3.Row]:
        rows = self.connection.execute(
            """
            SELECT id, name, source_type, enabled, ccf_level, area, venue_type, priority, status
            FROM sources
            ORDER BY priority DESC, id ASC
            """
        ).fetchall()
        return list(rows)

    def get_source_state(self, source_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM source_state WHERE source_id = ?",
            (source_id,),
        ).fetchone()

    def mark_source_success(self, source_id: str, *, etag: str | None, last_modified: str | None) -> None:
        self.connection.execute(
            """
            INSERT INTO source_state (source_id, last_success_at, etag, last_modified, last_error, last_error_at)
            VALUES (?, ?, ?, ?, NULL, NULL)
            ON CONFLICT(source_id) DO UPDATE SET
                last_success_at = excluded.last_success_at,
                etag = COALESCE(excluded.etag, source_state.etag),
                last_modified = COALESCE(excluded.last_modified, source_state.last_modified),
                last_error = NULL,
                last_error_at = NULL
            """,
            (source_id, iso_now(), etag, last_modified),
        )
        self.connection.commit()

    def mark_source_error(self, source_id: str, error: str) -> None:
        self.connection.execute(
            """
            INSERT INTO source_state (source_id, last_error_at, last_error)
            VALUES (?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                last_error_at = excluded.last_error_at,
                last_error = excluded.last_error
            """,
            (source_id, iso_now(), error[:2000]),
        )
        self.connection.commit()

    def upsert_paper(self, paper: Paper) -> bool:
        if not paper.id:
            raise ValueError("paper.id is required")
        existing = self.connection.execute("SELECT id FROM papers WHERE id = ?", (paper.id,)).fetchone()
        if existing:
            self.connection.execute(
                """
                UPDATE papers SET
                    title = ?,
                    normalized_title = ?,
                    authors_json = ?,
                    abstract = COALESCE(?, abstract),
                    venue = COALESCE(?, venue),
                    venue_type = ?,
                    ccf_level = ?,
                    area = COALESCE(?, area),
                    source_id = ?,
                    source_url = COALESCE(?, source_url),
                    paper_url = COALESCE(?, paper_url),
                    pdf_url = COALESCE(?, pdf_url),
                    doi = COALESCE(?, doi),
                    arxiv_id = COALESCE(?, arxiv_id),
                    dblp_key = COALESCE(?, dblp_key),
                    openreview_id = COALESCE(?, openreview_id),
                    year = COALESCE(?, year),
                    published_at = COALESCE(?, published_at),
                    last_seen_at = ?,
                    score = ?,
                    tags_json = ?,
                    summary = COALESCE(?, summary),
                    recommendation = ?,
                    raw_json = ?
                WHERE id = ?
                """,
                self._paper_values(paper, include_first_seen=False) + (paper.id,),
            )
            self.connection.commit()
            return False

        self.connection.execute(
            """
            INSERT INTO papers (
                id, title, normalized_title, authors_json, abstract, venue, venue_type,
                ccf_level, area, source_id, source_url, paper_url, pdf_url, doi,
                arxiv_id, dblp_key, openreview_id, year, published_at, first_seen_at,
                last_seen_at, score, tags_json, summary, recommendation, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (paper.id,) + self._paper_values(paper, include_first_seen=True),
        )
        self.connection.commit()
        return True

    def _paper_values(self, paper: Paper, *, include_first_seen: bool) -> tuple:
        values = (
            paper.title,
            paper.normalized_title,
            json.dumps(paper.authors, ensure_ascii=False),
            paper.abstract,
            paper.venue,
            paper.venue_type.value,
            paper.ccf_level.value,
            paper.area,
            paper.source_id,
            paper.source_url,
            paper.paper_url,
            paper.pdf_url,
            paper.doi,
            paper.arxiv_id,
            paper.dblp_key,
            paper.openreview_id,
            paper.year,
            paper.published_at.isoformat() if paper.published_at else None,
        )
        if include_first_seen:
            values += (paper.first_seen_at.isoformat(),)
        values += (
            paper.last_seen_at.isoformat(),
            paper.score,
            json.dumps(paper.tags, ensure_ascii=False),
            paper.summary,
            paper.recommendation.value,
            json.dumps(paper.raw, ensure_ascii=False, default=str),
        )
        return values

    def record_paper_seen(self, paper: Paper, source_item_id: str) -> None:
        if not paper.id:
            raise ValueError("paper.id is required")
        self.connection.execute(
            """
            INSERT INTO paper_source_seen (
                paper_id, source_id, source_item_id, source_url, first_seen_at, last_seen_at, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_id, source_id, source_item_id) DO UPDATE SET
                source_url = excluded.source_url,
                last_seen_at = excluded.last_seen_at,
                raw_json = excluded.raw_json
            """,
            (
                paper.id,
                paper.source_id,
                source_item_id or "",
                paper.paper_url or paper.source_url,
                paper.first_seen_at.isoformat(),
                paper.last_seen_at.isoformat(),
                json.dumps(paper.raw, ensure_ascii=False, default=str),
            ),
        )
        self.connection.commit()

    def create_scan_run(self, run_id: str, started_at: datetime, source_id: str | None) -> None:
        self.connection.execute(
            """
            INSERT INTO scan_runs (id, started_at, status, source_id)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, started_at.isoformat(), "running", source_id),
        )
        self.connection.commit()

    def finish_scan_run(
        self,
        run_id: str,
        finished_at: datetime,
        *,
        status: str,
        fetched_count: int,
        new_count: int,
        updated_count: int,
        error_count: int,
        log: str | None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE scan_runs SET
                finished_at = ?,
                status = ?,
                fetched_count = ?,
                new_count = ?,
                updated_count = ?,
                error_count = ?,
                log = ?
            WHERE id = ?
            """,
            (
                finished_at.isoformat(),
                status,
                fetched_count,
                new_count,
                updated_count,
                error_count,
                log,
                run_id,
            ),
        )
        self.connection.commit()

    def count_papers(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) AS count FROM papers").fetchone()
        return int(row["count"])

    def list_papers(self, *, recommendation: str | None = None, limit: int = 20) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[object] = []
        if recommendation:
            clauses.append("recommendation = ?")
            params.append(recommendation)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        return list(
            self.connection.execute(
                f"""
                SELECT id, title, authors_json, venue, ccf_level, score, recommendation, paper_url, published_at
                FROM papers
                {where}
                ORDER BY score DESC, published_at DESC, first_seen_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        )

    def search_papers(self, query: str, *, limit: int = 20) -> list[sqlite3.Row]:
        pattern = f"%{query.lower()}%"
        return list(
            self.connection.execute(
                """
                SELECT id, title, authors_json, venue, ccf_level, score, recommendation, paper_url, published_at
                FROM papers
                WHERE lower(title) LIKE ? OR lower(COALESCE(abstract, '')) LIKE ?
                ORDER BY score DESC, published_at DESC, first_seen_at DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
        )
