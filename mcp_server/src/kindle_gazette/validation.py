"""Validation for the edition payloads agents publish.

There is exactly one agent-facing schema — the edition — so there is no type
discriminator to get wrong; the only choice left is which figure kind to embed.
Errors are actionable: they name the field, the element index, and what was
expected, because the caller is an agent that has to self-correct from the
message alone. Unknown top-level fields are deliberately NOT errors (forward
compatibility: an older server must not reject data meant for a newer one);
they come back as warnings instead.
"""
from __future__ import annotations

import re
from typing import Any

# Top-level fields an edition understands; anything else is warned about.
_KNOWN_FIELDS = {"title", "byline", "body", "sections", "back", "refresh_sec"}

# The canonical edition, used as the shape example for top-level errors.
_EDITION_EXAMPLE = (
    '{"title": "Weekly Digest", "byline": "research-agent", '
    '"sections": [{"heading": "Intro", "text": "First paragraph."}, '
    '{"figure": {"kind": "sparkline", "values": [88, 95, 90], "baseline": 95, "caption": "HRV, 7-day"}}]}'
)

# One minimal example per figure kind — an error inside a figure gets that
# figure's shape back, not the whole edition's.
_FIGURE_EXAMPLES = {
    "sparkline": '{"kind": "sparkline", "values": [88, 95, 90], "baseline": 95}',
    "line_chart": '{"kind": "line_chart", "series": [{"label": "HRV", "values": [88, 95, 90]}], "x_labels": ["Mon", "Tue", "Wed"]}',
    "bars": '{"kind": "bars", "bars": [{"label": "Protein", "value": 120, "max": 160}]}',
    "stacked_bar": '{"kind": "stacked_bar", "segments": [{"label": "Carbs", "value": 200}, {"label": "Fat", "value": 70}]}',
    "heatmap": '{"kind": "heatmap", "rows": [[0, 2, 5], [1, 4, 0]], "row_labels": ["Week 34", "Week 35"], "col_labels": ["Mon", "Tue", "Wed"]}',
    "image": '{"kind": "image", "data": "iVBORw0KGgo=", "format": "png"}',
    "table": '{"kind": "table", "columns": ["Job", "State"], "rows": [["backup", "OK"]], "align": ["left", "right"]}',
    "stat_row": '{"kind": "stat_row", "stats": [{"value": "92", "unit": "ms", "label": "p50", "delta": "+4%", "direction": "up"}]}',
    "checklist": '{"kind": "checklist", "items": [{"text": "Ship the report", "state": "done"}]}',
    "callout": '{"kind": "callout", "text": "Backups have been stale since Tuesday.", "style": "alert"}',
    "timeline": '{"kind": "timeline", "events": [{"time": "09:00", "text": "Standup", "emphasis": true}]}',
    "qr": '{"kind": "qr", "data": "https://example.com/full-report"}',
    "link_list": '{"kind": "link_list", "links": [{"text": "Fleet status", "nav_target": "ops/fleet", "note": "2 min ago"}]}',
}

_FIGURE_KINDS = ("sparkline", "line_chart", "bars", "stacked_bar", "heatmap", "image",
                 "table", "stat_row", "checklist", "callout", "timeline", "qr", "link_list")
_SECTION_INDEX = re.compile(r"sections\[(\d+)\]")
_TABLE_ALIGNS = ("left", "right", "center")
_CHECK_STATES = ("done", "open", "skipped")
_CALLOUT_STYLES = ("alert", "note", "quote")
_STAT_DIRECTIONS = ("up", "down", "flat")
_MAX_STATS = 4

# A line chart differentiates series by dash pattern (solid/dashed/dotted) —
# grayscale e-ink can't carry a fourth line legibly.
_MAX_SERIES = 3

# A QR at figure size stops being reliably scannable long before
# the format's own capacity runs out, so cap the payload well under it.
_QR_MAX_CHARS = 1000


