# PaperWatcher

PaperWatcher is a user-oriented literature and conference subscription system.

The system is designed around two separated roles:

- A background worker continuously watches configured sources and records new
  items into a storage backend.
- A foreground service waits for external activation. A caller asks as a given
  user, and the foreground service returns new subscribed items since that
  user's last request.

At the current stage, the external caller is a human using CLI commands. Later,
AstrBot or another automation layer can call the same foreground logic.

## Target Runtime Logic

PaperWatcher maintains a user library. Each user declares what they want to
listen to. Different source classes have different storage fields because RSS
feeds, DBLP/OpenReview-style APIs, and website-watch pages are not configured in
the same way.

The intended flow is:

```text
User library
  -> user_id
  -> subscriptions
     -> rss subscriptions
     -> indexed venue subscriptions, later
     -> website-watch subscriptions, later

Background worker
  -> runs for a long time
  -> continuously scans RSS-like sources
  -> periodically scans non-RSS subscriptions, later
  -> writes new items to backend storage
  -> current backend: files
  -> later backend: SQLite/PostgreSQL behind the same interface

Foreground service
  -> waits for external activation
  -> caller provides user_id
  -> reads user subscriptions
  -> finds new items since this user's last pull
  -> returns a compact answer
  -> current answer: paper title + link
  -> later answer: Markdown summary, LLM digest, AstrBot message
```

Current event-flow rule:

```text
The backend scans the union of all users' subscribed source IDs.
The backend writes discovered items to one global event stream.
The frontend filters the global event stream by each user's subscriptions and cursor.
```

For the detailed design, see:

```text
docs/subscription_union_event_flow.md
```

## Current-Stage Scope

Current stage intentionally keeps the system small:

```text
Implemented source type for foreground/background flow:
  RSS
  arXiv, as RSS-compatible record-only sources
  DBLP, as the first CCF-A/B venue source class

Deferred source types:
  OpenReview
  website_watch
  Semantic Scholar
  email_import
```

Current storage mode:

```text
File storage
```

The file storage layer is temporary, but should be accessed through a narrow
interface so a later database backend can replace it without changing the
foreground/background business logic.

## Source Priority Policy

The main monitoring target is CCF-A/B journals and conferences. arXiv is treated
as a low-priority early-signal source:

```text
arXiv items are recorded.
arXiv items are not pushed to foreground users by default.
arXiv items can later be searched, scored, grouped, and used as weak signals.
```

Current arXiv sources use:

```yaml
source_type: arxiv
priority: 1
notification_policy: record_only
```

TODO: group arXiv records by the submitting authors' research team,
institution, lab, company research group, or security vendor when metadata is
available.

For monitoring-list hot update design, see:

```text
docs/monitoring_hot_reload_design.md
```

## User Library Design

The user library lives in:

```text
config/users.yaml
```

Example:

```yaml
users:
  - id: default
    display_name: Default User
    subscriptions:
      rss:
        - source_id: arxiv_cs_cr
        - source_id: arxiv_cs_lg
      indexed_venues: []
      website_watch: []
    delivery:
      format: text
      max_items: 20
```

RSS subscriptions refer to source IDs defined in:

```text
config/sources.yaml
```

Future indexed venue subscriptions may store fields such as:

```yaml
indexed_venues:
  - source_id: dblp_ccs
    venue_key: conf/ccs
    since_year: 2026
```

Future website-watch subscriptions may store fields such as:

```yaml
website_watch:
  - source_id: usenix_security_2026_accepted
    watch_url: https://www.usenix.org/conference/usenixsecurity26/accepted-papers
    css_selector: main
```

This distinction is important: the program should not force all subscription
types into one flat shape.

## File Storage Design

Current file backend lives under:

```text
state/
```

Recommended files:

```text
state/
  events.jsonl             # append-only discovered-item events
  source_state.json        # ETag / Last-Modified / cursor per source
  user_cursors.json        # last foreground pull timestamp/event per user
```

`events.jsonl` is append-only. Each line is one JSON object:

```json
{
  "event_id": "evt_...",
  "seen_at": "2026-07-15T00:00:00+00:00",
  "source_id": "arxiv_cs_cr",
  "source_type": "rss",
  "paper_id": "paper_...",
  "title": "Paper title",
  "link": "https://example.com/paper",
  "matched_users": []
}
```

