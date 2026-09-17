#!/usr/bin/env python3
"""Render the showcase pages with fixture data, once per theme.

The point is choosing between design styles without a Kindle in hand: each
theme gets the same four fixture pages — three editions covering the figure
kinds and the server-built home grid — written as full-size PNGs plus one
side-by-side contact sheet. Everything goes through the real pipeline —
Chromium render, Floyd-Steinberg dither to the panel's 16 grays — so what you
see is what the glass gets (minus reflective-contrast loss: verify the winner
on the device last).

Usage (from mcp_server/):

    uv run scripts/preview_themes.py                # every theme
    uv run scripts/preview_themes.py classic noir   # just these

Writes preview/<theme>/<fixture>.png and preview/contact_sheet.png.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from kindle_gazette import browser, config, renderers

OUT_DIR = Path(__file__).resolve().parent.parent / "preview"

# The four showcase pages — the front page
# plus three editions chosen so that between them they exercise every figure
# kind a theme can restyle, `image` aside (that one is agent-supplied pixels,
# with nothing for a theme to style). The fixture name is the PNG's name.
FIXTURES: list[tuple[str, str, dict]] = [
    # (a) chart-heavy: the geometry figures, all computed in renderers.py.
    ("charts", "edition", {
        "title": "The Overnight Dispatch",
        "byline": "research-agent · morning edition",
        "sections": [
            {"text": "Markets drifted sideways overnight while the build farm "
                     "quietly cleared its backlog. Two things deserve a glance "
                     "before noon."},
            {"heading": "Numbers", "figure": {"kind": "stat_row", "stats": [
                {"value": "74", "unit": "/100", "label": "Readiness", "delta": "-6", "direction": "down"},
                {"value": "92", "unit": "ms", "label": "HRV", "delta": "-3", "direction": "down"},
                {"value": "4", "label": "Jobs green", "delta": "+1", "direction": "up"},
            ]}},
            {"text": "The trend matters more than the level: the baseline has "
                     "held for three weeks, and this morning's dip sits well "
                     "inside normal variation.",
             "figure": {"kind": "line_chart", "baseline": 95,
                        "x_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                        "series": [{"label": "HRV", "values": [98, 96, 99, 94, 95, 91, 92]},
                                   {"label": "Resting HR", "values": [88, 90, 87, 91, 90, 93, 92]}],
                        "caption": "Two series, told apart by dash pattern"}},
            {"figure": {"kind": "sparkline", "values": [98, 96, 99, 94, 95, 91, 92],
                        "baseline": 95,
                        "caption": "7-day trend, hovering just under the 95 ms baseline"}},
            {"heading": "Budgets", "figure": {"kind": "bars", "bars": [
                {"label": "Protein", "value": 120, "max": 160, "target": 140},
                {"label": "Water", "value": 1.8, "max": 3},
                {"label": "Steps", "value": 5500, "max": 10000},
                {"label": "Focus hours", "value": 1.2, "max": 4},
            ]}},
            {"figure": {"kind": "stacked_bar", "max": 500, "segments": [
                {"label": "Carbs", "value": 210},
                {"label": "Protein", "value": 120},
                {"label": "Fat", "value": 60},
                {"label": "Fiber", "value": 30},
            ], "caption": "Calories against a 500 kcal budget"}},
            {"heading": "Sleep stages", "figure": {
                "kind": "heatmap",
                "row_labels": ["Deep", "REM", "Light", "Awake", "Total"],
                "col_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                "rows": [[42, 51, 38, 60, 47, 22, 55],
                         [88, 74, 91, 66, 80, 45, 72],
                         [120, 133, 118, 141, 126, 99, 130],
                         [14, 9, 21, 0, 12, 31, 18],
                         [264, 267, 268, None, 265, 197, 275]],
                "caption": "Minutes per stage; Thursday's total never synced"}},
        ],
    }),
    # (b) the tabular / list / band figures: denser, more rules per page.
    ("tables", "edition", {
        "title": "Operations Report",
        "byline": "ops-agent · 06:00",
        "sections": [
            {"text": "Nothing is on fire. Two things deserve a glance before "
                     "noon, and one of them has been waiting since Tuesday."},
            {"figure": {"kind": "callout", "style": "alert",
                        "text": "backup-check has failed three nights running"}},
            {"figure": {"kind": "table",
                        "columns": ["Job", "Last run", "Result"],
                        "align": ["left", "left", "right"],
                        "rows": [["backup-check", "03:00", "FAILED"],
                                 ["log-rotate", "05:15", "OK"],
                                 ["cert-renew", "05:20", "OK"],
                                 ["disk-usage", "05:40", "81%"],
                                 ["index-rebuild", "05:52", "OK"]],
                        "caption": "Job states as of this edition"}},
            {"heading": "Before noon", "figure": {"kind": "checklist", "items": [
                {"text": "Re-run backup-check by hand", "state": "open"},
                {"text": "Rotate the signing key", "state": "done"},
                {"text": "Drain the staging queue", "state": "done"},
                {"text": "File the incident write-up", "state": "done"},
                {"text": "Chase the vendor invoice", "state": "skipped"},
            ]}},
            {"heading": "Overnight", "figure": {"kind": "timeline", "events": [
                {"time": "23:40", "text": "Backup started"},
                {"time": "03:00", "text": "backup-check failed", "emphasis": True},
                {"time": "05:15", "text": "Log rotation completed"},
                {"time": "06:50", "text": "Edition rendered"},
            ]}},
            {"heading": "The full log", "figure": {
                "kind": "qr", "data": "https://example.invalid/gazette/ops",
                "caption": "Tonight's run log, on another screen"}},
        ],
    }),
    # (c) an index edition: link_list rows are the only interactive figure, so
    # this is the page that shows whether a theme's navigation reads tappable.
    ("index", "edition", {
        "title": "The Dispatch",
        "byline": "research-agent",
        "sections": [
            {"text": "Three editions filed since midnight."},
            {"figure": {"kind": "link_list", "links": [
                {"text": "Morning briefing", "nav_target": "news/briefing", "note": "07:02"},
                {"text": "Markets", "nav_target": "news/markets", "note": "6 charts"},
                {"text": "Overnight wire", "nav_target": "news/wire", "note": "23 items"},
                {"text": "Weather", "nav_target": "weather", "note": "updated 05:40"},
                {"text": "Yesterday's edition", "nav_target": "news/archive", "note": "archived"},
            ], "caption": "In this edition"}},
        ],
    }),
    # (d) home: built by the server from stored cards, never by an agent.
    ("home", "home", {
        "_home": True,
        "title": "Gazette",
        "cards": [
            {"title": "Operations", "summary": ["4 jobs, 1 failing", "backups stale since Tue"], "nav_target": "ops"},
            {"title": "Health", "summary": ["Readiness 74/100", "HRV 92 ms, under baseline"], "nav_target": "health"},
            {"title": "Nutrition", "summary": ["120/160 g protein"], "nav_target": "life/nutrition"},
            {"title": "The Dispatch", "summary": ["Fresh overnight edition", "8 sections",
                                                  "Markets, wire and weather in one file"],
             "nav_target": "news/dispatch"},
            {"title": "Weather", "summary": ["18°C, clearing by noon"], "nav_target": "weather"},
        ],
    }),
]

_SCALE = 4          # contact-sheet cells at 1/4 size: 268x362
_LABEL_H = 40       # theme-name band above each column
_PAD = 12

# The departure theme is designed around a condensed sans; if none of the
# faces in its --font-condensed chain exists on the render host, everything
# falls back to regular-width Helvetica and the layout breaks (row metrics
# assume condensed set widths). Chromium is the authority on which fonts
# resolve, so measure there: two same-text spans, condensed stack vs plain
# stack, compared via the tap-map bounding boxes render_page already returns.
_CONDENSED_STACK = ('"Arial Narrow", "DejaVu Sans Condensed", '
                    '"Liberation Sans Narrow", "Helvetica Neue Condensed", '
                    'Helvetica, sans-serif')
_CONDENSED_CHECK_HTML = f"""<!doctype html><html><head><style>
body {{ margin: 0; font-size: 52px; white-space: nowrap; }}
span {{ display: inline-block; }}
#cond {{ font-family: {_CONDENSED_STACK}; }}
#reg {{ font-family: Helvetica, sans-serif; }}
</style></head><body>
<span id="cond" data-action="probe" data-label="condensed">THE DISPATCH 0123456789</span><br>
<span id="reg" data-action="probe" data-label="regular">THE DISPATCH 0123456789</span>
</body></html>"""


def _check_condensed_face() -> None:
    _png, taps = browser.render_page(_CONDENSED_CHECK_HTML)
    widths = {tap["label"]: tap["w"] for tap in taps}
    if widths.get("condensed", 0) >= widths.get("regular", 0):
        print("WARNING: no condensed font face is available on this host — "
              "the 'departure' theme will render in regular-width Helvetica "
              "and its layout will break. Install the DejaVu/Liberation extra "
              "font packages, or drop 'departure' from the shipped set.")


def _font(size: int):
    try:
        return ImageFont.load_default(size)
    except TypeError:  # older Pillow: fixed-size bitmap font only
        return ImageFont.load_default()


def _render_fixture(kind: str, name: str, data: dict) -> renderers.RenderResult:
    """One fixture through the real renderer — editions paginate, home doesn't."""
    if kind == "home":
        return renderers.render_home(dict(data))
    return renderers.render_edition(dict(data), name)


