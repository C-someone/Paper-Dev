from __future__ import annotations

import sqlite3


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    url TEXT,
    feed_url TEXT,
    watch_url TEXT,
    css_selector TEXT,
    venue_key TEXT,
    openreview_venue_id TEXT,
    mailbox_label TEXT,
    ccf_level TEXT,
    area TEXT,
    venue_type TEXT,
    priority INTEGER,
    enabled INTEGER DEFAULT 1,
    status TEXT,
    tags_json TEXT,
    metadata_json TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_state (
    source_id TEXT PRIMARY KEY,
    last_success_at TEXT,
    last_error_at TEXT,
    last_error TEXT,
    etag TEXT,
    last_modified TEXT,
    content_hash TEXT,
    last_changed_at TEXT,
    cursor TEXT,
    metadata_json TEXT,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    authors_json TEXT,
    abstract TEXT,
    venue TEXT,
    venue_type TEXT,
    ccf_level TEXT,
    area TEXT,
    source_id TEXT,
    source_url TEXT,
    paper_url TEXT,
    pdf_url TEXT,
    doi TEXT,
    arxiv_id TEXT,
    dblp_key TEXT,
    openreview_id TEXT,
    year INTEGER,
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    score REAL DEFAULT 0,
    tags_json TEXT,
    summary TEXT,
    recommendation TEXT,
    raw_json TEXT,
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE INDEX IF NOT EXISTS idx_papers_normalized_title ON papers(normalized_title);
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_arxiv_id ON papers(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_papers_dblp_key ON papers(dblp_key);
CREATE INDEX IF NOT EXISTS idx_papers_openreview_id ON papers(openreview_id);
CREATE INDEX IF NOT EXISTS idx_papers_recommendation ON papers(recommendation);

CREATE TABLE IF NOT EXISTS paper_source_seen (
    paper_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_item_id TEXT NOT NULL DEFAULT '',
    source_url TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    raw_json TEXT,
    PRIMARY KEY (paper_id, source_id, source_item_id),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT,
    source_id TEXT,
    fetched_count INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    updated_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    log TEXT,
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

INSERT OR IGNORE INTO schema_migrations (version) VALUES (1);
"""


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    connection.commit()
