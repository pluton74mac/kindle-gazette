"""Shared helpers for the kindle-gazette test suite (no kindle_gazette imports
at module top — conftest.py sets KINDLE_GAZETTE_DATA_DIR first)."""
from __future__ import annotations

import re
import socket
import urllib.error
import urllib.request


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_get(port: int, path: str, token: str | None = None):
    """GET against the test server; returns (status, headers, body_bytes).
    HTTP errors are returned, not raised."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token is not None:
        req.add_header("X-Gazette-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def make_meta(path: str, taps: list[dict], title: str = "View", view_type: str = "edition",
              back: str | None = "home", refresh_sec: int = 900,
              back_default: bool = False) -> dict:
    """A meta dict shaped exactly like server._save_pages builds them.
    `back_default=True` marks the edition as not having set `back` itself, so
    http_server resolves the agent's front page at fetch time."""
    from kindle_gazette import store

    return {
        "version": 1,
        "title": title,
        "image": f"/images/{store.path_to_name(path)}.png",
        "taps": taps,
        "back": back,
        "refresh_sec": refresh_sec,
        "error": None,
        "cache": {"key": path, "ttl_sec": refresh_sec},
        "_view_type": view_type,
        "_back_default": back_default,
    }


# The minimal-but-representative edition: prose only, both block kinds.
EDITION = {
    "title": "Weekly Digest",
    "byline": "research-agent",
    "body": "First paragraph of the digest.\n\n## A heading\n\nMore text after the heading.",
}

# The showcase edition: one page exercising a spread of figure kinds. Used
# wherever a test wants "an edition with real content in it" — theme renders,
# smoke renders — so a template branch that breaks can't hide behind prose.
SHOWCASE_EDITION = {
    "title": "The Overnight Dispatch",
    "byline": "research-agent · morning edition",
    "sections": [
        {"text": "Markets drifted sideways overnight while the build farm quietly "
                 "cleared its backlog. Two things deserve a glance before noon."},
        {"heading": "Numbers", "figure": {"kind": "stat_row", "stats": [
            {"value": "74", "unit": "/100", "label": "Readiness", "delta": "-6", "direction": "down"},
            {"value": "92", "unit": "ms", "label": "HRV", "delta": "-3", "direction": "down"},
            {"value": "4", "label": "Jobs green", "delta": "+1", "direction": "up"},
        ]}},
        {"figure": {"kind": "line_chart", "baseline": 95,
                    "x_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    "series": [{"label": "HRV", "values": [98, 96, 99, 94, 95, 91, 92]},
                               {"label": "Resting HR", "values": [88, 90, 87, 91, 90, 93, 92]}],
                    "caption": "Seven days, one baseline"}},
        {"heading": "Jobs", "figure": {
            "kind": "table", "columns": ["Job", "Last run", "State"],
            "align": ["left", "left", "right"],
            "rows": [["backup-check", "03:00", "FAILED"], ["log-rotate", "05:15", "OK"]],
            "caption": "Job states as of this edition"}},
        {"figure": {"kind": "callout", "text": "Backups have been stale since Tuesday.",
                    "style": "alert"}},
        {"heading": "Elsewhere", "figure": {"kind": "link_list", "links": [
            {"text": "Fleet status", "nav_target": "ops/fleet", "note": "2 min ago"},
            {"text": "Nutrition log", "nav_target": "life/nutrition", "note": "yesterday"},
        ], "caption": "Other editions"}},
    ],
}


# ── awk-equivalent line scanner, mimicking gazette.sh's hit_test() parser ──

def _awk_num(field: str, line: str) -> str:
    v = re.sub(r'.*"' + field + r'"[ \t]*:[ \t]*', "", line)
    return re.sub(r"[^0-9-].*", "", v)


def _awk_str(field: str, line: str) -> str:
    v = re.sub(r'.*"' + field + r'"[ \t]*:[ \t]*"', "", line)
    return re.sub(r'".*', "", v)


def awk_hit_test(body_text: str, tx: int, ty: int):
    """Line-by-line port of the awk program in kindle/bin/gazette.sh hit_test().
    Returns (action, target) for the first tap rect containing (tx, ty), else None.
    Like awk's `x+0`, empty strings coerce to 0."""
    x = y = w = h = act = tgt = ""

    def num(s: str) -> int:
        try:
            return int(s)
        except ValueError:
            return 0

    for line in body_text.splitlines():
        if '"x"' in line:
            x = _awk_num("x", line)
        if '"y"' in line:
            y = _awk_num("y", line)
        if '"w"' in line:
            w = _awk_num("w", line)
        if '"h"' in line:
            h = _awk_num("h", line)
        if '"action"' in line:
            act = _awk_str("action", line)
        if '"target"' in line:
            tgt = _awk_str("target", line)
        if "}" in line and x != "":
            if num(x) <= tx < num(x) + num(w) and num(y) <= ty < num(y) + num(h):
                return act, tgt
            x = y = w = h = act = tgt = ""
    return None