`source_state.json` stores source-level incremental scan state:

```json
{
  "arxiv_cs_cr": {
    "etag": "...",
    "last_modified": "...",
    "last_success_at": "..."
  }
}
```

`user_cursors.json` stores foreground pull state:

```json
{
  "default": {
    "last_pulled_at": "2026-07-15T00:00:00+00:00"
  }
}
```

## Background Worker Logic

Current target:

```text
paperwatcher background --once
paperwatcher background --loop --watch-config --interval 300
```

`--once` runs a single pass. `--loop` runs repeated passes until interrupted.
With `--watch-config`, the worker checks YAML file fingerprints before each
pass and reloads valid config changes without restarting the process.

```text
paperwatcher background --loop --watch-config --interval 300
```

One background pass does:

```text
1. Load global source config.
2. Load user library.
3. Determine which RSS sources are required by at least one user.
4. Load file source_state.
5. Fetch each RSS source with ETag / Last-Modified.
6. Convert feed entries into normalized paper items.
7. Deduplicate against existing events by paper_id.
8. Find users subscribed to the source.
9. Append new events to state/events.jsonl.
10. Update state/source_state.json.
```

Important behavior:

```text
The background worker does not answer users directly.
It only records newly discovered items.
Bad hot-reload config is rejected and written to state/config_reload_errors.jsonl.
```

## Foreground Logic

Current target:

```text
paperwatcher foreground pull --user default
```

One foreground pull does:

```text
1. Load user library.
2. Load state/events.jsonl.
3. Load state/user_cursors.json.
4. Select events matching this user and newer than the user's cursor.
5. Print a compact response: title + link.
6. Update this user's cursor after successful response.
```

Current answer format:

```text
New papers for default:

1. Paper title
   https://example.com/paper
```

Later, AstrBot can call the same function and send the response to chat.

## Current Stage

Already implemented foundation:

- Project skeleton
- YAML configuration loader
- SQLite schema initialization
- Basic CLI commands
- RSS fetcher
- RSS scanning into SQLite
- Scoring and Markdown run reports
- Basic local paper query
- User library in `config/users.yaml`
- File-backed background event storage in `state/`
- `background --once` RSS monitoring pass
- `foreground pull --user <id>` user-specific update retrieval
- DBLP fetcher for the first CCF-A/B journal and conference sources
- `verify-sources` source availability checks
- Network request throttling, retry, and HTTP cache settings
- `events` command for global event inspection, including record-only and notifiable filters
- Long-running `background --loop --watch-config` with config reload error logging

Next implementation step:

- Add website-watch source class behind the same background interface.

## Basic Usage

```bash
python -m paper_watcher.main validate-config
python -m paper_watcher.main init-db
python -m paper_watcher.main sources
python -m paper_watcher.main scan --once --source arxiv_cs_cr
python -m paper_watcher.main papers --recommendation read
python -m paper_watcher.main search "prompt injection"
python -m paper_watcher.main background --once
python -m paper_watcher.main background --loop --watch-config --interval 300
python -m paper_watcher.main foreground pull --user default
python -m paper_watcher.main foreground pull --user debug_user --peek --format json --limit 1
python -m paper_watcher.main foreground cursor --user debug_user --reset
python -m paper_watcher.main debug-server --port 8765
python -m paper_watcher.main verify-sources --type dblp
python -m paper_watcher.main events --limit 10
python -m paper_watcher.main events --record-only --limit 10
python -m paper_watcher.main events --notifiable --format json --limit 10
python scripts/send_debug_update.py debug-event --source-id debug_fake_rss --title "Debug Paper" --link "https://example.com/debug"
python scripts/send_debug_update.py fake-rss --port 8766 --title "Fake RSS Paper"
python -m unittest discover -s tests
```

## Debug Update Injection

For business-logic debugging, run a local backend debug port:

```bash
python3 -m paper_watcher.main debug-server --host 127.0.0.1 --port 8765
```

Then, from another shell, send a fake update:

