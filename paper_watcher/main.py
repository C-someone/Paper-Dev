from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

from paper_watcher.agent_review.search_review import (
    list_search_reviews,
    review_search_results,
)
from paper_watcher.background import run_background_loop, run_background_once
from paper_watcher.conference_discovery import (
    approve_candidate,
    discover_conferences,
    list_candidates,
    reject_candidate,
)
from paper_watcher.conference_signal_review import (
    detect_conference_signal,
    render_signal_review_results,
    review_conference_signal,
)
from paper_watcher.conference_review_batch import review_conferences_batch
from paper_watcher.conference_review_promoter import promote_conference_review
from paper_watcher.conference_search import search_and_review_conference, search_conference
from paper_watcher.config_loader import ConfigError, load_config
from paper_watcher.debug_server import run_debug_server
from paper_watcher.events import list_global_events
from paper_watcher.foreground import pull_user_updates, reset_user_cursor
from paper_watcher.monitor_web import run_monitor_web
from paper_watcher.settings import resolve_project_path
from paper_watcher.scanner import scan_once
from paper_watcher.source_health import list_source_health
from paper_watcher.storage.file_storage import FileStateStore
from paper_watcher.storage.database import connect
from paper_watcher.storage.index_store import LocalSqliteStateIndex
from paper_watcher.storage.migrations import init_db as apply_schema
from paper_watcher.storage.repository import Repository
from paper_watcher.status_dashboard import build_status_dashboard
from paper_watcher.user_admin import list_users_for_admin, subscribe_user_to_source, unsubscribe_user_from_source
from paper_watcher.verifier import verify_sources


def _load_or_exit(config_dir: Path):
    try:
        return load_config(config_dir)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


def validate_config(config_dir: Path = Path("config")) -> None:
    """Validate YAML configuration files without touching the database."""
    config = _load_or_exit(config_dir)
    enabled_count = sum(1 for source in config.sources.sources if source.enabled)
    print("Configuration is valid.")
    print(f"Sources: {len(config.sources.sources)} total, {enabled_count} enabled")
    print(f"Venues: {len(config.venues.venues)}")
    print(f"Users: {len(config.users.users)}")


def init_db(config_dir: Path = Path("config")) -> None:
    """Create or update SQLite tables and sync configured sources."""
    config = _load_or_exit(config_dir)
    db_path = resolve_project_path(config, config.settings.database_path)
    connection = connect(db_path)
    try:
        apply_schema(connection)
        repository = Repository(connection)
        repository.upsert_sources(config.sources.sources)
        print(f"Database initialized: {db_path}")
        print(f"Sources synced: {repository.count_sources()}")
    finally:
        connection.close()


def index_sync(config_dir: Path = Path("config")) -> None:
    """Rebuild the local SQLite index from file-backed state."""
    config = _load_or_exit(config_dir)
    db_path = resolve_project_path(config, config.settings.database_path)
    state_store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    connection = connect(db_path)
    try:
        index = LocalSqliteStateIndex(connection)
        result = index.rebuild_from_store(state_store)
    finally:
        connection.close()

    print(f"Index synced: {db_path}")
    print(f"Synced at: {result.synced_at}")
    print(f"Events: {result.event_count}")
    print(f"Source states: {result.source_state_count}")
    print(f"User cursors: {result.user_cursor_count}")
    print(f"Source verification rows: {result.source_verification_count}")


def index_status(config_dir: Path = Path("config")) -> None:
    """Show the current local SQLite index status."""
    config = _load_or_exit(config_dir)
    db_path = resolve_project_path(config, config.settings.database_path)
    if not db_path.exists():
        print(f"Index database does not exist yet: {db_path}", file=sys.stderr)
        print("Run: paperwatcher index sync", file=sys.stderr)
        raise SystemExit(1)

    connection = connect(db_path)
    try:
        index = LocalSqliteStateIndex(connection)
        status = index.status()
    finally:
        connection.close()

    if not status.initialized:
        print(f"Index schema not initialized yet: {db_path}", file=sys.stderr)
        print("Run: paperwatcher index sync", file=sys.stderr)
        raise SystemExit(1)

    print(f"Index database: {db_path}")
    print(f"Last synced at: {status.last_synced_at or 'unknown'}")
    print(f"Events: {status.event_count}")
    print(f"Source states: {status.source_state_count}")
    print(f"User cursors: {status.user_cursor_count}")
    print(f"Source verification rows: {status.source_verification_count}")


