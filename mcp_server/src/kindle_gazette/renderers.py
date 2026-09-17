"""HTML/Chromium renderers.

There are exactly two renderers: `render_edition()` for everything an agent
publishes, and `render_home()` for the server-built home grid. Agents never
touch layout, e-ink, or tap-map geometry — they publish an edition (prose plus
figures) and this module massages that into Jinja template context (all
layout/styling lives in `templates/`), renders it in headless Chromium via
`browser.py`, and extracts the tap map from the DOM.

Grayscale-only palette note: e-ink has no color, so severity and emphasis are
communicated with fill darkness and text labels, not hue — the grays live in
the active theme's theme.css (templates/themes/<name>/).
"""
from __future__ import annotations

import base64
import math
import time
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

import qrcode
from jinja2 import Environment, FileSystemLoader
from qrcode.image.pil import PilImage

from . import browser, config

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_THEMES_DIR = _TEMPLATES_DIR / "themes"


def available_themes() -> list[str]:
    """Themes that can actually render: subdirectories of templates/themes/
    carrying a theme.css."""
    return sorted(p.name for p in _THEMES_DIR.iterdir() if (p / "theme.css").is_file())


def theme_dir() -> Path:
    """Directory of the active theme (config.THEME). A theme is a theme.css
    (design tokens) plus optional template overrides. Unknown names fail loudly
    so a typo'd KINDLE_GAZETTE_THEME can't silently render the default look."""
    directory = _THEMES_DIR / config.THEME
    if not (directory / "theme.css").is_file():
        raise ValueError(
            f"Unknown theme {config.THEME!r} (KINDLE_GAZETTE_THEME). "
            f"Available themes: {', '.join(available_themes())}"
        )
    return directory


@lru_cache(maxsize=None)
def _theme_env(theme_path: str) -> Environment:
    # Theme dir first, shared templates second: a theme may override any
    # template file, and unoverridden ones fall back to templates/.
    return Environment(loader=FileSystemLoader([theme_path, str(_TEMPLATES_DIR)]), autoescape=True)


def _env() -> Environment:
    return _theme_env(str(theme_dir()))


# Cards that can't fit above the footer are dropped, matching the old
# renderer's behavior of stopping at the bottom of the grid (2 columns of
# minimum-height cards in the content band).
_MAX_GRID_CARDS = 14


@dataclass
class RenderResult:
    """Everything server.py needs to persist a rendered view. `pages` holds
    (grayscale PNG bytes, taps) per screen — one entry except for paginated
    editions."""
    pages: list[tuple[bytes, list[dict]]]
    back: str | None
    refresh_sec: int


def _base_context(title: str, back: str | None, is_home: bool = False) -> dict:
    return {
        "title": title,
        "edition_stamp": time.strftime("%b %d · %H:%M"),
        "back": back,
        "is_home": is_home,
        "screen_w": config.SCREEN_WIDTH,
        "screen_h": config.SCREEN_HEIGHT,
        "theme_css": (theme_dir() / "theme.css").read_text(),
    }


def _render_single(template: str, context: dict, back: str | None, refresh_sec: int) -> RenderResult:
    html = _env().get_template(template).render(**context)
    png, taps = browser.render_page(html)
    return RenderResult(pages=[(png, taps)], back=back, refresh_sec=refresh_sec)


# ── home: the server-built grid of agent cards (not agent-pushable) ──

def render_home(data: dict) -> RenderResult:
    """The home view: a grid of navigable cards, one per registered agent.
    Built by server.build_home_view() from stored home cards — no agent
    payload reaches this renderer."""
    is_home = data.get("_home", False)
    back = None if is_home else data.get("back", "home")
    cards = [
        {
            "title": str(card.get("title", "")),
            "summary": [str(line) for line in card.get("summary", [])[:4]],
            "nav_target": card.get("nav_target", ""),
        }
        for card in data.get("cards", [])[:_MAX_GRID_CARDS]
    ]
    context = _base_context(data.get("title", "Gazette"), back, is_home)
    context["cards"] = cards
    return _render_single("home.html", context, back, data.get("refresh_sec", 0))


# ── figure geometry: sparkline ──

