"""Kindle-facing HTTP server: the 3 endpoints the shell viewer polls.

Runs as a background thread inside the MCP process (stdio MCP, HTTP as a
thread, not a separate daemon). Pure read path over what `store.py` has
persisted to disk; it doesn't know or care whether an agent is currently
connected. The one thing computed per request — still a pure function of the
stored state — is the default BACK target: an edition that didn't set `back`
falls back to its agent's front page (the home card's nav_target), resolved at
fetch time so it stays correct whatever order the agent published in.
"""
from __future__ import annotations

import hmac
import json
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import config, store

_PAGE_SUFFIX = re.compile(r"/p\d+$")


def _with_resolved_back(path: str, meta: dict) -> dict:
    """Resolve the default BACK target for an edition that didn't set `back`:
    the agent's front page (its home card's nav_target) when one exists and
    this view isn't it, else the baked-in "home". Continuation pages resolve
    from their base path, so every page of an edition backs out to the same
    place. Rewrites both the meta field and the Back tap's target — the tap
    map is what the Kindle actually navigates by."""
    if not meta.get("_back_default"):
        return meta
    base = _PAGE_SUFFIX.sub("", path.strip("/"))
    agent_id = store.agent_id_for_path(base) or base
    card = store.get_home_cards().get(agent_id)
    front = (card or {}).get("nav_target", "").strip("/")
    if not front or front == base:
        return meta
    meta = dict(meta)
    meta["back"] = front
    meta["taps"] = [
        {**tap, "target": front} if tap.get("label") == "Back" else tap
        for tap in meta["taps"]
    ]
    return meta


class ViewHandler(BaseHTTPRequestHandler):
    server_version = "KindleGazette/1.0"

    def do_GET(self):
        parsed = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        # /health stays token-free: the Kindle probes it for reachability before
        # auth may be configured, and it leaks nothing beyond ok/port/view-count.
        if parsed.path != "/health" and not self._authorized(query):
            print(f"[http {time.strftime('%H:%M:%S')}] rejected unauthenticated request "
                  f"from {self.address_string()} for {parsed.path}", flush=True)
            self.send_error(401, "Missing or invalid token")
            return

        if parsed.path == "/view":
            self._handle_view(query.get("path", "home"))
        elif parsed.path.startswith("/images/"):
            self._handle_image(parsed.path[len("/images/"):])
        elif parsed.path == "/health":
            # "name" identifies this as a kindle-gazette server: the port-sharing
            # probe requires it, so a stale pre-rename server (or anything else)
            # holding the port fails loudly instead of silently serving stale views.
            self._json(200, {"ok": True, "name": "kindle-gazette", "port": config.HTTP_PORT,
                             "views": store.registry_count()})
        else:
            self.send_error(404, f"Unknown path: {parsed.path}")

    def _authorized(self, query: dict) -> bool:
        # Empty AUTH_TOKEN = auth disabled. The Kindle sends the token either as
        # an X-Gazette-Token header (gazette.sh) or ?token= (busybox wget has no
        # custom-header flag on some firmwares). Constant-time compare either way.
        if not config.AUTH_TOKEN:
            return True
        supplied = self.headers.get("X-Gazette-Token") or query.get("token") or ""
        return hmac.compare_digest(supplied, config.AUTH_TOKEN)

    def _handle_view(self, path: str):
        meta = store.get_view_meta(path)
        if meta is None:
            self.send_error(404, f"View not found: {path}")
            return
        self._json(200, _with_resolved_back(path, meta))

    def _handle_image(self, name: str):
        img_path = store.get_image_path(name)
        if img_path is None:
            self.send_error(404, "Image not found")
            return
        body = img_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict):
        # indent=2 is load-bearing, not cosmetic: the Kindle's awk tap parser
        # (gazette.sh) scans line-by-line and expects each field and each
        # tap object's closing "}" on its own line. Compact single-line JSON breaks it.
        body = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[http {time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}", flush=True)


def _is_gazette_health(port: int) -> bool:
    """True iff something on this port answers /health as a kindle-gazette server.

    Requires the "name" marker, not just ok:true — a stale server from an
    earlier build answers the same ok/port/views shape, and treating it as a
    sibling would silently serve its stale views (observed on hardware)."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
    if config.AUTH_TOKEN:
        req.add_header("X-Gazette-Token", config.AUTH_TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            payload = json.loads(resp.read())
            return payload.get("ok") is True and payload.get("name") == "kindle-gazette"
    except Exception:
        return False


def start() -> ThreadingHTTPServer | None:
    try:
        server = ThreadingHTTPServer((config.HTTP_HOST, config.HTTP_PORT), ViewHandler)
    except OSError as exc:
        # Bind failed — almost always EADDRINUSE from a sibling MCP process (each
        # agent framework spawns its own copy of this server over stdio). Disk is
        # the shared source of truth, so if a kindle-gazette instance already
        # serves this port we can safely run MCP-only instead of crashing.
        if _is_gazette_health(config.HTTP_PORT):
            print(f"[kindle-gazette] port {config.HTTP_PORT} already served by another "
                  f"kindle-gazette instance; continuing MCP-only against the shared data dir "
                  f"{config.DATA_DIR}", flush=True)
            return None
        raise OSError(
            f"Port {config.HTTP_PORT} is held by something that is not a kindle-gazette "
            f"server; pick a different KINDLE_GAZETTE_PORT."
        ) from exc
    server.daemon_threads = True  # don't let in-flight Kindle polls block process exit
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="kindle-gazette-http")
    thread.start()
    print(f"[kindle-gazette] HTTP server listening on {config.HTTP_HOST}:{config.HTTP_PORT}", flush=True)
    return server