def _render_theme(theme: str) -> dict[str, Image.Image]:
    """Render all fixtures in `theme`, save full-size PNGs, return first pages."""
    config.THEME = theme
    out = OUT_DIR / theme
    out.mkdir(parents=True, exist_ok=True)
    firsts: dict[str, Image.Image] = {}
    for name, kind, data in FIXTURES:
        result = _render_fixture(kind, name, data)
        for i, (png, _taps) in enumerate(result.pages):
            suffix = "" if len(result.pages) == 1 else f"_p{i + 1}"
            (out / f"{name}{suffix}.png").write_bytes(png)
        firsts[name] = Image.open(BytesIO(result.pages[0][0])).convert("L")
        print(f"  {theme}/{name}: {len(result.pages)} page(s)")
    return firsts


def _contact_sheet(pages: dict[str, dict[str, Image.Image]]) -> Image.Image:
    themes = list(pages)
    names = [name for name, _kind, _data in FIXTURES]
    cell_w = config.SCREEN_WIDTH // _SCALE
    cell_h = config.SCREEN_HEIGHT // _SCALE
    width = _PAD + len(themes) * (cell_w + _PAD)
    height = _LABEL_H + len(names) * (cell_h + _PAD)
    sheet = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(sheet)
    for col, theme in enumerate(themes):
        x = _PAD + col * (cell_w + _PAD)
        draw.text((x, _PAD), theme, font=_font(24), fill=0)
        for row, name in enumerate(names):
            y = _LABEL_H + row * (cell_h + _PAD)
            sheet.paste(pages[theme][name].resize((cell_w, cell_h)), (x, y))
    return sheet


def main() -> None:
    themes = sys.argv[1:] or renderers.available_themes()
    unknown = set(themes) - set(renderers.available_themes())
    if unknown:
        sys.exit(f"Unknown theme(s): {', '.join(sorted(unknown))}. "
                 f"Available: {', '.join(renderers.available_themes())}")
    pages = {}
    try:
        if "departure" in themes:
            _check_condensed_face()
        for theme in themes:
            pages[theme] = _render_theme(theme)
    finally:
        browser.shutdown()
    sheet_path = OUT_DIR / "contact_sheet.png"
    _contact_sheet(pages).save(sheet_path)
    print(f"Contact sheet: {sheet_path}")


if __name__ == "__main__":
    main()
