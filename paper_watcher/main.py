from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

from paper_watcher.background import run_background_loop, run_background_once
from paper_watcher.config_loader import ConfigError, load_config
from paper_watcher.debug_server import run_debug_server
from paper_watcher.events import list_global_events
from paper_watcher.foreground import pull_user_updates, reset_user_cursor
from paper_watcher.settings import resolve_project_path
from paper_watcher.scanner import scan_once
from paper_watcher.source_health import list_source_health
from paper_watcher.storage.database import connect
from paper_watcher.storage.migrations import init_db as apply_schema
from paper_watcher.storage.repository import Repository
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
) -> None:
    config = _load_or_exit(config_dir)
    scanned, new_events, errors = run_background_once(
        config,
        source_id=source_id,
        include_disabled=include_disabled,
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
) -> None:
    try:
        run_background_loop(
            config_dir,
            interval_seconds=interval_seconds,
            watch_config=watch_config,
            source_id=source_id,
            include_disabled=include_disabled,
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


def debug_server(config_dir: Path = Path("config"), host: str = "127.0.0.1", port: int = 8765) -> None:
    config = _load_or_exit(config_dir)
    run_debug_server(config, host=host, port=port)


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
    subparsers.add_parser("init-db", help="Create SQLite tables and sync configured sources.")
    subparsers.add_parser("sources", help="List sources stored in the SQLite database.")
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
    foreground_parser = subparsers.add_parser("foreground", help="Foreground user-facing commands.")
    foreground_subparsers = foreground_parser.add_subparsers(dest="foreground_command", required=True)
    pull_parser = foreground_subparsers.add_parser("pull", help="Pull updates for a user.")
    pull_parser.add_argument("--user", required=True, dest="user_id")
    pull_parser.add_argument("--peek", action="store_true", help="Read without advancing the user cursor.")
    pull_parser.add_argument("--limit", type=int, help="Override user's delivery.max_items.")
    pull_parser.add_argument("--format", choices=["text", "json"], default="text", dest="output_format")
    pull_parser.add_argument("--source", dest="source_id", help="Only return events from one source id.")
    pull_parser.add_argument("--since", help="Read events newer than this ISO timestamp instead of cursor.")
    cursor_parser = foreground_subparsers.add_parser("cursor", help="Manage foreground user cursor.")
    cursor_parser.add_argument("--user", required=True, dest="user_id")
    cursor_parser.add_argument("--reset", action="store_true", help="Reset this user's cursor.")
    debug_parser = subparsers.add_parser("debug-server", help="Run local HTTP server for injecting debug updates.")
    debug_parser.add_argument("--host", default="127.0.0.1")
    debug_parser.add_argument("--port", type=int, default=8765)
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
    return parser


def app(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate-config":
        validate_config(args.config_dir)
    elif args.command == "init-db":
        init_db(args.config_dir)
    elif args.command == "sources":
        list_sources(args.config_dir)
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
            )
        elif args.once:
            background_once(args.config_dir, source_id=args.source_id, include_disabled=args.include_disabled)
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
                since=args.since,
            )
        elif args.foreground_command == "cursor":
            if not args.reset:
                parser.error("foreground cursor currently requires --reset")
            foreground_reset_cursor(args.config_dir, user_id=args.user_id)
        else:
            parser.error(f"unknown foreground command: {args.foreground_command}")
    elif args.command == "debug-server":
        debug_server(args.config_dir, host=args.host, port=args.port)
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
    else:
        parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    app()