def _check_labels(errors: list[str], figure: dict, field: str, where: str, expected: int | None) -> None:
    """An optional list of axis labels: strings, and — where the axis has a
    fixed length — exactly as many as there are rows/columns to name."""
    labels = figure.get(field)
    if labels is None:
        return
    if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
        errors.append(f"{where}: '{field}' must be a list of strings")
    elif expected is not None and len(labels) != expected:
        errors.append(f"{where}: '{field}' has {len(labels)} entries but needs {expected}")


def _check_figure(errors: list[str], figure: Any, where: str) -> None:
    """A section's embedded figure: {"kind": one of _FIGURE_KINDS, ...}."""
    if not isinstance(figure, dict):
        errors.append(f"{where}: 'figure' must be an object with a 'kind' field, got {type(figure).__name__}")
        return
    kind = figure.get("kind")
    if kind not in _FIGURE_KINDS:
        errors.append(f"{where}: figure 'kind' must be one of {list(_FIGURE_KINDS)}, got {kind!r}")
        return
    if kind == "sparkline":
        values = figure.get("values")
        if not isinstance(values, list) or not all(_is_num(v) for v in values) or len(values) < 2:
            errors.append(f"{where}: sparkline figure needs 'values', a list of 2+ numbers")
        if "baseline" in figure and figure["baseline"] is not None and not _is_num(figure["baseline"]):
            errors.append(f"{where}: figure 'baseline' must be a number")
    elif kind == "line_chart":
        series = figure.get("series")
        if not isinstance(series, list) or not series:
            errors.append(f"{where}: line_chart figure needs 'series', a list of 1-3 "
                          '{"label": "...", "values": [n, n, ...]} objects')
        elif len(series) > _MAX_SERIES:
            errors.append(f"{where}: line_chart 'series' takes at most {_MAX_SERIES} entries, "
                          f"got {len(series)} — series are told apart by dash pattern "
                          "(solid/dashed/dotted), so a fourth line would be unreadable; "
                          "split it into a second figure")
        else:
            lengths = set()
            for i, entry in enumerate(series):
                if not isinstance(entry, dict):
                    errors.append(f"{where}: series[{i}] must be an object")
                    continue
                _check_str(errors, entry, "label", f"{where}: series[{i}]", required=True)
                values = entry.get("values")
                if (not isinstance(values, list) or len(values) < 2
                        or not all(_is_num(v) for v in values)):
                    errors.append(f"{where}: series[{i}]: 'values' must be a list of 2+ numbers")
                else:
                    lengths.add(len(values))
            if len(lengths) > 1:
                errors.append(f"{where}: every line_chart series needs the same number of "
                              f"'values' (got lengths {sorted(lengths)}) — they share one x axis")
        _check_labels(errors, figure, "x_labels", where, None)
        for field in ("baseline", "y_min", "y_max"):
            if figure.get(field) is not None and not _is_num(figure[field]):
                errors.append(f"{where}: line_chart '{field}' must be a number")
    elif kind == "bars":
        bars = figure.get("bars")
        if not isinstance(bars, list) or not bars:
            errors.append(f"{where}: bars figure needs 'bars', a non-empty list of "
                          '{"label": "...", "value": n, "max": n, "target"?: n}')
        else:
            for i, bar in enumerate(bars):
                if not isinstance(bar, dict):
                    errors.append(f"{where}: bars[{i}] must be an object")
                    continue
                _check_str(errors, bar, "label", f"{where}: bars[{i}]", required=True)
                if not _is_num(bar.get("value")):
                    errors.append(f"{where}: bars[{i}]: 'value' must be a number")
                if not _is_num(bar.get("max")):
                    errors.append(f"{where}: bars[{i}]: 'max' must be a number")
                if bar.get("target") is not None and not _is_num(bar["target"]):
                    errors.append(f"{where}: bars[{i}]: 'target' must be a number "
                                  "(a tick on the track, in the same units as 'value')")
    elif kind == "stacked_bar":
        segments = figure.get("segments")
        if not isinstance(segments, list) or not segments:
            errors.append(f"{where}: stacked_bar figure needs 'segments', a non-empty list of "
                          '{"label": "...", "value": n}')
        else:
            for i, seg in enumerate(segments):
                if not isinstance(seg, dict):
                    errors.append(f"{where}: segments[{i}] must be an object")
                    continue
                _check_str(errors, seg, "label", f"{where}: segments[{i}]")
                if not _is_num(seg.get("value")):
                    errors.append(f"{where}: segments[{i}]: 'value' must be a number")
        if figure.get("max") is not None and not _is_num(figure["max"]):
            errors.append(f"{where}: stacked_bar 'max' must be a number "
                          "(defaults to the segment total)")
    elif kind == "heatmap":
        rows = figure.get("rows")
        width = None
        if not isinstance(rows, list) or not rows:
            errors.append(f"{where}: heatmap figure needs 'rows', a non-empty list of "
                          "equal-length lists of numbers (null for an empty cell)")
        else:
            for i, row in enumerate(rows):
                if not isinstance(row, list) or not row:
                    errors.append(f"{where}: rows[{i}] must be a non-empty list of numbers or nulls")
                    continue
                if width is None:
                    width = len(row)
                elif len(row) != width:
                    errors.append(f"{where}: rows[{i}] has {len(row)} cells but rows[0] has "
                                  f"{width} — every heatmap row must be the same length")
                for j, cell in enumerate(row):
                    if cell is not None and not _is_num(cell):
                        errors.append(f"{where}: rows[{i}][{j}] must be a number or null, "
                                      f"got {type(cell).__name__}")
        _check_labels(errors, figure, "row_labels", where,
                      len(rows) if isinstance(rows, list) and rows else None)
        _check_labels(errors, figure, "col_labels", where, width)
        if figure.get("scale_max") is not None and not _is_num(figure["scale_max"]):
            errors.append(f"{where}: heatmap 'scale_max' must be a number "
                          "(defaults to the largest cell value)")
    elif kind == "image":
        data = figure.get("data")
        if not isinstance(data, str) or not data:
            errors.append(f"{where}: image figure needs 'data', a base64-encoded PNG/JPEG "
                          "(or a full data: URI)")
        fmt = figure.get("format")
        if fmt is not None and str(fmt).lower() not in ("png", "jpeg", "jpg"):
            errors.append(f"{where}: image 'format' must be 'png' or 'jpeg', got {fmt!r}")
    elif kind == "table":
        columns = figure.get("columns")
        if not isinstance(columns, list) or not columns:
            errors.append(f"{where}: table figure needs 'columns', a non-empty list of header strings")
        elif not all(isinstance(col, str) for col in columns):
            errors.append(f"{where}: table 'columns' must all be strings")
        rows = figure.get("rows")
        if not isinstance(rows, list) or not rows:
            errors.append(f"{where}: table figure needs 'rows', a non-empty list of cell lists")
        else:
            for i, row in enumerate(rows):
                if not isinstance(row, list):
                    errors.append(f"{where}: rows[{i}] must be a list of cells, got {type(row).__name__}")
        align = figure.get("align")
        if align is not None:
            if not isinstance(align, list):
                errors.append(f"{where}: table 'align' must be a list of {list(_TABLE_ALIGNS)}, "
                              f"got {type(align).__name__}")
            else:
                for i, value in enumerate(align):
                    if value not in _TABLE_ALIGNS:
                        errors.append(f"{where}: align[{i}] must be one of {list(_TABLE_ALIGNS)}, got {value!r}")
    elif kind == "stat_row":
        stats = figure.get("stats")
        if not isinstance(stats, list) or not stats:
            errors.append(f"{where}: stat_row figure needs 'stats', a list of 1-{_MAX_STATS} "
                          '{"value": "...", "label": "..."} objects')
        elif len(stats) > _MAX_STATS:
            errors.append(f"{where}: stat_row 'stats' holds at most {_MAX_STATS} stats, got {len(stats)}")
        else:
            for i, stat in enumerate(stats):
                if not isinstance(stat, dict):
                    errors.append(f"{where}: stats[{i}] must be an object")
                    continue
                value = stat.get("value")
                if value is None or not isinstance(value, (str, int, float)) or isinstance(value, bool):
                    errors.append(f"{where}: stats[{i}]: 'value' must be a string or number")
                _check_str(errors, stat, "label", f"{where}: stats[{i}]", required=True)
                _check_str(errors, stat, "unit", f"{where}: stats[{i}]")
                _check_str(errors, stat, "delta", f"{where}: stats[{i}]")
                direction = stat.get("direction")
                if direction is not None and direction not in _STAT_DIRECTIONS:
                    errors.append(f"{where}: stats[{i}]: 'direction' must be one of "
                                  f"{list(_STAT_DIRECTIONS)}, got {direction!r}")
    elif kind == "checklist":
        items = figure.get("items")
        if not isinstance(items, list) or not items:
            errors.append(f"{where}: checklist figure needs 'items', a non-empty list of "
                          '{"text": "...", "state": "done"|"open"|"skipped"}')
        else:
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    errors.append(f"{where}: items[{i}] must be an object")
                    continue
                _check_str(errors, item, "text", f"{where}: items[{i}]", required=True)
                state = item.get("state")
                if state is not None and state not in _CHECK_STATES:
                    errors.append(f"{where}: items[{i}]: 'state' must be one of "
                                  f"{list(_CHECK_STATES)}, got {state!r}")
    elif kind == "callout":
        text = figure.get("text")
        if not isinstance(text, str) or not text:
            errors.append(f"{where}: callout figure needs 'text', a non-empty string")
        style = figure.get("style")
        if style is not None and style not in _CALLOUT_STYLES:
            errors.append(f"{where}: callout 'style' must be one of {list(_CALLOUT_STYLES)}, got {style!r}")
    elif kind == "timeline":
        events = figure.get("events")
        if not isinstance(events, list) or not events:
            errors.append(f"{where}: timeline figure needs 'events', a non-empty list of "
                          '{"time": "09:00", "text": "...", "emphasis": false}')
        else:
            for i, event in enumerate(events):
                if not isinstance(event, dict):
                    errors.append(f"{where}: events[{i}] must be an object, got {type(event).__name__}")
                    continue
                _check_str(errors, event, "text", f"{where}: events[{i}]", required=True)
                # 'time' is a free-form label ("09:00", "Tue", "Q3"), never parsed.
                _check_str(errors, event, "time", f"{where}: events[{i}]")
                if event.get("emphasis") is not None and not isinstance(event["emphasis"], bool):
                    errors.append(f"{where}: events[{i}]: 'emphasis' must be true or false, "
                                  f"got {type(event['emphasis']).__name__}")
    elif kind == "qr":
        data = figure.get("data")
        if not isinstance(data, str) or not data:
            errors.append(f"{where}: qr figure needs 'data', a non-empty string "
                          "(a URL, or any text to encode)")
        elif len(data) > _QR_MAX_CHARS:
            errors.append(f"{where}: qr 'data' is {len(data)} characters; the maximum that "
                          f"stays scannable at figure size is {_QR_MAX_CHARS}")
    elif kind == "link_list":
        links = figure.get("links")
        if not isinstance(links, list) or not links:
            errors.append(f"{where}: link_list figure needs 'links', a non-empty list of "
                          '{"text": "...", "nav_target": "<view path>", "note"?: "..."}')
        else:
            for i, link in enumerate(links):
                if not isinstance(link, dict):
                    errors.append(f"{where}: links[{i}] must be an object, got {type(link).__name__}")
                    continue
                for field in ("text", "nav_target"):
                    value = link.get(field)
                    if value is None:
                        errors.append(f"{where}: links[{i}]: missing required field '{field}' (string)")
                    elif not isinstance(value, str):
                        errors.append(f"{where}: links[{i}]: '{field}' must be a string, "
                                      f"got {type(value).__name__}")
                    elif not value.strip():
                        # An empty label or target renders a tappable dead row.
                        errors.append(f"{where}: links[{i}]: '{field}' must be a non-empty string")
                _check_str(errors, link, "note", f"{where}: links[{i}]")
    _check_str(errors, figure, "caption", where)