def list_sources(config_dir: Path = Path("config")) -> None:
    """List sources currently loaded into the SQLite database."""
    config = _load_or_exit(config_dir)
    db_path = resolve_project_path(config, config.settings.database_path)
    if not db_path.exists():
        print(f"Database does not exist yet: {db_path}", file=sys.stderr)
        print("Run: paperwatcher init-db", file=sys.stderr)
        raise SystemExit(1)

    connection = connect(db_path)
    try:
        repository = Repository(connection)
        rows = repository.list_sources()
    finally:
        connection.close()

    if not rows:
        print("No sources found. Run: paperwatcher init-db")
        return

    for row in rows:
        enabled = "enabled" if row["enabled"] else "disabled"
        print(
            f"{row['id']} | {row['source_type']} | {enabled} | "
            f"priority={row['priority']} | ccf={row['ccf_level']} | {row['name']}"
        )


def scan(config_dir: Path = Path("config"), source_id: str | None = None) -> None:
    config = _load_or_exit(config_dir)
    db_path = resolve_project_path(config, config.settings.database_path)
    connection = connect(db_path)
    try:
        apply_schema(connection)
        repository = Repository(connection)
        repository.upsert_sources(config.sources.sources)
        summary = scan_once(config, repository, source_id=source_id)
    finally:
        connection.close()

    print(f"Scan run: {summary.run_id}")
    print(f"Scanned sources: {summary.scanned_sources}")
    print(f"Fetched items: {summary.fetched_count}")
    print(f"New papers: {summary.new_count}")
    print(f"Updated papers: {summary.updated_count}")
    print(f"Errors: {summary.error_count}")
    print(f"Report: {summary.report_path}")


def list_papers(config_dir: Path = Path("config"), recommendation: str | None = None, limit: int = 20) -> None:
    repository, connection = _open_repository(config_dir)
    try:
        rows = repository.list_papers(recommendation=recommendation, limit=limit)
    finally:
        connection.close()
    _print_paper_rows(rows)


def search_papers(config_dir: Path = Path("config"), query: str = "", limit: int = 20) -> None:
    repository, connection = _open_repository(config_dir)
    try:
        rows = repository.search_papers(query, limit=limit)
    finally:
        connection.close()
    _print_paper_rows(rows)


def background_once(
    config_dir: Path = Path("config"),
    *,
    source_id: str | None = None,
    include_disabled: bool = False,
    enable_signal_review: bool = False,
    signal_reviewer: str = "auto",
    signal_review_num_results: int = 10,
) -> None:
    config = _load_or_exit(config_dir)
    scanned, new_events, errors = run_background_once(
        config,
        source_id=source_id,
        include_disabled=include_disabled,
        enable_signal_review=enable_signal_review,
        signal_reviewer=signal_reviewer,
        signal_review_num_results=signal_review_num_results,
    )
    print(f"Background scanned sources: {scanned}")
    print(f"New events: {new_events}")
    print(f"Errors: {errors}")


def background_loop(
    config_dir: Path = Path("config"),
    *,
    interval_seconds: float = 300,
    watch_config: bool = False,
    source_id: str | None = None,
    include_disabled: bool = False,
    enable_conference_review: bool = False,
    conference_review_interval_seconds: float = 86400,
    conference_review_year: int | None = None,
    conference_review_reviewer: str = "auto",
    conference_review_num_results: int = 10,
    enable_signal_review: bool = False,
    signal_reviewer: str = "auto",
    signal_review_num_results: int = 10,
) -> None:
    try:
        run_background_loop(
            config_dir,
            interval_seconds=interval_seconds,
            watch_config=watch_config,
            source_id=source_id,
            include_disabled=include_disabled,
            enable_conference_review=enable_conference_review,
            conference_review_interval_seconds=conference_review_interval_seconds,
            conference_review_year=conference_review_year,
            conference_review_reviewer=conference_review_reviewer,
            conference_review_num_results=conference_review_num_results,
            enable_signal_review=enable_signal_review,
            signal_reviewer=signal_reviewer,
            signal_review_num_results=signal_review_num_results,
        )
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        print("Background loop stopped.")


