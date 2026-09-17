"""Browser tier: real Chromium renders of everything the server can draw —
the home grid, the generated system/agents overview, and an edition.

Marked `browser` — skipped wholesale when no Chromium is resolvable, so the
unit tier still runs anywhere.
"""
import copy
from io import BytesIO

import pytest
from PIL import Image

from kindle_gazette import config, server, store

import _util

pytestmark = pytest.mark.browser


def _render(path, data):
    server.render_and_save(path, copy.deepcopy(data))
    meta = store.get_view_meta(path)
    assert meta is not None
    png = (config.DATA_DIR / "images" / f"{store.path_to_name(path)}.png").read_bytes()
    return meta, png


def _assert_png_contract(png_bytes):
    img = Image.open(BytesIO(png_bytes))
    assert img.size == (config.SCREEN_WIDTH, config.SCREEN_HEIGHT)
    assert img.mode == "L"
    # Panel-exact pixels: every value must be one of the 16 grays the 4-bit
    # E Ink glass can show (the render pipeline dithers to this palette).
    levels = {value for _count, value in img.getcolors(256)}
    assert levels <= {i * 17 for i in range(16)}, sorted(levels)


def _assert_taps_contract(taps):
    assert taps, "tap map must not be empty"
    for tap in taps:
        for field in ("x", "y", "w", "h"):
            assert isinstance(tap[field], int) and not isinstance(tap[field], bool), \
                f"{field} must be an int, got {tap[field]!r}"
        assert 0 <= tap["x"] < config.SCREEN_WIDTH
        assert 0 <= tap["y"] < config.SCREEN_HEIGHT
        assert tap["w"] > 0 and tap["h"] > 0
        assert tap["x"] + tap["w"] <= config.SCREEN_WIDTH
        assert tap["y"] + tap["h"] <= config.SCREEN_HEIGHT
        assert tap["action"] in ("navigate", "refresh", "exit")


def _labels(taps):
    return {t["label"] for t in taps}


# ── editions ──

@pytest.mark.parametrize("edition", [_util.EDITION, _util.SHOWCASE_EDITION],
                         ids=["prose", "showcase"])
def test_edition_renders_to_contract(edition):
    meta, png = _render("demo/edition", edition)
    _assert_png_contract(png)
    _assert_taps_contract(meta["taps"])

    # Masthead refresh tap is always present.
    assert any(t["action"] == "refresh" for t in meta["taps"])
    # An edition carries BACK (to `back`, default home) and EXIT.
    assert any(t["action"] == "navigate" and t["target"] == "home" and t["label"] == "Back"
               for t in meta["taps"])
    assert any(t["action"] == "exit" for t in meta["taps"])


def test_very_long_text_still_renders():
    """Overlong strings must wrap/clip inside the fixed viewport, not blow up."""
    long_str = "a-very-long-unbroken-token " * 40
    data = {"title": long_str, "byline": long_str, "sections": [
        {"heading": long_str, "text": long_str},
        {"figure": {"kind": "link_list", "links": [
            {"text": long_str, "nav_target": "a/b", "note": long_str},
        ]}},
    ]}
    meta, png = _render("demo/long_text", data)
    _assert_png_contract(png)
    _assert_taps_contract(meta["taps"])


# ── home ──

def test_home_has_exit_and_no_back():
    store.upsert_home_card("sports", "Readiness", ["74/100"], "sports/readiness")
    server.build_home_view()
    meta = store.get_view_meta("home")
    assert meta is not None
    _assert_taps_contract(meta["taps"])
    assert meta["back"] is None
    assert any(t["action"] == "exit" for t in meta["taps"])
    assert "Back" not in _labels(meta["taps"])
    # The pushed card is tappable on the home grid.
    assert any(t["action"] == "navigate" and t["target"] == "sports/readiness"
               for t in meta["taps"])
    # And the masthead refresh is there too.
    assert any(t["action"] == "refresh" for t in meta["taps"])
    _assert_png_contract((config.DATA_DIR / "images" / "home.png").read_bytes())


def test_empty_home_still_renders():
    """No agents yet: the grid falls back to its empty note, not an exception."""
    server.build_home_view()
    meta = store.get_view_meta("home")
    assert meta is not None
    _assert_taps_contract(meta["taps"])
    assert not [t for t in meta["taps"] if t["action"] == "navigate"]


def test_home_card_titles_and_summaries_render():
    long_str = "a-very-long-unbroken-token " * 40
    store.upsert_home_card("ops", long_str, [long_str, long_str], "ops/web")
    server.build_home_view()
    meta = store.get_view_meta("home")
    assert meta is not None
    _assert_taps_contract(meta["taps"])
    _assert_png_contract((config.DATA_DIR / "images" / "home.png").read_bytes())


# ── system/agents: an edition built from a link_list ──

def test_agents_overview_links_every_agent():
    store.upsert_home_card("sports", "Readiness", ["74/100"], "sports/readiness")
    store.upsert_home_card("ops", "Fleet", ["4 jobs"], "ops/fleet")
    server.build_agents_overview()

    meta = store.get_view_meta("system/agents")
    assert meta is not None
    _assert_taps_contract(meta["taps"])
    _assert_png_contract((config.DATA_DIR / "images" / "system_agents.png").read_bytes())

    targets = {t["target"] for t in meta["taps"] if t["action"] == "navigate"}
    assert {"sports/readiness", "ops/fleet"} <= targets
    # Rows are labeled with the card titles, and BACK still goes home.
    assert {"Readiness", "Fleet"} <= _labels(meta["taps"])
    assert meta["back"] == "home"


def test_agents_overview_with_no_agents_renders():
    server.build_agents_overview()
    meta = store.get_view_meta("system/agents")
    assert meta is not None
    _assert_taps_contract(meta["taps"])