def shape_example(figure_kind: str | None = None) -> str:
    """A minimal valid example: of `figure_kind` when one is named, of the
    canonical edition otherwise. Appended to failure messages so an agent can
    self-correct against a concrete shape."""
    if figure_kind is None:
        return _EDITION_EXAMPLE
    return _FIGURE_EXAMPLES.get(figure_kind, _EDITION_EXAMPLE)


def failure_example(data: dict, errors: list[str]) -> str:
    """The most useful shape example for this failure. When every error points
    at sections holding one and the same figure kind, that figure's shape is
    what the agent needs; anything else gets the edition."""
    sections = data.get("sections")
    if not errors or not isinstance(sections, list):
        return _EDITION_EXAMPLE
    kinds = set()
    for message in errors:
        match = _SECTION_INDEX.search(message)
        if match is None:
            return _EDITION_EXAMPLE
        index = int(match.group(1))
        section = sections[index] if index < len(sections) else None
        figure = section.get("figure") if isinstance(section, dict) else None
        kind = figure.get("kind") if isinstance(figure, dict) else None
        # `kind` is whatever the agent sent — check it is a string before using
        # it as a dict key, or an unhashable one would raise here.
        if not isinstance(kind, str) or kind not in _FIGURE_EXAMPLES:
            return _EDITION_EXAMPLE
        kinds.add(kind)
    return _FIGURE_EXAMPLES[kinds.pop()] if len(kinds) == 1 else _EDITION_EXAMPLE


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_str(errors: list[str], obj: dict, field: str, where: str, required: bool = False) -> None:
    value = obj.get(field)
    if value is None:
        if required:
            errors.append(f"{where}: missing required field '{field}' (string)")
    elif not isinstance(value, str):
        errors.append(f"{where}: '{field}' must be a string, got {type(value).__name__}")