def foreground_pull(
    config_dir: Path = Path("config"),
    user_id: str = "",
    *,
    peek: bool = False,
    limit: int | None = None,
    output_format: str = "text",
    source_id: str | None = None,
    exclude_source_ids: list[str] | None = None,
    since: str | None = None,
) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = pull_user_updates(
            config,
            user_id,
            update_cursor=not peek,
            limit=limit,
            source_id=source_id,
            exclude_source_ids={source for source in (exclude_source_ids or []) if source},
            since=since,
            output_format=output_format,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def foreground_reset_cursor(config_dir: Path = Path("config"), user_id: str = "") -> None:
    config = _load_or_exit(config_dir)
    try:
        reset_user_cursor(config, user_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Cursor reset for {user_id}.")


def users_list_command(config_dir: Path = Path("config"), *, output_format: str = "text") -> None:
    config = _load_or_exit(config_dir)
    try:
        result = list_users_for_admin(config, output_format=output_format)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def users_subscribe_command(
    config_dir: Path = Path("config"),
    *,
    user_id: str,
    source_id: str,
    bucket: str = "auto",
) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = subscribe_user_to_source(config, user_id=user_id, source_id=source_id, bucket=bucket)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def users_unsubscribe_command(
    config_dir: Path = Path("config"),
    *,
    user_id: str,
    source_id: str,
    bucket: str = "auto",
) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = unsubscribe_user_from_source(config, user_id=user_id, source_id=source_id, bucket=bucket)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def status_command(config_dir: Path = Path("config"), *, output_format: str = "text") -> None:
    config = _load_or_exit(config_dir)
    try:
        result = build_status_dashboard(config, output_format=output_format)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def debug_server(config_dir: Path = Path("config"), host: str = "127.0.0.1", port: int = 8765) -> None:
    config = _load_or_exit(config_dir)
    run_debug_server(config, host=host, port=port)


def web_monitor(
    config_dir: Path = Path("config"),
    host: str = "127.0.0.1",
    port: int = 8080,
    token: str | None = None,
    token_file: Path | None = None,
) -> None:
    if token and token_file:
        print("Use only one of --token or --token-file.", file=sys.stderr)
        raise SystemExit(1)
    if token_file:
        try:
            token = token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            print(f"Failed to read token file: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if not token:
            print("Token file is empty.", file=sys.stderr)
            raise SystemExit(1)
    _load_or_exit(config_dir)
    run_monitor_web(config_dir, host=host, port=port, token=token)


def verify_sources_command(
    config_dir: Path = Path("config"),
    *,
    source_id: str | None = None,
    source_type: str | None = None,
    include_disabled: bool = False,
) -> None:
    config = _load_or_exit(config_dir)
    results = verify_sources(
        config,
        source_id=source_id,
        source_type=source_type,
        include_disabled=include_disabled,
    )
    if not results:
        print("No sources matched.")
        return
    for result in results:
        enabled = "enabled" if result.enabled else "disabled"
        error = f" | {result.error}" if result.error else ""
        print(
            f"{result.status.upper():24} {result.source_id:28} "
            f"{result.source_type:12} {enabled:8} items={result.item_count:<5} "
            f"elapsed_ms={result.elapsed_ms}{error}"
        )


def events_command(
    config_dir: Path = Path("config"),
    *,
    limit: int = 10,
    source_id: str | None = None,
    record_only: bool = False,
    notifiable: bool = False,
    output_format: str = "text",
) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = list_global_events(
            config,
            limit=limit,
            source_id=source_id,
            record_only=record_only,
            notifiable=notifiable,
            output_format=output_format,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def source_health_command(
    config_dir: Path = Path("config"),
    *,
    source_id: str | None = None,
    source_type: str | None = None,
    failed_only: bool = False,
    due_only: bool = False,
    output_format: str = "text",
) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = list_source_health(
            config,
            source_id=source_id,
            source_type=source_type,
            failed_only=failed_only,
            due_only=due_only,
            output_format=output_format,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def discover_conferences_command(
    config_dir: Path = Path("config"),
    *,
    venue_id: str | None = None,
    year: int | None = None,
    include_existing: bool = False,
    output_format: str = "text",
) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = discover_conferences(
            config,
            venue_id=venue_id,
            year=year,
            include_existing=include_existing,
            output_format=output_format,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def candidates_list_command(
    config_dir: Path = Path("config"),
    *,
    status: str | None = None,
    venue_id: str | None = None,
    output_format: str = "text",
) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = list_candidates(
            config,
            status=status,
            venue_id=venue_id,
            output_format=output_format,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def candidate_approve_command(config_dir: Path = Path("config"), *, candidate_id: str, dry_run: bool = False) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = approve_candidate(config, candidate_id=candidate_id, dry_run=dry_run)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def candidate_reject_command(config_dir: Path = Path("config"), *, candidate_id: str, reason: str | None = None) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = reject_candidate(config, candidate_id=candidate_id, reason=reason)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def review_search_results_command(
    config_dir: Path = Path("config"),
    *,
    input_path: Path,
    venue_id: str | None = None,
    year: int | None = None,
    reviewer: str = "auto",
    output_format: str = "text",
    dry_run: bool = False,
) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = review_search_results(
            config,
            input_path=input_path,
            venue_id=venue_id,
            year=year,
            reviewer=reviewer,
            output_format=output_format,
            dry_run=dry_run,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def conference_reviews_command(
    config_dir: Path = Path("config"),
    *,
    venue_id: str | None = None,
    year: int | None = None,
    output_format: str = "text",
) -> None:
    config = _load_or_exit(config_dir)
    try:
        response = list_search_reviews(
            config,
            venue_id=venue_id,
            year=year,
            output_format=output_format,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(response)


def review_conferences_command(
    config_dir: Path = Path("config"),
    *,
    venue_id: str | None = None,
    year: int | None = None,
    reviewer: str = "auto",
    num_results: int = 10,
    output_format: str = "text",
    dry_run: bool = False,
) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = review_conferences_batch(
            config,
            venue_id=venue_id,
            year=year,
            reviewer=reviewer,
            num_results=num_results,
            dry_run=dry_run,
            output_format=output_format,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def promote_conference_review_command(
    config_dir: Path = Path("config"),
    *,
    review_id: str | None = None,
    venue_id: str | None = None,
    year: int | None = None,
    output_format: str = "text",
    dry_run: bool = False,
) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = promote_conference_review(
            config,
            review_id=review_id,
            venue_id=venue_id,
            year=year,
            dry_run=dry_run,
            output_format=output_format,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.response_text)


def review_conference_signal_command(
    config_dir: Path = Path("config"),
    *,
    event_id: str,
    reviewer: str = "auto",
    num_results: int = 10,
    output_format: str = "text",
) -> None:
    config = _load_or_exit(config_dir)
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    event = next((item for item in store.load_events() if item.event_id == event_id), None)
    if event is None:
        print(f"event not found: {event_id}", file=sys.stderr)
        raise SystemExit(1)
    signal = detect_conference_signal(config, event)
    if signal is None:
        print(f"event is not a supported conference signal: {event_id}", file=sys.stderr)
        raise SystemExit(1)
    result = review_conference_signal(config, signal, reviewer=reviewer, num_results=num_results)
    print(render_signal_review_results([result], output_format=output_format))


def search_conference_command(
    config_dir: Path = Path("config"),
    *,
    venue_id: str,
    year: int,
    num_results: int = 10,
    output_format: str = "text",
    save: Path | None = None,
) -> None:
    config = _load_or_exit(config_dir)
    try:
        result = search_conference(
            config,
            venue_id=venue_id,
            year=year,
            num_results=num_results,
            output_format=output_format,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    if save:
        save.write_text(json.dumps(result.search_input.to_json_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result.response_text)


def search_and_review_conference_command(
    config_dir: Path = Path("config"),
    *,
    venue_id: str,
    year: int,
    num_results: int = 10,
    reviewer: str = "auto",
    output_format: str = "text",
    dry_run: bool = False,
) -> None:
    config = _load_or_exit(config_dir)
    try:
        search_result, review_result = search_and_review_conference(
            config,
            venue_id=venue_id,
            year=year,
            num_results=num_results,
            reviewer=reviewer,
            search_output_format=output_format,
            review_output_format=output_format,
            dry_run=dry_run,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    if output_format == "json":
        print(
            json.dumps(
                {
                    "search": search_result.search_input.to_json_payload(),
                    "review": review_result.review.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(search_result.response_text)
        print("")
        print(review_result.response_text)


def _open_repository(config_dir: Path) -> tuple[Repository, object]:
    config = _load_or_exit(config_dir)
    db_path = resolve_project_path(config, config.settings.database_path)
    if not db_path.exists():
        print(f"Database does not exist yet: {db_path}", file=sys.stderr)
        print("Run: paperwatcher init-db", file=sys.stderr)
        raise SystemExit(1)
    connection = connect(db_path)
    return Repository(connection), connection


def _print_paper_rows(rows) -> None:
    if not rows:
        print("No papers found.")
        return
    for row in rows:
        try:
            authors = json.loads(row["authors_json"] or "[]")
        except json.JSONDecodeError:
            authors = []
        author_text = ", ".join(authors[:3])
        if len(authors) > 3:
            author_text += " et al."
        print(f"[{row['recommendation']}] score={row['score']} ccf={row['ccf_level']} venue={row['venue']}")
        print(row["title"])
        if author_text:
            print(f"Authors: {author_text}")
        if row["paper_url"]:
            print(row["paper_url"])
        print("")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperwatcher", description="PaperWatcher CLI")
    parser.add_argument("-c", "--config-dir", default="config", type=Path, help="Configuration directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-config", help="Validate YAML configuration files.")
    status_parser = subparsers.add_parser("status", help="Show current PaperWatcher state summary.")
    status_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    subparsers.add_parser("init-db", help="Create SQLite tables and sync configured sources.")
    subparsers.add_parser("sources", help="List sources stored in the SQLite database.")
    index_parser = subparsers.add_parser("index", help="Manage the local SQLite state index.")
    index_subparsers = index_parser.add_subparsers(dest="index_command", required=True)
    index_subparsers.add_parser("sync", help="Rebuild the local SQLite index from file state.")
    index_subparsers.add_parser("status", help="Show the local SQLite index status.")
    scan_parser = subparsers.add_parser("scan", help="Run a scan.")
    scan_parser.add_argument("--once", action="store_true", help="Run one scan immediately.")
    scan_parser.add_argument("--source", dest="source_id", help="Only scan one enabled source id.")
    papers_parser = subparsers.add_parser("papers", help="List papers in the local database.")
    papers_parser.add_argument("--recommendation", choices=["read", "skim", "archive", "ignore"])
    papers_parser.add_argument("--limit", type=int, default=20)
    search_parser = subparsers.add_parser("search", help="Search papers in the local database.")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=20)
    background_parser = subparsers.add_parser("background", help="Run background source monitoring.")
    background_parser.add_argument("--once", action="store_true", help="Run one background pass.")
    background_parser.add_argument("--loop", action="store_true", help="Run background passes continuously.")
    background_parser.add_argument("--watch-config", action="store_true", help="Reload configuration between passes.")
    background_parser.add_argument("--interval", type=float, default=300, help="Seconds between loop passes.")
    background_parser.add_argument("--source", dest="source_id", help="Only scan one subscribed source id.")
    background_parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Allow scanning disabled sources, useful for explicit debug flows.",
    )
    background_parser.add_argument(
        "--enable-conference-review",
        action="store_true",
        help="Enable low-frequency conference search review during background loop.",
    )
    background_parser.add_argument(
        "--conference-review-interval",
        type=float,
        default=86400,
        help="Seconds between scheduled conference review batches.",
    )
    background_parser.add_argument("--conference-review-year", type=int)
    background_parser.add_argument(
        "--conference-review-reviewer",
        choices=["auto", "rule_based", "pydantic_ai"],
        default="auto",
    )
    background_parser.add_argument("--conference-review-num-results", type=int, default=10)
    background_parser.add_argument(
        "--enable-signal-review",
        action="store_true",
        help="Review conference signals, such as DBLP proceedings entries, when they appear.",
    )
    background_parser.add_argument("--signal-reviewer", choices=["auto", "rule_based", "pydantic_ai"], default="auto")
    background_parser.add_argument("--signal-review-num-results", type=int, default=10)
    foreground_parser = subparsers.add_parser("foreground", help="Foreground user-facing commands.")
    foreground_subparsers = foreground_parser.add_subparsers(dest="foreground_command", required=True)
    pull_parser = foreground_subparsers.add_parser("pull", help="Pull updates for a user.")
    pull_parser.add_argument("--user", required=True, dest="user_id")
    pull_parser.add_argument("--peek", action="store_true", help="Read without advancing the user cursor.")
    pull_parser.add_argument("--limit", type=int, help="Override user's delivery.max_items.")
    pull_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    pull_parser.add_argument("--source", dest="source_id", help="Only return events from one source id.")
    pull_parser.add_argument(
        "--exclude-source",
        action="append",
        dest="exclude_source_ids",
        help="Exclude one source id from this read; can be repeated.",
    )
    pull_parser.add_argument("--since", help="Read events newer than this ISO timestamp instead of cursor.")
    cursor_parser = foreground_subparsers.add_parser("cursor", help="Manage foreground user cursor.")
    cursor_parser.add_argument("--user", required=True, dest="user_id")
    cursor_parser.add_argument("--reset", action="store_true", help="Reset this user's cursor.")
    users_parser = subparsers.add_parser("users", help="Manage configured users and subscriptions.")
    users_subparsers = users_parser.add_subparsers(dest="users_command", required=True)
    users_list_parser = users_subparsers.add_parser("list", help="List users and subscriptions.")
    users_list_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    users_subscribe_parser = users_subparsers.add_parser("subscribe", help="Subscribe a user to a source.")
    users_subscribe_parser.add_argument("--user", required=True, dest="user_id")
    users_subscribe_parser.add_argument("--source", required=True, dest="source_id")
    users_subscribe_parser.add_argument(
        "--type",
        choices=["auto", "rss", "indexed_venues", "website_watch"],
        default="auto",
        dest="bucket",
    )
    users_unsubscribe_parser = users_subparsers.add_parser("unsubscribe", help="Unsubscribe a user from a source.")
    users_unsubscribe_parser.add_argument("--user", required=True, dest="user_id")
    users_unsubscribe_parser.add_argument("--source", required=True, dest="source_id")
    users_unsubscribe_parser.add_argument(
        "--type",
        choices=["auto", "rss", "indexed_venues", "website_watch"],
        default="auto",
        dest="bucket",
    )
    debug_parser = subparsers.add_parser("debug-server", help="Run local HTTP server for injecting debug updates.")
    debug_parser.add_argument("--host", default="127.0.0.1")
    debug_parser.add_argument("--port", type=int, default=8765)
    web_parser = subparsers.add_parser("web", help="Run read-only browser monitoring page.")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8080)
    web_parser.add_argument("--token", help="Optional access token for remote browser access.")
    web_parser.add_argument("--token-file", type=Path, help="Read the access token from a file.")
    verify_parser = subparsers.add_parser("verify-sources", help="Verify configured source availability.")
    verify_parser.add_argument("--source", dest="source_id", help="Only verify one source id.")
    verify_parser.add_argument("--type", dest="source_type", help="Only verify one source type, e.g. rss or dblp.")
    verify_parser.add_argument("--include-disabled", action="store_true")
    events_parser = subparsers.add_parser("events", help="List file-backed background events.")
    events_parser.add_argument("--limit", type=int, default=10)
    events_parser.add_argument("--source", dest="source_id", help="Only list one source id.")
    events_parser.add_argument("--record-only", action="store_true", help="Only list record-only source events.")
    events_parser.add_argument("--notifiable", action="store_true", help="Only list foreground-notifiable source events.")
    events_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    health_parser = subparsers.add_parser("source-health", help="List file-backed source scan health.")
    health_parser.add_argument("--source", dest="source_id", help="Only show one source id.")
    health_parser.add_argument("--type", dest="source_type", help="Only show one source type, e.g. rss or website_watch.")
    health_parser.add_argument("--failed", action="store_true", help="Only show sources with scan or verification failures.")
    health_parser.add_argument("--due", action="store_true", help="Only show sources due for a scheduled scan.")
    health_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    discover_parser = subparsers.add_parser("discover-conferences", help="Discover unstable conference website-watch candidates.")
    discover_parser.add_argument("--venue", dest="venue_id", help="Only discover one venue profile id.")
    discover_parser.add_argument("--year", type=int, help="Target conference year. Defaults to current year.")
    discover_parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Also probe URLs already configured in sources.yaml.",
    )
    discover_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    candidates_parser = subparsers.add_parser("candidates", help="Manage discovered source candidates.")
    candidates_subparsers = candidates_parser.add_subparsers(dest="candidates_command", required=True)
    candidates_list_parser = candidates_subparsers.add_parser("list", help="List discovered source candidates.")
    candidates_list_parser.add_argument("--status", choices=["pending", "approved", "rejected"])
    candidates_list_parser.add_argument("--venue", dest="venue_id")
    candidates_list_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    candidates_approve_parser = candidates_subparsers.add_parser("approve", help="Approve a candidate into config.")
    candidates_approve_parser.add_argument("--id", required=True, dest="candidate_id")
    candidates_approve_parser.add_argument("--dry-run", action="store_true", help="Preview source YAML without writing config.")
    candidates_reject_parser = candidates_subparsers.add_parser("reject", help="Reject a candidate.")
    candidates_reject_parser.add_argument("--id", required=True, dest="candidate_id")
    candidates_reject_parser.add_argument("--reason")
    review_search_parser = subparsers.add_parser(
        "review-search-results",
        help="Review fuzzy conference search results with rule-based or Pydantic AI reviewer.",
    )
    review_search_parser.add_argument("--input", required=True, type=Path, dest="input_path")
    review_search_parser.add_argument("--venue", dest="venue_id")
    review_search_parser.add_argument("--year", type=int)
    review_search_parser.add_argument("--reviewer", choices=["auto", "rule_based", "pydantic_ai"], default="auto")
    review_search_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    review_search_parser.add_argument("--dry-run", action="store_true", help="Do not write review state.")
    conference_reviews_parser = subparsers.add_parser(
        "conference-reviews",
        help="List stored conference search reviews.",
    )
    conference_reviews_parser.add_argument("--venue", dest="venue_id")
    conference_reviews_parser.add_argument("--year", type=int)
    conference_reviews_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    conference_reviews_subparsers = conference_reviews_parser.add_subparsers(
        dest="conference_reviews_command",
        required=False,
    )
    promote_review_parser = conference_reviews_subparsers.add_parser(
        "promote",
        help="Promote a high-confidence accepted-page review into source candidates.",
    )
    promote_review_parser.add_argument("--id", dest="review_id")
    promote_review_parser.add_argument("--venue", dest="promote_venue_id")
    promote_review_parser.add_argument("--year", type=int, dest="promote_year")
    promote_review_parser.add_argument("--format", choices=["text", "json"], default="text", dest="promote_output_format")
    promote_review_parser.add_argument("--dry-run", action="store_true")
    signal_review_parser = subparsers.add_parser(
        "review-conference-signal",
        help="Review one stored DBLP conference signal event and schedule follow-up monitoring.",
    )
    signal_review_parser.add_argument("--event-id", required=True)
    signal_review_parser.add_argument("--reviewer", choices=["auto", "rule_based", "pydantic_ai"], default="auto")
    signal_review_parser.add_argument("--num-results", type=int, default=10)
    signal_review_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    review_conferences_parser = subparsers.add_parser(
        "review-conferences",
        help="Batch search and review conference profiles for a target year.",
    )
    review_conferences_parser.add_argument("--venue", dest="venue_id")
    review_conferences_parser.add_argument("--year", type=int)
    review_conferences_parser.add_argument("--reviewer", choices=["auto", "rule_based", "pydantic_ai"], default="auto")
    review_conferences_parser.add_argument("--num-results", type=int, default=10)
    review_conferences_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    review_conferences_parser.add_argument("--dry-run", action="store_true", help="Do not write review state.")
    search_conference_parser = subparsers.add_parser(
        "search-conference",
        help="Search the web for conference signals using Exa.",
    )
    search_conference_parser.add_argument("--venue", required=True, dest="venue_id")
    search_conference_parser.add_argument("--year", required=True, type=int)
    search_conference_parser.add_argument("--num-results", type=int, default=10)
    search_conference_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    search_conference_parser.add_argument("--save", type=Path, help="Save normalized search input JSON to a file.")
    search_review_conference_parser = subparsers.add_parser(
        "search-review-conference",
        help="Search the web and immediately review the results.",
    )
    search_review_conference_parser.add_argument("--venue", required=True, dest="venue_id")
    search_review_conference_parser.add_argument("--year", required=True, type=int)
    search_review_conference_parser.add_argument("--num-results", type=int, default=10)
    search_review_conference_parser.add_argument("--reviewer", choices=["auto", "rule_based", "pydantic_ai"], default="auto")
    search_review_conference_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    search_review_conference_parser.add_argument("--dry-run", action="store_true", help="Do not write review state.")
    return parser


def app(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate-config":
        validate_config(args.config_dir)
    elif args.command == "status":
        status_command(args.config_dir, output_format=args.output_format)
    elif args.command == "init-db":
        init_db(args.config_dir)
    elif args.command == "sources":
        list_sources(args.config_dir)
    elif args.command == "index":
        if args.index_command == "sync":
            index_sync(args.config_dir)
        elif args.index_command == "status":
            index_status(args.config_dir)
        else:
            parser.error(f"unknown index command: {args.index_command}")
    elif args.command == "scan":
        if not args.once:
            parser.error("scan currently requires --once")
        scan(args.config_dir, source_id=args.source_id)
    elif args.command == "papers":
        list_papers(args.config_dir, recommendation=args.recommendation, limit=args.limit)
    elif args.command == "search":
        search_papers(args.config_dir, query=args.query, limit=args.limit)
    elif args.command == "background":
        if args.once and args.loop:
            parser.error("background accepts only one of --once or --loop")
        if args.loop:
            background_loop(
                args.config_dir,
                interval_seconds=args.interval,
                watch_config=args.watch_config,
                source_id=args.source_id,
                include_disabled=args.include_disabled,
                enable_conference_review=args.enable_conference_review,
                conference_review_interval_seconds=args.conference_review_interval,
                conference_review_year=args.conference_review_year,
                conference_review_reviewer=args.conference_review_reviewer,
                conference_review_num_results=args.conference_review_num_results,
                enable_signal_review=args.enable_signal_review,
                signal_reviewer=args.signal_reviewer,
                signal_review_num_results=args.signal_review_num_results,
            )
        elif args.once:
            background_once(
                args.config_dir,
                source_id=args.source_id,
                include_disabled=args.include_disabled,
                enable_signal_review=args.enable_signal_review,
                signal_reviewer=args.signal_reviewer,
                signal_review_num_results=args.signal_review_num_results,
            )
        else:
            parser.error("background requires --once or --loop")
    elif args.command == "foreground":
        if args.foreground_command == "pull":
            foreground_pull(
                args.config_dir,
                user_id=args.user_id,
                peek=args.peek,
                limit=args.limit,
                output_format=args.output_format,
                source_id=args.source_id,
                exclude_source_ids=args.exclude_source_ids,
                since=args.since,
            )
        elif args.foreground_command == "cursor":
            if not args.reset:
                parser.error("foreground cursor currently requires --reset")
            foreground_reset_cursor(args.config_dir, user_id=args.user_id)
        else:
            parser.error(f"unknown foreground command: {args.foreground_command}")
    elif args.command == "users":
        if args.users_command == "list":
            users_list_command(args.config_dir, output_format=args.output_format)
        elif args.users_command == "subscribe":
            users_subscribe_command(
                args.config_dir,
                user_id=args.user_id,
                source_id=args.source_id,
                bucket=args.bucket,
            )
        elif args.users_command == "unsubscribe":
            users_unsubscribe_command(
                args.config_dir,
                user_id=args.user_id,
                source_id=args.source_id,
                bucket=args.bucket,
            )
        else:
            parser.error(f"unknown users command: {args.users_command}")
    elif args.command == "debug-server":
        debug_server(args.config_dir, host=args.host, port=args.port)
    elif args.command == "web":
        web_monitor(args.config_dir, host=args.host, port=args.port, token=args.token, token_file=args.token_file)
    elif args.command == "verify-sources":
        verify_sources_command(
            args.config_dir,
            source_id=args.source_id,
            source_type=args.source_type,
            include_disabled=args.include_disabled,
        )
    elif args.command == "events":
        events_command(
            args.config_dir,
            limit=args.limit,
            source_id=args.source_id,
            record_only=args.record_only,
            notifiable=args.notifiable,
            output_format=args.output_format,
        )
    elif args.command == "source-health":
        source_health_command(
            args.config_dir,
            source_id=args.source_id,
            source_type=args.source_type,
            failed_only=args.failed,
            due_only=args.due,
            output_format=args.output_format,
        )
    elif args.command == "discover-conferences":
        discover_conferences_command(
            args.config_dir,
            venue_id=args.venue_id,
            year=args.year,
            include_existing=args.include_existing,
            output_format=args.output_format,
        )
    elif args.command == "candidates":
        if args.candidates_command == "list":
            candidates_list_command(
                args.config_dir,
                status=args.status,
                venue_id=args.venue_id,
                output_format=args.output_format,
            )
        elif args.candidates_command == "approve":
            candidate_approve_command(args.config_dir, candidate_id=args.candidate_id, dry_run=args.dry_run)
        elif args.candidates_command == "reject":
            candidate_reject_command(args.config_dir, candidate_id=args.candidate_id, reason=args.reason)
        else:
            parser.error(f"unknown candidates command: {args.candidates_command}")
    elif args.command == "review-search-results":
        review_search_results_command(
            args.config_dir,
            input_path=args.input_path,
            venue_id=args.venue_id,
            year=args.year,
            reviewer=args.reviewer,
            output_format=args.output_format,
            dry_run=args.dry_run,
        )
    elif args.command == "conference-reviews":
        if args.conference_reviews_command == "promote":
            promote_conference_review_command(
                args.config_dir,
                review_id=args.review_id,
                venue_id=args.promote_venue_id,
                year=args.promote_year,
                output_format=args.promote_output_format,
                dry_run=args.dry_run,
            )
        else:
            conference_reviews_command(
                args.config_dir,
                venue_id=args.venue_id,
                year=args.year,
                output_format=args.output_format,
            )
    elif args.command == "review-conferences":
        review_conferences_command(
            args.config_dir,
            venue_id=args.venue_id,
            year=args.year,
            reviewer=args.reviewer,
            num_results=args.num_results,
            output_format=args.output_format,
            dry_run=args.dry_run,
        )
    elif args.command == "review-conference-signal":
        review_conference_signal_command(
            args.config_dir,
            event_id=args.event_id,
            reviewer=args.reviewer,
            num_results=args.num_results,
            output_format=args.output_format,
        )
    elif args.command == "search-conference":
        search_conference_command(
            args.config_dir,
            venue_id=args.venue_id,
            year=args.year,
            num_results=args.num_results,
            output_format=args.output_format,
            save=args.save,
        )
    elif args.command == "search-review-conference":
        search_and_review_conference_command(
            args.config_dir,
            venue_id=args.venue_id,
            year=args.year,
            num_results=args.num_results,
            reviewer=args.reviewer,
            output_format=args.output_format,
            dry_run=args.dry_run,
        )
    else:
        parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    app()