def _sparkline_geometry(spark: dict) -> dict | None:
    """Polyline/dot/baseline coordinates for the inline SVG — same min/max/pad
    scaling the Pillow renderer used, computed here so templates stay dumb."""
    values = [float(v) for v in spark.get("values", [])]
    if len(values) < 2:
        return None
    width = config.SCREEN_WIDTH - 80
    height = 300
    baseline = spark.get("baseline")
    all_vals = values + ([float(baseline)] if baseline is not None else [])
    lo, hi = min(all_vals), max(all_vals)
    pad = (hi - lo) * 0.1 or 1.0
    lo, hi = lo - pad, hi + pad

    def sx(i: int) -> float:
        return round(width * i / (len(values) - 1), 1)

    def sy(v: float) -> float:
        return round(height - height * (v - lo) / (hi - lo), 1)

    dots = [(sx(i), sy(v)) for i, v in enumerate(values)]
    return {
        "width": width,
        "height": height,
        "points": " ".join(f"{px},{py}" for px, py in dots),
        "dots": dots,
        "baseline_y": sy(float(baseline)) if baseline is not None else None,
    }


# ── figure geometry: progress bars and stacked bars ──

def _bar_context(bar: dict) -> dict:
    """One progress bar of a `bars` figure. Optional `target` becomes a tick on
    the track at target/max — drawn whether the fill has passed it or not."""
    value = float(bar.get("value", 0))
    vmax = float(bar.get("max", 1)) or 1.0
    target = bar.get("target")
    return {
        "label": str(bar.get("label", "")),
        "percent": round(max(0.0, min(1.0, value / vmax)) * 100, 1),
        "readout": f"{value:g}/{vmax:g}",
        "target_percent": (
            round(max(0.0, min(1.0, float(target) / vmax)) * 100, 1)
            if target is not None else None
        ),
    }


def _stacked_segments(stacked: dict) -> list[dict]:
    """Segment widths for a `stacked_bar` figure. `max` defaults to the segment
    total, so segments fill the track unless the caller pins a larger
    denominator."""
    raw = stacked.get("segments") or []
    smax = float(stacked.get("max") or sum(s.get("value", 0) for s in raw) or 1.0)
    segments = []
    for i, seg in enumerate(raw):
        value = float(seg.get("value", 0))
        segments.append({
            "label": str(seg.get("label", "")),
            "percent": round(max(0.0, min(1.0, value / smax)) * 100, 1),
            "readout": f"{value:g}",
            "palette": i % 4 + 1,
        })
    return segments


# ── edition: long-form text + figures, paginated into viewport-width columns ──

_TABLE_ALIGNS = ("left", "right", "center")
_STAT_DIRECTIONS = {"up": "▲", "down": "▼", "flat": ""}
_CHECK_STATES = ("done", "open", "skipped")
_CALLOUT_STYLES = ("alert", "note", "quote")
# Stats share one row of screen width; more than four stop being readable.
_MAX_STATS = 4
# QR figures are generated here, not by the agent: the agent sends text, the
# renderer sends back pixels. ~340px on the 1072px-wide page, at an exact
# integer module scale — a fractionally scaled QR turns into gray module edges
# after dithering and stops scanning.
_QR_TARGET_PX = 340