def _check_list(errors: list[str], data: dict, field: str, where: str = "") -> list:
    value = data.get(field)
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{where or field}: '{field}' must be a list, got {type(value).__name__}")
        return []
    return value


def _check_dicts(errors: list[str], items: list, what: str) -> list[dict]:
    good = []
    for i, item in enumerate(items):
        if isinstance(item, dict):
            good.append(item)
        else:
            errors.append(f"{what}[{i}] must be an object, got {type(item).__name__}")
    return good


def validate(data: dict) -> list[str]:
    """Validate an edition payload. Returns a list of problems; empty means the
    edition is renderable."""
    errors: list[str] = []
    _check_str(errors, data, "title", "edition", required=True)
    if "back" in data and data["back"] is not None and not isinstance(data["back"], str):
        errors.append(f"'back' must be a string view path, got {type(data['back']).__name__}")
    if "refresh_sec" in data and not _is_num(data["refresh_sec"]):
        errors.append(f"'refresh_sec' must be a number, got {type(data['refresh_sec']).__name__}")
    _check_str(errors, data, "byline", "edition")

    has_body = data.get("body") is not None
    has_sections = data.get("sections") is not None
    if has_body == has_sections:
        errors.append("exactly one of 'body' (plain text) or 'sections' "
                      "(list of {heading?, text?, figure?}) is required")
    if has_body and not isinstance(data["body"], str):
        errors.append(f"'body' must be a string, got {type(data['body']).__name__}")
    if has_sections:
        sections = _check_dicts(errors, _check_list(errors, data, "sections"), "sections")
        for i, section in enumerate(sections):
            _check_str(errors, section, "text", f"sections[{i}]")
            _check_str(errors, section, "heading", f"sections[{i}]")
            if section.get("text") is None and section.get("figure") is None:
                errors.append(f"sections[{i}]: needs 'text' (string) and/or 'figure' (object)")
            if "figure" in section and section["figure"] is not None:
                _check_figure(errors, section["figure"], f"sections[{i}]")

    return errors


def collect_warnings(data: dict) -> list[str]:
    """Unknown top-level fields — accepted (forward compat) but flagged so a
    misspelled field name doesn't fail silently."""
    return [f"unknown field {field!r} (ignored)" for field in data if field not in _KNOWN_FIELDS]
