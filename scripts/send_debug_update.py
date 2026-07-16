#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"debug-event", "fake-rss", "fake-webpage"}:
        command = argv.pop(0)
    else:
        command = "debug-event"

    if command == "debug-event":
        return send_debug_event(argv)
    if command == "fake-rss":
        return serve_fake_rss(argv)
    if command == "fake-webpage":
        return serve_fake_webpage(argv)
    print(f"unknown command: {command}", file=sys.stderr)
    return 2


def send_debug_event(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Send a debug update event to PaperWatcher background port.")
    parser.add_argument("--url", default="http://127.0.0.1:8765/debug/update")
    parser.add_argument("--user", action="append", dest="users", default=None, help="Deprecated. User routing is now based on source subscriptions.")
    parser.add_argument("--title", default="Debug Paper Update")
    parser.add_argument("--link", default="https://example.com/debug-paper")
    parser.add_argument("--paper-id", help="Optional stable debug paper id.")
    parser.add_argument("--source-id", default="debug_fake_rss")
    args = parser.parse_args(argv)

    payload = {
        "title": args.title,
        "link": args.link,
        "source_id": args.source_id,
        "raw": {"debug": True},
    }
    if args.paper_id:
        payload["paper_id"] = args.paper_id

    request = Request(
        args.url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"failed to connect to debug server: {exc}", file=sys.stderr)
        return 1

    print(body)
    return 0


def serve_fake_rss(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Serve a fake RSS feed for PaperWatcher background tests.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--title", default="Fake RSS Paper")
    parser.add_argument("--link", default="https://example.com/fake-rss-paper")
    parser.add_argument("--guid", default=None, help="Stable RSS item guid. Change it to simulate a new paper.")
    args = parser.parse_args(argv)

    guid = args.guid or f"fake-rss-{datetime.now(UTC).timestamp()}"
    rss_xml = build_fake_rss(title=args.title, link=args.link, guid=guid)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in {"/", "/feed.xml"}:
                self.send_response(404)
                self.end_headers()
                return
            raw = rss_xml.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args) -> None:
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Fake RSS listening on http://{args.host}:{args.port}/feed.xml")
    print(f"guid={guid}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFake RSS stopped.")
    finally:
        server.server_close()
    return 0


def serve_fake_webpage(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Serve a fake webpage for PaperWatcher website_watch tests.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--title", default="Accepted Papers")
    parser.add_argument("--body", default="Paper A")
    parser.add_argument(
        "--paper",
        action="append",
        default=None,
        help="Paper title to render as a linked list item. Can be repeated.",
    )
    args = parser.parse_args(argv)

    html_text = build_fake_webpage(title=args.title, body=args.body, papers=args.paper or [])

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in {"/", "/accepted-papers"}:
                self.send_response(404)
                self.end_headers()
                return
            raw = html_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args) -> None:
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Fake webpage listening on http://{args.host}:{args.port}/accepted-papers")
    print("css_selector=main")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFake webpage stopped.")
    finally:
        server.server_close()
    return 0


def build_fake_rss(*, title: str, link: str, guid: str) -> str:
    now = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
  <channel>
    <title>PaperWatcher Fake RSS</title>
    <link>https://example.com/fake-rss</link>
    <description>Debug RSS feed for PaperWatcher</description>
    <item>
      <title>{html.escape(title)}</title>
      <link>{html.escape(link)}</link>
      <guid isPermaLink="false">{html.escape(guid)}</guid>
      <pubDate>{now}</pubDate>
      <description>Fake RSS item generated for PaperWatcher business-flow testing.</description>
    </item>
  </channel>
</rss>
"""


def build_fake_webpage(*, title: str, body: str, papers: list[str] | None = None) -> str:
    paper_items = "\n".join(
        f'      <li><a href="/papers/{index}">{html.escape(paper)}</a></li>'
        for index, paper in enumerate(papers or [], start=1)
    )
    paper_list = f"\n      <ul>\n{paper_items}\n      </ul>" if paper_items else ""
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>{html.escape(title)}</title>
  </head>
  <body>
    <main>
      <h1>{html.escape(title)}</h1>
      <p>{html.escape(body)}</p>
{paper_list}
    </main>
  </body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