def _qr_data_uri(payload: str) -> tuple[str, int]:
    """Encode `payload` as a pure black-on-white PNG QR (error correction M,
    4-module quiet zone) and return (data-URI, side length in px). The box size
    is a whole number of pixels per module so the <img> is shown at natural
    size and stays pixel-crisp."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=4)
    qr.add_data(payload)
    qr.make(fit=True)  # picks the smallest version that holds the payload
    modules = qr.modules_count + 2 * qr.border
    qr.box_size = max(1, round(_QR_TARGET_PX / modules))
    image = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white").convert("L")
    buf = BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), image.width
# Series are told apart by stroke pattern, never by gray value: two mid-gray
# lines dither into similar dot texture on the panel and stop reading apart.
_LINE_DASHES = (None, "12 8", "3 7")   # solid / dashed / dotted
_LINE_MAX_SERIES = 3
_LINE_X_LABELS = 7                     # most x labels that stay legible at 22px

_HEAT_GAP = 3
_HEAT_MAX_H = 420                      # figure must leave room for text on the page
_HEAT_MAX_CELL = 96
_HEAT_MIN_CELL = 14
_HEAT_GUTTER = 150                     # left gutter for right-aligned row labels
_HEAT_HEAD_H = 30                      # column-label band above the grid


def _num_label(value: float, span: float) -> str:
    """Axis tick text: enough decimals to tell neighbouring ticks apart, never
    more — a long label overflows the y gutter and gets clipped."""
    digits = 0 if span <= 0 else max(0, min(4, 2 - math.floor(math.log10(span))))
    text = f"{value:.{digits}f}"
    return text.lstrip("-") if float(text) == 0 else text


def _thinned(count: int, keep: int) -> list[int]:
    """Indices to label — at most `keep`, evenly spaced, first and last always
    included (an axis whose ends are unlabeled reads as cropped)."""
    if count <= keep:
        return list(range(count))
    step = (count - 1) / (keep - 1)
    return sorted({round(k * step) for k in range(keep)} | {0, count - 1})


def _line_chart_geometry(figure: dict) -> dict | None:
    """Polyline/gridline/label coordinates for a multi-series line chart, in the
    same geometry-in-Python style as _sparkline_geometry: same min/max/10%-pad
    scaling (overridable with y_min/y_max), plus a left gutter for y ticks and a
    bottom gutter for x labels."""
    series_in = []
    for entry in figure.get("series", [])[:_LINE_MAX_SERIES]:
        if not isinstance(entry, dict):
            continue
        values = [float(v) for v in entry.get("values", [])]
        if len(values) >= 2:
            series_in.append((str(entry.get("label", "")), values))
    if not series_in:
        return None

    width, height = 992, 360
    gutter_l, gutter_b = 70, 40
    plot_w, plot_h = width - gutter_l, height - gutter_b

    baseline = figure.get("baseline")
    all_vals = [v for _label, values in series_in for v in values]
    if baseline is not None:
        all_vals.append(float(baseline))
    lo, hi = min(all_vals), max(all_vals)
    pad = (hi - lo) * 0.1 or 1.0
    lo, hi = lo - pad, hi + pad
    if figure.get("y_min") is not None:
        lo = float(figure["y_min"])
    if figure.get("y_max") is not None:
        hi = float(figure["y_max"])
    if hi <= lo:
        hi = lo + 1.0
    # Series may differ in length (validation asks for equal); scale to longest.
    count = max(len(values) for _label, values in series_in)

    def sx(i: int) -> float:
        return round(gutter_l + plot_w * i / (count - 1), 1)

    def sy(v: float) -> float:
        return round(plot_h - plot_h * (v - lo) / (hi - lo), 1)

    ticks = []
    for k in range(5):
        y = round(plot_h * k / 4, 1)
        ticks.append({
            "y": y,
            # Keep the end labels inside the viewBox — mid-anchored text at y=0
            # would be half-clipped by the top edge.
            "text_y": round(min(max(y, 16.0), plot_h - 2), 1),
            "label": _num_label(hi - (hi - lo) * k / 4, hi - lo),
        })

    labels = [str(label) for label in (figure.get("x_labels") or [])][:count]
    x_labels = [
        {
            "x": sx(i),
            "text": labels[i],
            "anchor": "start" if i == 0 else ("end" if i == count - 1 else "middle"),
        }
        for i in _thinned(len(labels), _LINE_X_LABELS)
    ]

    return {
        "width": width,
        "height": height,
        "plot_x": gutter_l,
        "plot_h": plot_h,
        "frame_x": gutter_l + 1,
        "frame_w": plot_w - 2,
        "frame_h": plot_h - 2,
        "tick_x": gutter_l - 12,
        "label_y": height - 12,
        "ticks": ticks,
        "x_labels": x_labels,
        "baseline_y": sy(float(baseline)) if baseline is not None else None,
        "series": [
            {
                "label": label,
                "dash": _LINE_DASHES[i],
                "points": " ".join(f"{sx(j)},{sy(v)}" for j, v in enumerate(values)),
            }
            for i, (label, values) in enumerate(series_in)
        ],
    }


def _heatmap_geometry(figure: dict) -> dict | None:
    """Cell sizes and fills for a heatmap grid. Fills are computed here as
    PANEL-EXACT grays — value/scale_max quantized onto the 16 levels the glass
    has (multiples of 0x11, inverted so 0 is paper and scale_max is ink) — so
    this figure never leans on dithering. Cells are square and capped so the
    figure still leaves room for text on the page."""
    rows_in = [row for row in figure.get("rows", []) if isinstance(row, list) and row]
    if not rows_in:
        return None
    cols = max(len(row) for row in rows_in)
    values = [float(v) for row in rows_in for v in row if v is not None]
    scale_max = float(figure.get("scale_max") or 0) or (max(values, default=0.0) or 1.0)

    row_labels = [str(label) for label in (figure.get("row_labels") or [])]
    col_labels = [str(label) for label in (figure.get("col_labels") or [])][:cols]
    gutter = _HEAT_GUTTER if row_labels else 0
    head_h = _HEAT_HEAD_H if col_labels else 0
    cell = min(
        _HEAT_MAX_CELL,
        (992 - gutter - _HEAT_GAP * (cols - 1)) // cols,
        (_HEAT_MAX_H - head_h - _HEAT_GAP * (len(rows_in) - 1)) // len(rows_in),
    )
    cell = max(_HEAT_MIN_CELL, int(cell))

    rows = []
    for i, row in enumerate(rows_in):
        cells = []
        for j in range(cols):
            value = row[j] if j < len(row) else None
            if value is None:
                cells.append({"color": None, "empty": True})
                continue
            level = round(max(0.0, min(1.0, float(value) / scale_max)) * 15)
            shade = (15 - level) * 17
            cells.append({"color": f"#{shade:02x}{shade:02x}{shade:02x}", "empty": False})
        rows.append({
            "label": row_labels[i] if i < len(row_labels) else "",
            "cells": cells,
        })
    return {"cell": cell, "gutter": gutter, "cols": cols, "rows": rows, "col_labels": col_labels}


def _figure_context(figure: dict) -> dict | None:
    """Normalize a section's `figure` payload into template context — one
    branch per figure kind, all geometry computed here so the templates stay
    dumb. Returns None for a figure that has nothing drawable (no values, no
    rows, no links): an empty figure is dropped rather than rendered as an
    empty ruled band."""
    kind = figure.get("kind")
    caption = figure.get("caption")
    if kind == "sparkline":
        geometry = _sparkline_geometry(figure)
        if geometry is None:
            return None
        return {"kind": "sparkline", "chart": geometry, "caption": caption}
    if kind == "line_chart":
        geometry = _line_chart_geometry(figure)
        if geometry is None:
            return None
        return {"kind": "line_chart", "chart": geometry, "caption": caption}
    if kind == "heatmap":
        grid = _heatmap_geometry(figure)
        if grid is None:
            return None
        return {"kind": "heatmap", "grid": grid, "caption": caption}
    if kind == "bars":
        bars = [_bar_context(bar) for bar in figure.get("bars", [])]
        if not bars:
            return None
        return {"kind": "bars", "bars": bars, "caption": caption}
    if kind == "stacked_bar":
        segments = _stacked_segments(figure)
        if not segments:
            return None
        return {"kind": "stacked_bar", "segments": segments, "caption": caption}
    if kind == "image":
        data = str(figure.get("data", ""))
        if not data:
            return None
        if data.startswith("data:"):
            src = data
        else:
            fmt = str(figure.get("format", "png")).lower()
            src = f"data:image/{'jpeg' if fmt in ('jpg', 'jpeg') else 'png'};base64,{data}"
        return {"kind": "image", "src": src, "caption": caption}
    if kind == "table":
        columns = [str(col) for col in figure.get("columns", [])]
        if not columns:
            return None
        aligns = []
        for value in figure.get("align") or []:
            align = str(value).lower()
            aligns.append(align if align in _TABLE_ALIGNS else "left")
        aligns = (aligns + ["left"] * len(columns))[:len(columns)]
        rows = []
        for row in figure.get("rows", []):
            if not isinstance(row, (list, tuple)):
                continue
            cells = [str(cell) for cell in row][:len(columns)]
            # Ragged rows are padded, not dropped: a partial row still informs.
            cells += [""] * (len(columns) - len(cells))
            rows.append(list(zip(cells, aligns)))
        if not rows:
            return None
        return {
            "kind": "table",
            "columns": list(zip(columns, aligns)),
            "rows": rows,
            "caption": caption,
        }
    if kind == "stat_row":
        stats = []
        for stat in figure.get("stats", [])[:_MAX_STATS]:
            if not isinstance(stat, dict):
                continue
            direction = str(stat.get("direction", "") or "").lower()
            stats.append({
                "value": str(stat.get("value", "")),
                "unit": str(stat.get("unit", "") or "") or None,
                "label": str(stat.get("label", "")),
                "delta": str(stat.get("delta", "") or "") or None,
                "arrow": _STAT_DIRECTIONS.get(direction, ""),
            })
        if not stats:
            return None
        return {"kind": "stat_row", "stats": stats, "caption": caption}
    if kind == "checklist":
        items = []
        for item in figure.get("items", []):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", ""))
            if not text:
                continue
            state = str(item.get("state", "open") or "open").lower()
            items.append({
                "text": text,
                "state": state if state in _CHECK_STATES else "open",
            })
        if not items:
            return None
        return {"kind": "checklist", "items": items, "caption": caption}
    if kind == "callout":
        text = str(figure.get("text", "") or "")
        if not text:
            return None
        style = str(figure.get("style", "note") or "note").lower()
        return {
            "kind": "callout",
            "text": text,
            "style": style if style in _CALLOUT_STYLES else "note",
            "caption": caption,
        }
    if kind == "timeline":
        events = []
        for event in figure.get("events", []):
            text = str(event.get("text", "")).strip()
            if not text:
                continue  # a timeline entry with no text has nothing to draw
            label = event.get("time")
            events.append({
                "text": text,
                "time": str(label) if label else "",
                "emphasis": bool(event.get("emphasis", False)),
            })
        if not events:
            return None
        return {"kind": "timeline", "events": events, "caption": caption}
    if kind == "qr":
        payload = str(figure.get("data", ""))
        if not payload:
            return None
        src, size = _qr_data_uri(payload)
        return {"kind": "qr", "src": src, "size": size, "caption": caption}
    if kind == "link_list":
        links = []
        for link in figure.get("links", []):
            if not isinstance(link, dict):
                continue
            text = str(link.get("text", "") or "").strip()
            target = str(link.get("nav_target", "") or "").strip()
            # A row with no label or no destination would render as a tappable
            # rectangle that goes nowhere — drop it rather than ship a dead tap.
            if not text or not target:
                continue
            note = str(link.get("note", "") or "").strip()
            links.append({"text": text, "nav_target": target, "note": note or None})
        if not links:
            return None
        return {"kind": "link_list", "links": links, "caption": caption}
    return None


def _edition_blocks(data: dict) -> list[dict]:
    """Normalize body/sections into a flat list of heading/paragraph/figure
    blocks. `body` is plain text: blank-line-separated paragraphs, "## " lines
    become section headings. `sections` is the structured equivalent — each
    section may carry `heading`, `text`, and/or a `figure` (rendered after
    that section's paragraphs)."""
    blocks: list[dict] = []
    if data.get("body") is not None:
        for chunk in str(data["body"]).split("\n\n"):
            lines = [line.strip() for line in chunk.split("\n") if line.strip()]
            para_lines: list[str] = []
            for line in lines:
                if line.startswith("## "):
                    if para_lines:
                        blocks.append({"kind": "para", "text": " ".join(para_lines)})
                        para_lines = []
                    blocks.append({"kind": "heading", "text": line[3:].strip()})
                else:
                    para_lines.append(line)
            if para_lines:
                blocks.append({"kind": "para", "text": " ".join(para_lines)})
    else:
        for section in data.get("sections", []):
            heading = section.get("heading")
            if heading:
                blocks.append({"kind": "heading", "text": str(heading)})
            text = str(section.get("text", "") or "")
            for para in text.split("\n\n"):
                para = para.strip()
                if para:
                    blocks.append({"kind": "para", "text": para})
            figure = section.get("figure")
            if isinstance(figure, dict):
                context = _figure_context(figure)
                if context is not None:
                    blocks.append({"kind": "figure", "figure": context})
    return blocks


def render_edition(data: dict[str, Any], path: str) -> RenderResult:
    """Render one edition. `path` is the edition's own view path — the template
    needs it to build the /p2, /p3... targets of its PREV/NEXT buttons."""
    back = data.get("back", "home")
    title = data.get("title", "Edition")
    context = _base_context(title, back)
    context.update({
        "article_title": title,
        "byline": data.get("byline"),
        "blocks": _edition_blocks(data),
        "base_path": path,
    })
    html = _env().get_template("article.html").render(**context)
    pages, _count = browser.render_paged(html)
    return RenderResult(pages=pages, back=back, refresh_sec=data.get("refresh_sec", 0))
