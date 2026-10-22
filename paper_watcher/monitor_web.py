from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from paper_watcher.conference_discovery import approve_candidate, reject_candidate
from paper_watcher.config_loader import load_config
from paper_watcher.events import list_global_events
from paper_watcher.settings import resolve_project_path
from paper_watcher.source_health import list_source_health
from paper_watcher.status_dashboard import build_status_dashboard
from paper_watcher.storage.file_storage import FileStateStore
from paper_watcher.subscriptions import user_subscription_source_ids


def run_monitor_web(config_dir: Path, *, host: str = "127.0.0.1", port: int = 8080, token: str | None = None) -> None:
    class Handler(MonitorWebHandler):
        active_config_dir = config_dir
        access_token = token

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"PaperWatcher monitor listening on {url}")
    if token:
        print("Access token enabled. Pass it as ?token=... or X-PaperWatcher-Token.")
    elif host not in {"127.0.0.1", "localhost", "::1"}:
        print("Warning: no access token configured while binding to a non-loopback host.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPaperWatcher monitor stopped.")
    finally:
        server.server_close()


class MonitorWebHandler(BaseHTTPRequestHandler):
    active_config_dir: Path
    access_token: str | None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._write_json(200, {"ok": True})
            return
        if not self._is_authorized(parsed):
            self._write_unauthorized(parsed.path)
            return
        if parsed.path in {"", "/"}:
            self._write_html(200, _HTML)
            return
        if parsed.path == "/api/dashboard":
            try:
                payload = build_monitor_payload(self.active_config_dir, parsed.query)
            except Exception as exc:
                self._write_json(500, {"error": str(exc)})
                return
            self._write_json(200, payload)
            return
        if parsed.path == "/api/candidates":
            try:
                payload = list_candidates_for_api(self.active_config_dir, parsed.query)
            except Exception as exc:
                self._write_json(500, {"error": str(exc)})
                return
            self._write_json(200, payload)
            return
        self._write_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self._is_authorized(parsed):
            self._write_unauthorized(parsed.path)
            return
        if parsed.path == "/api/candidates/approve":
            try:
                payload = self._read_json_body()
                candidate_id = payload.get("candidate_id")
                if not isinstance(candidate_id, str) or not candidate_id.strip():
                    self._write_json(400, {"error": "candidate_id is required"})
                    return
                dry_run = bool(payload.get("dry_run", False))
                actor = _actor_from_payload(payload)
                result = approve_candidate_from_api(
                    self.active_config_dir,
                    candidate_id=candidate_id.strip(),
                    dry_run=dry_run,
                    actor=actor,
                )
            except ValueError as exc:
                self._write_json(400, {"error": str(exc)})
                return
            except Exception as exc:
                self._write_json(500, {"error": str(exc)})
                return
            self._write_json(200, result)
            return
        if parsed.path == "/api/candidates/reject":
            try:
                payload = self._read_json_body()
                candidate_id = payload.get("candidate_id")
                if not isinstance(candidate_id, str) or not candidate_id.strip():
                    self._write_json(400, {"error": "candidate_id is required"})
                    return
                reason = payload.get("reason")
                if reason is not None and not isinstance(reason, str):
                    self._write_json(400, {"error": "reason must be a string"})
                    return
                actor = _actor_from_payload(payload)
                result = reject_candidate_from_api(
                    self.active_config_dir,
                    candidate_id=candidate_id.strip(),
                    reason=reason.strip() if isinstance(reason, str) and reason.strip() else None,
                    actor=actor,
                )
            except ValueError as exc:
                self._write_json(400, {"error": str(exc)})
                return
            except Exception as exc:
                self._write_json(500, {"error": str(exc)})
                return
            self._write_json(200, result)
            return
        self._write_json(404, {"error": "not found"})

    def log_message(self, format: str, *args) -> None:
        return

    def _is_authorized(self, parsed) -> bool:
        if not self.access_token:
            return True
        query_token = parse_qs(parsed.query).get("token", [None])[0]
        header_token = self.headers.get("X-PaperWatcher-Token")
        auth = self.headers.get("Authorization", "")
        bearer_token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else None
        return self.access_token in {query_token, header_token, bearer_token}

    def _write_unauthorized(self, path: str) -> None:
        if path.startswith("/api/"):
            self._write_json(401, {"error": "unauthorized"})
            return
        self._write_html(
            401,
            """
<!doctype html>
<html><head><meta charset="utf-8"><title>Unauthorized</title></head>
<body><h1>Unauthorized</h1><p>Pass the monitor token as <code>?token=...</code>.</p></body></html>
""",
        )

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return {}
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0 or length > 65536:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def _write_html(self, status: int, html: str) -> None:
        raw = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def list_candidates_for_api(config_dir: Path, query: str = "") -> dict[str, Any]:
    params = parse_qs(query)
    status = _optional_param(params, "status")
    venue_id = _optional_param(params, "venue_id") or _optional_param(params, "venue")
    limit = _int_param(params, "limit", 80)
    config = load_config(config_dir)
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    candidates = store.load_source_candidates()
    if status:
        candidates = [item for item in candidates if item.get("status") == status]
    if venue_id:
        candidates = [item for item in candidates if item.get("venue_id") == venue_id]
    candidates = sorted(candidates, key=lambda item: item.get("last_checked_at", ""), reverse=True)
    return {
        "count": len(candidates),
        "returned": min(len(candidates), limit),
        "generated_at": datetime.now(UTC).isoformat(),
        "candidates": candidates[:limit],
    }


