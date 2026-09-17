"""http_server.py against a real ThreadingHTTPServer on an ephemeral port."""
import http.server
import json
import threading

import pytest

from kindle_gazette import config, http_server, store

import _util

PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"


def _save_simple_view():
    meta = _util.make_meta("ops/web", taps=[], title="Web")
    store.save_view("ops/web", meta, PNG)


# ── /health ──

def test_health_open_without_auth(gazette_server):
    status, _, body = _util.http_get(gazette_server, "/health")
    assert status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["port"] == config.HTTP_PORT
    assert payload["views"] == 0


def test_health_open_even_with_auth_enabled(gazette_server, monkeypatch):
    monkeypatch.setattr(config, "AUTH_TOKEN", "s3cret")
    status, _, body = _util.http_get(gazette_server, "/health")  # no token sent
    assert status == 200
    assert json.loads(body)["ok"] is True


# ── auth on /view and /images ──

def test_view_requires_token(gazette_server, monkeypatch):
    _save_simple_view()
    monkeypatch.setattr(config, "AUTH_TOKEN", "s3cret")
    assert _util.http_get(gazette_server, "/view?path=ops/web")[0] == 401
    assert _util.http_get(gazette_server, "/view?path=ops/web", token="wrong")[0] == 401
    assert _util.http_get(gazette_server, "/view?path=ops/web", token="s3cret")[0] == 200
    # busybox-wget style: token as query parameter
    assert _util.http_get(gazette_server, "/view?path=ops/web&token=s3cret")[0] == 200


def test_images_require_token(gazette_server, monkeypatch):
    _save_simple_view()
    monkeypatch.setattr(config, "AUTH_TOKEN", "s3cret")
    assert _util.http_get(gazette_server, "/images/ops_web.png")[0] == 401
    assert _util.http_get(gazette_server, "/images/ops_web.png", token="s3cret")[0] == 200
    assert _util.http_get(gazette_server, "/images/ops_web.png?token=s3cret")[0] == 200


def test_no_token_configured_means_open(gazette_server):
    _save_simple_view()
    assert _util.http_get(gazette_server, "/view?path=ops/web")[0] == 200


# ── content ──

def test_view_returns_meta(gazette_server):
    _save_simple_view()
    status, headers, body = _util.http_get(gazette_server, "/view?path=ops/web")
    assert status == 200
    assert headers["Content-Type"] == "application/json"
    assert int(headers["Content-Length"]) == len(body)
    assert json.loads(body)["title"] == "Web"


# ── default BACK target resolves to the agent's front page ──

BACK_TAP = {"x": 20, "y": 1338, "w": 170, "h": 90, "action": "navigate",
            "target": "home", "label": "Back"}
EXIT_TAP = {"x": 872, "y": 1338, "w": 180, "h": 90, "action": "exit",
            "target": "", "label": "Exit"}


def _save_edition(path: str, back_default: bool):
    meta = _util.make_meta(path, taps=[dict(BACK_TAP), dict(EXIT_TAP)],
                           back_default=back_default)
    store.save_view(path, meta, PNG)


def _fetched_back(gazette_server, path: str) -> tuple[str, str]:
    """(meta back, Back tap's target) as the Kindle would receive them."""
    _, _, body = _util.http_get(gazette_server, f"/view?path={path}")
    meta = json.loads(body)
    back_tap = next(t for t in meta["taps"] if t.get("label") == "Back")
    return meta["back"], back_tap["target"]


def test_default_back_resolves_to_agent_front_page(gazette_server):
    store.upsert_home_card("dispatch", "The Dispatch", ["3 editions"], "dispatch/index")
    _save_edition("dispatch/morning", back_default=True)
    assert _fetched_back(gazette_server, "dispatch/morning") == ("dispatch/index", "dispatch/index")
    # Non-Back taps are left alone.
    _, _, body = _util.http_get(gazette_server, "/view?path=dispatch/morning")
    exit_tap = next(t for t in json.loads(body)["taps"] if t["label"] == "Exit")
    assert exit_tap["target"] == ""