```bash
python3 scripts/send_debug_update.py debug-event \
  --source-id debug_fake_rss \
  --title "Debug Paper Update" \
  --link "https://example.com/debug-paper"
```

The debug server appends one event to `state/events.jsonl`. The foreground can
then retrieve it like any real background event:

```bash
python3 -m paper_watcher.main foreground pull --user debug_user --source debug_fake_rss
```

The debug server binds to `127.0.0.1` by default. Keep it local unless there is
a clear reason to expose it.

The same standalone debug tool can also serve a fake RSS feed:

```bash
python3 scripts/send_debug_update.py fake-rss \
  --port 8766 \
  --title "Fake RSS Paper" \
  --link "https://example.com/fake-rss-paper" \
  --guid fake-rss-001
```

The configured `debug_fake_rss` source is disabled by default. To scan it
explicitly for a test:

```bash
python3 -m paper_watcher.main background --once --source debug_fake_rss --include-disabled
```

Foreground read options:

```bash
python3 -m paper_watcher.main foreground pull --user debug_user --peek
python3 -m paper_watcher.main foreground pull --user debug_user --limit 5
python3 -m paper_watcher.main foreground pull --user debug_user --format json
python3 -m paper_watcher.main foreground pull --user debug_user --source debug_fake_rss
python3 -m paper_watcher.main foreground pull --user debug_user --since 2026-07-15T00:00:00+00:00
python3 -m paper_watcher.main foreground cursor --user debug_user --reset
```

See [docs/functional_test_plan.md](docs/functional_test_plan.md) for the
end-to-end feature test plan.

## Event Inspection

The background writes discovered items into the global file event stream:

```text
state/events.jsonl
```

Inspect recent events without advancing any user's foreground cursor:

```bash
python3 -m paper_watcher.main events --limit 10
python3 -m paper_watcher.main events --source arxiv_cs_cr --limit 10
python3 -m paper_watcher.main events --record-only --limit 10
python3 -m paper_watcher.main events --notifiable --limit 10
python3 -m paper_watcher.main events --format json --limit 10
```

`--record-only` is useful for checking low-priority arXiv records. `--notifiable`
shows events from sources that foreground users can receive through
`foreground pull`.

## Source Verification

Verify source availability without writing paper events:

```bash
python3 -m paper_watcher.main verify-sources
python3 -m paper_watcher.main verify-sources --source dblp_ccs
python3 -m paper_watcher.main verify-sources --type dblp
python3 -m paper_watcher.main verify-sources --include-disabled
```

Verification results are stored in:

```text
state/source_verification.json
```

Supported now:

```text
rss
arxiv
dblp
```

Unsupported source types are reported as `unsupported_source_type` instead of
failing the whole command.

Possible verification statuses include:

```text
ok
cached_ok
unsupported_source_type
missing_required_field
network_error
http_429
http_503
parse_error
failed
```

Network behavior is configured in `config/settings.yaml`:

```yaml
network:
  per_host_delay_seconds:
    dblp.org: 5
  retries:
    max_attempts: 3
    backoff_seconds: 10
  cache:
    enabled: true
    dir: state/http_cache
```

`verify-sources` may fall back to `state/http_cache` and report `cached_ok` when
the live request fails but a previous successful response is available. Regular
background scans do not use cached responses after a network error, so stale
cache content cannot create new paper events.

Or after installing the package:

```bash
paperwatcher validate-config
paperwatcher init-db
paperwatcher sources
```

## Python Package Mirror

On Aliyun ECS, configure pip to use the Aliyun PyPI mirror first:

```bash
python3 -m pip config --user set global.index-url https://mirrors.aliyun.com/pypi/simple/
python3 -m pip config --user set global.timeout 60
python3 -m pip config --user set global.retries 10
```

Install development and fetch dependencies:

```bash
python3 -m pip install --user --break-system-packages --no-build-isolation -e '.[dev,fetch]'
```

If the mirror cannot solve a network issue, use the local mihomo proxy already
running on this machine as the next fallback.

## Configuration

Default configuration path:

```text
config/
```

Runtime settings are in:

```text
config/settings.yaml
```

Sensitive values such as LLM API keys and webhook tokens must be provided by
environment variables or `.env`, not committed into YAML configuration.