def approve_candidate_from_api(
    config_dir: Path,
    *,
    candidate_id: str,
    dry_run: bool = False,
    actor: str = "web",
) -> dict[str, Any]:
    config = load_config(config_dir)
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    result = approve_candidate(config, candidate_id=candidate_id, dry_run=dry_run)
    action_record = store.append_candidate_action(
        candidate_id=result.candidate.candidate_id,
        source_id=result.candidate.source_id,
        action="approve_preview" if dry_run else "approve",
        actor=actor,
        dry_run=dry_run,
        result="ok",
        message=result.response_text,
    )
    return {
        "ok": True,
        "dry_run": dry_run,
        "candidate_id": result.candidate.candidate_id,
        "source_id": result.candidate.source_id,
        "status": "preview" if dry_run else "approved",
        "message": result.response_text,
        "candidate": result.candidate.to_dict(),
        "action": action_record,
    }


def reject_candidate_from_api(
    config_dir: Path,
    *,
    candidate_id: str,
    reason: str | None = None,
    actor: str = "web",
) -> dict[str, Any]:
    config = load_config(config_dir)
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    result = reject_candidate(config, candidate_id=candidate_id, reason=reason)
    action_record = store.append_candidate_action(
        candidate_id=result.candidate.candidate_id,
        source_id=result.candidate.source_id,
        action="reject",
        actor=actor,
        reason=reason,
        result="ok",
        message=result.response_text,
    )
    return {
        "ok": True,
        "candidate_id": result.candidate.candidate_id,
        "source_id": result.candidate.source_id,
        "status": "rejected",
        "message": result.response_text,
        "candidate": result.candidate.to_dict(),
        "action": action_record,
    }