def test_explicit_back_is_never_overridden(gazette_server):
    store.upsert_home_card("dispatch", "The Dispatch", ["3 editions"], "dispatch/index")
    _save_edition("dispatch/morning", back_default=False)
    assert _fetched_back(gazette_server, "dispatch/morning") == ("home", "home")


def test_front_page_itself_backs_to_home(gazette_server):
    store.upsert_home_card("dispatch", "The Dispatch", ["3 editions"], "dispatch/index")
    _save_edition("dispatch/index", back_default=True)
    assert _fetched_back(gazette_server, "dispatch/index") == ("home", "home")


def test_continuation_pages_resolve_from_their_base(gazette_server):
    store.upsert_home_card("dispatch", "The Dispatch", ["3 editions"], "dispatch/index")
    _save_edition("dispatch/morning/p2", back_default=True)
    assert _fetched_back(gazette_server, "dispatch/morning/p2") == ("dispatch/index", "dispatch/index")


def test_agent_without_card_backs_to_home(gazette_server):
    _save_edition("dispatch/morning", back_default=True)
    assert _fetched_back(gazette_server, "dispatch/morning") == ("home", "home")


def test_single_segment_path_is_its_own_agent(gazette_server):
    store.upsert_home_card("dispatch", "The Dispatch", ["3 editions"], "dispatch")
    _save_edition("dispatch", back_default=True)
    # The front page itself — no self-loop, back stays home.
    assert _fetched_back(gazette_server, "dispatch") == ("home", "home")


def test_image_content_type_and_length(gazette_server):
    _save_simple_view()
    status, headers, body = _util.http_get(gazette_server, "/images/ops_web.png")
    assert status == 200
    assert headers["Content-Type"] == "image/png"
    assert int(headers["Content-Length"]) == len(body)
    assert body == PNG


# ── 404s ──

def test_404s(gazette_server):
    assert _util.http_get(gazette_server, "/view?path=no/such")[0] == 404
    assert _util.http_get(gazette_server, "/images/no_such.png")[0] == 404
    assert _util.http_get(gazette_server, "/images/../registry.json")[0] == 404
    assert _util.http_get(gazette_server, "/bogus")[0] == 404


# ── port sharing ──

def test_start_twice_second_returns_none(gazette_server):
    # A sibling kindle-gazette already owns the port: start() must detect it
    # via /health and return None instead of crashing.
    assert http_server.start() is None


def test_start_against_foreign_listener_raises(monkeypatch):
    class Quiet404(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_error(404)

        def log_message(self, *args):
            pass

    foreign = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet404)
    port = foreign.server_address[1]
    threading.Thread(target=foreign.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(config, "HTTP_HOST", "127.0.0.1")
        monkeypatch.setattr(config, "HTTP_PORT", port)
        with pytest.raises(OSError, match="KINDLE_GAZETTE_PORT"):
            http_server.start()
    finally:
        foreign.shutdown()
        foreign.server_close()


def test_start_against_ok_true_impostor_raises(monkeypatch):
    # Observed on hardware: a stale server from an earlier build answers
    # /health with ok:true but no "name" marker. Treating it as a sibling made
    # the real server run MCP-only and serve stale views — it must be treated
    # as a foreign listener instead.
    class OkTrueNoName(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"ok": True, "port": 0, "views": 3}, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    impostor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), OkTrueNoName)
    port = impostor.server_address[1]
    threading.Thread(target=impostor.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(config, "HTTP_HOST", "127.0.0.1")
        monkeypatch.setattr(config, "HTTP_PORT", port)
        with pytest.raises(OSError, match="KINDLE_GAZETTE_PORT"):
            http_server.start()
    finally:
        impostor.shutdown()
        impostor.server_close()
