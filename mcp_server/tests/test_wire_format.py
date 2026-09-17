"""THE wire-format regression guard.

The Kindle's gazette.sh parses /view JSON with a line-oriented awk program: it
needs every tap field on its own line and every tap object's closing "}" on its
own line. That only holds because store + http_server serialize with
json.dumps(..., indent=2). These tests exercise the REAL code paths (save_view
to disk, ViewHandler._json over a real socket) and then run a faithful port of
the awk parser over the raw bytes to prove a tap rect is still extractable.
"""
import json

from kindle_gazette import config, store

import _util

TAPS = [
    {"x": 0, "y": 0, "w": 1072, "h": 120, "action": "refresh", "target": "", "label": "Masthead"},
    {"x": 36, "y": 200, "w": 500, "h": 260, "action": "navigate", "target": "sports/readiness", "label": "Readiness"},
    {"x": 36, "y": 1340, "w": 200, "h": 80, "action": "navigate", "target": "home", "label": "Back"},
    {"x": 872, "y": 1340, "w": 200, "h": 80, "action": "exit", "target": "", "label": "Exit"},
]

TAP_FIELDS = ("x", "y", "w", "h", "action", "target", "label")


def _save_fixture_view():
    meta = _util.make_meta("sports/overview", TAPS, title="Sports")
    store.save_view("sports/overview", meta, b"\x89PNG-fake")
    return meta


def _assert_awk_parseable(raw_text: str, taps: list[dict]):
    lines = raw_text.splitlines()
    # Every tap field sits on its own line, one line per tap.
    for field in TAP_FIELDS:
        matching = [ln for ln in lines if f'"{field}"' in ln]
        assert len(matching) == len(taps), f'"{field}" must appear on exactly {len(taps)} lines'
        # No two rect fields share a line (compact JSON would collapse them).
        for ln in matching:
            others = [f for f in TAP_FIELDS if f != field and len(f) == 1]
            assert not any(f'"{o}"' in ln for o in others), f"multiple tap fields on one line: {ln!r}"
    # Each tap object's closing brace is on a line of its own.
    closers = [ln for ln in lines if ln.strip() in ("}", "},")]
    assert len(closers) >= len(taps)


def test_saved_meta_file_is_awk_parseable():
    _save_fixture_view()
    raw = (config.DATA_DIR / "sports_overview.json").read_text()
    _assert_awk_parseable(raw, TAPS)


def test_view_endpoint_is_awk_parseable(gazette_server):
    meta = _save_fixture_view()
    status, headers, body = _util.http_get(gazette_server, "/view?path=sports/overview")
    assert status == 200
    assert headers["Content-Type"] == "application/json"

    raw = body.decode()
    # Sanity: the wire body is the meta minus the internal _view_type field.
    parsed = json.loads(raw)
    expected = dict(meta)
    expected.pop("_view_type")
    assert parsed == expected
    assert "_view_type" not in raw

    _assert_awk_parseable(raw, TAPS)

    # The awk-equivalent scanner extracts the right rect for a tap point.
    assert _util.awk_hit_test(raw, 100, 300) == ("navigate", "sports/readiness")
    assert _util.awk_hit_test(raw, 900, 1350) == ("exit", "")
    assert _util.awk_hit_test(raw, 500, 60) == ("refresh", "")
    # A point in dead space hits nothing.
    assert _util.awk_hit_test(raw, 1000, 700) is None


def test_compact_json_would_break_the_parser():
    """Canary: proves the guard above is load-bearing. If someone 'optimizes'
    the serializer to compact JSON, the awk parser stops extracting taps."""
    meta = _util.make_meta("sports/overview", TAPS)
    compact = json.dumps(meta)  # what a well-meaning refactor would produce
    assert _util.awk_hit_test(compact, 100, 300) != ("navigate", "sports/readiness")