def build_monitor_payload(config_dir: Path, query: str = "") -> dict[str, Any]:
    params = parse_qs(query)
    event_limit = _int_param(params, "event_limit", 80)
    config = load_config(config_dir)
    store = FileStateStore(resolve_project_path(config, config.settings.state_dir))
    status = build_status_dashboard(config, output_format="json").data
    health = list_source_health(config).rows
    events = list_global_events(config, limit=event_limit).events
    candidates = store.load_source_candidates()
    reviews = store.load_conference_search_reviews()
    source_by_id = {source.id: source for source in config.sources.sources}
    conference_pages = _collect_conference_page_diagnostics(events, source_by_id)

    source_type_counts: dict[str, int] = {}
    ccf_counts: dict[str, int] = {}
    for source in config.sources.sources:
        source_type_counts[source.source_type.value] = source_type_counts.get(source.source_type.value, 0) + 1
        ccf_counts[source.ccf_level.value] = ccf_counts.get(source.ccf_level.value, 0) + 1

    users = []
    enabled_source_ids = {source.id for source in config.sources.sources if source.enabled}
    for user in config.users.users:
        subscribed = sorted(user_subscription_source_ids(user))
        users.append(
            {
                "id": user.id,
                "display_name": user.display_name,
                "source_count": len(subscribed),
                "enabled_coverage": len(enabled_source_ids.intersection(subscribed)),
                "sources": subscribed,
            }
        )

    return {
        "status": status,
        "generated_at": status["background"].get("last_scan_at"),
        "source_type_counts": source_type_counts,
        "ccf_counts": ccf_counts,
        "sources": [
            {
                "id": source.id,
                "name": source.name,
                "source_type": source.source_type.value,
                "enabled": source.enabled,
                "ccf_level": source.ccf_level.value,
                "venue_type": source.venue_type.value,
                "priority": source.priority,
                "notification_policy": source.notification_policy.value,
                "tags": source.tags,
            }
            for source in config.sources.sources
        ],
        "source_health": [asdict(row) for row in health],
        "events": [
            {
                "event_id": event.event_id,
                "seen_at": event.seen_at,
                "source_id": event.source_id,
                "source_name": source_by_id[event.source_id].name if event.source_id in source_by_id else event.source_id,
                "source_type": event.source_type,
                "title": event.title,
                "link": event.link,
                "paper_id": event.paper_id,
                "raw": event.raw,
            }
            for event in events
        ],
        "conference_pages": conference_pages,
        "users": users,
        "candidates": sorted(candidates, key=lambda item: item.get("last_checked_at", ""), reverse=True)[:80],
        "conference_reviews": sorted(reviews, key=lambda item: item.get("reviewed_at", ""), reverse=True)[:80],
    }


def _collect_conference_page_diagnostics(events, source_by_id: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        source = source_by_id.get(event.source_id)
        if not source or source.source_type.value != "website_watch":
            continue
        raw = event.raw or {}
        supervisor = raw.get("conference_page_supervisor")
        supervisor_error = raw.get("conference_page_supervisor_error")
        if not supervisor and not supervisor_error:
            continue
        row: dict[str, Any] = {
            "event_id": event.event_id,
            "seen_at": event.seen_at,
            "source_id": event.source_id,
            "source_name": source.name,
            "title": event.title,
            "link": event.link,
            "supervisor_error": supervisor_error,
        }
        if isinstance(supervisor, dict):
            row.update(
                {
                    "analysis_mode": supervisor.get("analysis_mode"),
                    "matched_layout": supervisor.get("matched_layout"),
                    "retry_used": supervisor.get("retry_used", False),
                    "retry_layout": supervisor.get("retry_layout"),
                    "snapshot_only": supervisor.get("snapshot_only", False),
                    "review": supervisor.get("review"),
                    "page_summary": supervisor.get("page_summary"),
                    "initial_candidate_count": supervisor.get("initial_candidate_count"),
                    "final_candidate_count": supervisor.get("final_candidate_count"),
                    "review_error": supervisor.get("review_error"),
                    "fallback_to_snapshot_only": supervisor.get("fallback_to_snapshot_only", False),
                }
            )
        rows.append(row)
    rows.sort(key=lambda item: item.get("seen_at", ""), reverse=True)
    return rows[:80]


def _int_param(params: dict[str, list[str]], key: str, default: int) -> int:
    raw = params.get(key, [None])[0]
    if raw is None:
        return default
    try:
        return max(1, min(500, int(raw)))
    except ValueError:
        return default


def _optional_param(params: dict[str, list[str]], key: str) -> str | None:
    value = params.get(key, [None])[0]
    if value is None:
        return None
    value = value.strip()
    return value or None


def _actor_from_payload(payload: dict[str, Any]) -> str:
    actor = payload.get("actor")
    if actor is None:
        return "web"
    if not isinstance(actor, str):
        raise ValueError("actor must be a string")
    actor = actor.strip()
    if not actor:
        return "web"
    return actor[:120]


_HTML = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PaperWatcher Monitor</title>
  <style>
    :root {
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d8dde6;
      --text: #18202a;
      --muted: #667085;
      --accent: #0f766e;
      --warn: #b45309;
      --bad: #b42318;
      --good: #027a48;
      --soft: #eef2f6;
      --shadow: 0 1px 2px rgba(16, 24, 40, 0.06);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; color: var(--text); background: var(--bg); }
    header {
      display: flex; align-items: center; justify-content: space-between; gap: 16px;
      padding: 18px 24px; border-bottom: 1px solid var(--line); background: var(--panel);
      position: sticky; top: 0; z-index: 10;
    }
    h1 { margin: 0; font-size: 20px; font-weight: 700; letter-spacing: 0; }
    h2 { margin: 0 0 12px; font-size: 15px; letter-spacing: 0; }
    button {
      border: 1px solid var(--line); background: var(--panel); color: var(--text);
      height: 34px; padding: 0 12px; border-radius: 6px; cursor: pointer;
    }
    button.primary { background: var(--accent); color: white; border-color: var(--accent); }
    button.danger { color: var(--bad); border-color: #fda29b; background: #fff7f5; }
    button:disabled { cursor: not-allowed; opacity: 0.55; }
    main { padding: 18px 24px 32px; max-width: 1480px; margin: 0 auto; }
    .toolbar { display: flex; gap: 10px; align-items: center; color: var(--muted); font-size: 13px; }
    .grid { display: grid; gap: 14px; }
    .metrics { grid-template-columns: repeat(6, minmax(130px, 1fr)); }
    .two { grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr); margin-top: 14px; }
    .panel, .metric {
      background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow);
    }
    .metric { padding: 14px; min-height: 82px; }
    .metric .label { color: var(--muted); font-size: 12px; }
    .metric .value { margin-top: 8px; font-size: 26px; line-height: 1; font-weight: 750; }
    .metric .hint { margin-top: 6px; color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .panel { padding: 14px; min-width: 0; }
    .tabs { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0; }
    .tab[aria-selected="true"] { background: var(--accent); color: white; border-color: var(--accent); }
    table { width: 100%; border-collapse: collapse; table-layout: fixed; }
    th, td { padding: 9px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; font-size: 13px; }
    th { color: var(--muted); font-size: 12px; font-weight: 650; background: #fbfcfd; }
    td { overflow-wrap: anywhere; }
    .pill { display: inline-flex; align-items: center; min-height: 22px; padding: 2px 7px; border-radius: 999px; background: var(--soft); font-size: 12px; color: var(--muted); }
    .pill.good { color: var(--good); background: #ecfdf3; }
    .pill.bad { color: var(--bad); background: #fef3f2; }
    .pill.warn { color: var(--warn); background: #fffaeb; }
    .list { display: grid; gap: 10px; }
    .event { padding: 10px 0; border-bottom: 1px solid var(--line); }
    .event:last-child { border-bottom: 0; }
    .event a { color: #175cd3; text-decoration: none; }
    .event .title { font-weight: 650; line-height: 1.35; }
    .event .meta { color: var(--muted); font-size: 12px; margin-top: 5px; }
    .empty, .error { color: var(--muted); padding: 16px; background: var(--panel); border: 1px dashed var(--line); border-radius: 8px; }
    .error { color: var(--bad); }
    .notice { color: var(--good); padding: 10px 12px; margin-bottom: 12px; background: #ecfdf3; border: 1px solid #abefc6; border-radius: 8px; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .hide { display: none; }
    @media (max-width: 980px) {
      header { position: static; align-items: flex-start; flex-direction: column; }
      main { padding: 14px; }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .two { grid-template-columns: 1fr; }
      table { table-layout: auto; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>PaperWatcher Monitor</h1>
      <div class="toolbar"><span id="subtitle">Loading state...</span></div>
    </div>
    <div class="toolbar">
      <button id="refresh" class="primary" type="button">Refresh</button>
      <button id="auto" type="button" aria-pressed="false">Auto refresh: off</button>
    </div>
  </header>
  <main>
    <section id="metrics" class="grid metrics"></section>
    <nav class="tabs" aria-label="Views">
      <button class="tab" data-view="events" aria-selected="true">Events</button>
      <button class="tab" data-view="conference_pages">Conference Pages</button>
      <button class="tab" data-view="sources">Sources</button>
      <button class="tab" data-view="health">Health</button>
      <button class="tab" data-view="users">Users</button>
      <button class="tab" data-view="reviews">Reviews</button>
      <button class="tab" data-view="candidates">Candidates</button>
    </nav>
    <section id="error" class="error hide"></section>
    <section class="grid two">
      <div id="primary" class="panel"></div>
      <aside id="secondary" class="panel"></aside>
    </section>
  </main>
  <script>
    const state = { data: null, view: "events", auto: null };
    const token = new URLSearchParams(location.search).get("token") || "";
    const apiUrl = () => "/api/dashboard?event_limit=120" + (token ? "&token=" + encodeURIComponent(token) : "");
    const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const short = (v, n = 140) => { const s = String(v ?? ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
    const pill = (text, kind = "") => `<span class="pill ${kind}">${esc(text)}</span>`;
    function metric(label, value, hint = "") {
      return `<div class="metric"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint)}</div></div>`;
    }
    async function load() {
      document.querySelector("#error").classList.add("hide");
      try {
        const response = await fetch(apiUrl(), { headers: token ? { "X-PaperWatcher-Token": token } : {} });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        state.data = await response.json();
        render();
      } catch (err) {
        const el = document.querySelector("#error");
        el.textContent = `加载失败 / Load failed: ${err.message}`;
        el.classList.remove("hide");
      }
    }
    async function postJson(path, payload) {
      const response = await fetch(path + (token ? "?token=" + encodeURIComponent(token) : ""), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { "X-PaperWatcher-Token": token } : {})
        },
        body: JSON.stringify(payload)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      return data;
    }
    function render() {
      const d = state.data;
      if (!d) return;
      document.querySelector("#subtitle").textContent = `Sources ${d.status.sources.enabled}/${d.status.sources.total} · Events ${d.status.events.total} · Last scan ${d.status.background.last_scan_at || "none"}`;
      document.querySelector("#metrics").innerHTML = [
        metric("Enabled Sources", d.status.sources.enabled, `${d.status.sources.total} total`),
        metric("Failed Sources", d.status.sources.failed, d.status.sources.failed ? "needs attention" : "clean"),
        metric("Events", d.status.events.total, d.status.events.last_seen_at || "none"),
        metric("Users", d.status.users.total, d.status.users.ids.join(", ")),
        metric("Candidates", d.status.candidates.pending, `${d.status.candidates.approved} approved`),
        metric("Reviews", d.status.conference_reviews.total, d.status.conference_reviews.last_reviewed_at || "none")
      ].join("");
      renderPrimary();
      renderSecondary();
    }
    function renderPrimary() {
      const d = state.data;
      const p = document.querySelector("#primary");
      if (state.view === "events") p.innerHTML = `<h2>Recent Events</h2>${eventsHtml(d.events)}`;
      if (state.view === "conference_pages") p.innerHTML = `<h2>Conference Page Diagnostics</h2>${conferencePagesHtml(d.conference_pages)}`;
      if (state.view === "sources") p.innerHTML = `<h2>Sources</h2>${sourcesHtml(d.sources)}`;
      if (state.view === "health") p.innerHTML = `<h2>Source Health</h2>${healthHtml(d.source_health)}`;
      if (state.view === "users") p.innerHTML = `<h2>Users</h2>${usersHtml(d.users)}`;
      if (state.view === "reviews") p.innerHTML = `<h2>Conference Reviews</h2>${reviewsHtml(d.conference_reviews)}`;
      if (state.view === "candidates") p.innerHTML = `<h2>Candidates</h2>${candidatesHtml(d.candidates)}`;
    }
    function renderSecondary() {
      const d = state.data;
      const due = d.source_health.filter(x => x.due && x.enabled).length;
      const failed = d.source_health.filter(x => x.last_error || String(x.verification_status || "").includes("failed"));
      document.querySelector("#secondary").innerHTML = `
        <h2>Operational Summary</h2>
        <table>
          <tbody>
            <tr><th>Due enabled sources</th><td>${due}</td></tr>
            <tr><th>Failed sources</th><td>${failed.length ? failed.map(x => esc(x.source_id)).join("<br>") : "none"}</td></tr>
            <tr><th>Source types</th><td>${Object.entries(d.source_type_counts).map(([k,v]) => `${esc(k)}: ${v}`).join("<br>")}</td></tr>
            <tr><th>CCF levels</th><td>${Object.entries(d.ccf_counts).map(([k,v]) => `${esc(k)}: ${v}`).join("<br>")}</td></tr>
          </tbody>
        </table>`;
    }
    function eventsHtml(events) {
      if (!events.length) return `<div class="empty">No events.</div>`;
      return `<div class="list">${events.map(e => `<div class="event">
        <div class="title">${e.link ? `<a href="${esc(e.link)}" target="_blank" rel="noreferrer">${esc(e.title)}</a>` : esc(e.title)}</div>
        <div class="meta">${esc(e.seen_at)} · ${esc(e.source_id)} · ${esc(e.source_type)}</div>
        ${e.raw?.excerpt ? `<div class="meta">${esc(short(e.raw.excerpt, 220))}</div>` : ""}
      </div>`).join("")}</div>`;
    }
    function conferencePagesHtml(rows) {
      if (!rows.length) return `<div class="empty">No conference page diagnostics yet.</div>`;
      return `<table><thead><tr><th>Source</th><th>Mode</th><th>Result</th><th>Review</th><th>Details</th></tr></thead><tbody>
        ${rows.map(row => {
          const review = row.review || {};
          const resultParts = [];
          if (row.snapshot_only) resultParts.push(pill("snapshot only", "warn"));
          else if (row.retry_used) resultParts.push(pill("retry used", "good"));
          else resultParts.push(pill("parsed", "good"));
          if (row.supervisor_error || row.review_error) resultParts.push(pill("error", "bad"));
          const reviewBits = [];
          if (review.decision) reviewBits.push(`decision=${review.decision}`);
          if (review.confidence !== undefined) reviewBits.push(`confidence=${review.confidence}`);
          if (review.reason) reviewBits.push(short(review.reason, 120));
          const detailBits = [];
          if (row.matched_layout) detailBits.push(`layout=${row.matched_layout}`);
          if (row.retry_layout) detailBits.push(`retry=${row.retry_layout}`);
          if (row.initial_candidate_count !== undefined) detailBits.push(`initial=${row.initial_candidate_count}`);
          if (row.final_candidate_count !== undefined) detailBits.push(`final=${row.final_candidate_count}`);
          if (row.supervisor_error) detailBits.push(`supervisor_error=${short(row.supervisor_error, 120)}`);
          if (row.review_error) detailBits.push(`review_error=${short(row.review_error, 120)}`);
          return `<tr>
            <td>${esc(row.source_id)}<br>${esc(row.source_name || "")}<br>${esc(row.seen_at || "")}</td>
            <td>${esc(row.analysis_mode || "-")}</td>
            <td>${resultParts.join("<br>")}</td>
            <td>${reviewBits.map(item => esc(item)).join("<br>")}</td>
            <td>${esc(detailBits.join(" · "))}</td>
          </tr>`;
        }).join("")}
      </tbody></table>`;
    }
    function sourcesHtml(rows) {
      return `<table><thead><tr><th>ID</th><th>Name</th><th>Type</th><th>CCF</th><th>Priority</th><th>Status</th></tr></thead><tbody>
        ${rows.map(s => `<tr><td>${esc(s.id)}</td><td>${esc(s.name)}</td><td>${pill(s.source_type)}</td><td>${esc(s.ccf_level)}</td><td>${s.priority}</td><td>${s.enabled ? pill("enabled", "good") : pill("disabled", "warn")}</td></tr>`).join("")}
      </tbody></table>`;
    }
    function healthHtml(rows) {
      return `<table><thead><tr><th>Source</th><th>Last Scan</th><th>Next Scan</th><th>Due</th><th>Error</th></tr></thead><tbody>
        ${rows.map(r => `<tr><td>${esc(r.source_id)}<br>${pill(r.source_type)}</td><td>${esc(r.last_scan_at || "-")}</td><td>${esc(r.next_scan_after || "-")}</td><td>${r.due ? pill("due", "warn") : pill("wait", "good")}</td><td>${r.last_error ? esc(short(r.last_error, 180)) : ""}</td></tr>`).join("")}
      </tbody></table>`;
    }
    function usersHtml(rows) {
      return `<table><thead><tr><th>User</th><th>Sources</th><th>Enabled Coverage</th><th>Subscribed IDs</th></tr></thead><tbody>
        ${rows.map(u => `<tr><td>${esc(u.id)}<br>${esc(u.display_name)}</td><td>${u.source_count}</td><td>${u.enabled_coverage}</td><td>${esc(u.sources.join(", "))}</td></tr>`).join("")}
      </tbody></table>`;
    }
    function reviewsHtml(rows) {
      if (!rows.length) return `<div class="empty">No conference reviews.</div>`;
      return `<table><thead><tr><th>Review</th><th>Venue</th><th>Action</th><th>Confidence</th><th>URL</th></tr></thead><tbody>
        ${rows.map(r => `<tr><td>${esc(r.review_id)}<br>${esc(r.reviewed_at)}</td><td>${esc(r.venue_id)} ${esc(r.year)}</td><td>${pill(r.action, r.action === "monitor_accepted_page" ? "good" : "warn")}<br>${esc(r.accepted_info_status)}</td><td>${esc(r.confidence)}</td><td>${r.accepted_info_url ? `<a href="${esc(r.accepted_info_url)}" target="_blank" rel="noreferrer">${esc(short(r.accepted_info_url, 70))}</a>` : ""}</td></tr>`).join("")}
      </tbody></table>`;
    }
    function candidatesHtml(rows) {
      if (!rows.length) return `<div class="empty">No candidates.</div>`;
      return `<div id="candidate-notice" class="notice hide"></div>
      <table><thead><tr><th>Candidate</th><th>Venue</th><th>Status</th><th>Confidence</th><th>URL</th><th>Action</th></tr></thead><tbody>
        ${rows.map(c => `<tr><td>${esc(c.candidate_id)}<br>${esc(c.source_id)}</td><td>${esc(c.venue_id)} ${esc(c.year)}</td><td>${pill(c.status, c.status === "pending" ? "warn" : "good")}<br>${esc(c.probe_status)}</td><td>${esc(c.confidence)}</td><td><a href="${esc(c.url)}" target="_blank" rel="noreferrer">${esc(short(c.url, 80))}</a></td><td>${candidateActionsHtml(c)}</td></tr>`).join("")}
      </tbody></table>`;
    }
    function candidateActionsHtml(c) {
      if (c.status !== "pending") return "";
      return `<div class="actions">
        <button type="button" data-candidate-preview="${esc(c.candidate_id)}">Preview</button>
        <button class="primary" type="button" data-candidate-approve="${esc(c.candidate_id)}">Approve</button>
      </div>`;
    }
    async function approveCandidate(candidateId, dryRun) {
      const button = document.querySelector(`[data-candidate-${dryRun ? "preview" : "approve"}="${CSS.escape(candidateId)}"]`);
      if (button) button.disabled = true;
      try {
        if (!dryRun && !confirm(`Approve candidate ${candidateId} into config/sources.yaml and root subscriptions?`)) return;
        const result = await postJson("/api/candidates/approve", { candidate_id: candidateId, dry_run: dryRun });
        if (dryRun) {
          alert(result.message);
        } else {
          const notice = document.querySelector("#candidate-notice");
          if (notice) {
            notice.textContent = `${result.candidate_id} approved as ${result.source_id}.`;
            notice.classList.remove("hide");
          }
          await load();
        }
      } catch (err) {
        const el = document.querySelector("#error");
        el.textContent = `操作失败 / Operation failed: ${err.message}`;
        el.classList.remove("hide");
      } finally {
        if (button) button.disabled = false;
      }
    }
    document.querySelector("#refresh").addEventListener("click", load);
    document.querySelector("#auto").addEventListener("click", (event) => {
      if (state.auto) {
        clearInterval(state.auto); state.auto = null; event.target.textContent = "Auto refresh: off"; event.target.setAttribute("aria-pressed", "false");
      } else {
        state.auto = setInterval(load, 30000); event.target.textContent = "Auto refresh: 30s"; event.target.setAttribute("aria-pressed", "true");
      }
    });
    document.querySelectorAll(".tab").forEach(btn => btn.addEventListener("click", () => {
      state.view = btn.dataset.view;
      document.querySelectorAll(".tab").forEach(x => x.setAttribute("aria-selected", String(x === btn)));
      renderPrimary();
    }));
    document.addEventListener("click", (event) => {
      const preview = event.target.closest("[data-candidate-preview]");
      if (preview) {
        approveCandidate(preview.dataset.candidatePreview, true);
        return;
      }
      const approve = event.target.closest("[data-candidate-approve]");
      if (approve) approveCandidate(approve.dataset.candidateApprove, false);
    });
    load();
  </script>
</body>
</html>
"""
