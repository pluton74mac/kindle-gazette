"""The text-shaped article figures: table, stat_row, checklist, callout.

Validation coverage plus one browser-tier render that proves all four reach the
panel as a palette-exact grayscale PNG.
"""
import io

from PIL import Image

import pytest

from kindle_gazette import config, server, store, validation

TABLE = {
    "kind": "table",
    "columns": ["Plan", "Price", "Notes"],
    "rows": [["Basic", "$5", "ok"], ["Pro", "$12", "best"]],
    "align": ["left", "right", "left"],
    "caption": "Pricing tiers",
}
STAT_ROW = {
    "kind": "stat_row",
    "stats": [
        {"value": "92", "unit": "ms", "label": "HRV", "delta": "+4%", "direction": "up"},
        {"value": 61, "label": "Resting HR", "delta": "-2 bpm", "direction": "down"},
    ],
    "caption": "Overnight",
}
CHECKLIST = {
    "kind": "checklist",
    "items": [
        {"text": "Ship the report", "state": "done"},
        {"text": "Review the diff"},
        {"text": "Chase the vendor", "state": "skipped"},
    ],
    "caption": "Today",
}
CALLOUT = {"kind": "callout", "text": "Do not train today — HRV crashed.", "style": "alert"}

FIGURES = {"table": TABLE, "stat_row": STAT_ROW, "checklist": CHECKLIST, "callout": CALLOUT}


def _edition(sections):
    return {"title": "Figures", "sections": sections}


def _errors(figure):
    return validation.validate(_edition([{"text": "body", "figure": figure}]))


# ── valid payloads ──

@pytest.mark.parametrize("kind", sorted(FIGURES))
def test_figure_payload_valid(kind):
    assert _errors(FIGURES[kind]) == []


def test_optional_fields_may_be_omitted():
    assert _errors({"kind": "table", "columns": ["A"], "rows": [["1"]]}) == []
    assert _errors({"kind": "stat_row", "stats": [{"value": 1, "label": "One"}]}) == []
    assert _errors({"kind": "checklist", "items": [{"text": "Do it"}]}) == []
    assert _errors({"kind": "callout", "text": "Heads up"}) == []


def test_figure_only_section_is_valid():
    assert validation.validate(_edition([{"figure": CALLOUT}])) == []


def test_new_kinds_are_registered():
    assert set(validation._FIGURE_KINDS) >= {"table", "stat_row", "checklist", "callout"}


def test_unknown_kind_lists_the_valid_ones():
    errs = _errors({"kind": "pie"})
    assert any("sections[0]" in e and "'pie'" in e and "table" in e for e in errs)


# ── table ──

def test_table_requires_columns_and_rows():
    errs = _errors({"kind": "table", "rows": [["a"]]})
    assert any("sections[0]" in e and "'columns'" in e for e in errs)
    errs = _errors({"kind": "table", "columns": ["A"]})
    assert any("sections[0]" in e and "'rows'" in e for e in errs)
    errs = _errors({"kind": "table", "columns": ["A"], "rows": []})
    assert any("sections[0]" in e and "'rows'" in e for e in errs)


def test_table_row_must_be_a_list():
    errs = _errors({"kind": "table", "columns": ["A"], "rows": ["oops"]})
    assert any("sections[0]" in e and "rows[0]" in e and "list" in e for e in errs)


def test_table_align_values_checked():
    errs = _errors({"kind": "table", "columns": ["A"], "rows": [["1"]], "align": ["middle"]})
    assert any("sections[0]" in e and "align[0]" in e and "'middle'" in e for e in errs)
    errs = _errors({"kind": "table", "columns": ["A"], "rows": [["1"]], "align": "left"})
    assert any("sections[0]" in e and "'align'" in e and "list" in e for e in errs)


# ── stat_row ──

def test_stat_row_requires_stats():
    errs = _errors({"kind": "stat_row", "stats": []})
    assert any("sections[0]" in e and "'stats'" in e for e in errs)


def test_stat_row_caps_at_four():
    stats = [{"value": i, "label": f"S{i}"} for i in range(5)]
    errs = _errors({"kind": "stat_row", "stats": stats})
    assert any("sections[0]" in e and "'stats'" in e and "4" in e for e in errs)


def test_stat_requires_value_and_label():
    errs = _errors({"kind": "stat_row", "stats": [{"label": "HRV"}]})
    assert any("sections[0]" in e and "stats[0]" in e and "'value'" in e for e in errs)
    errs = _errors({"kind": "stat_row", "stats": [{"value": 92}]})
    assert any("sections[0]" in e and "stats[0]" in e and "'label'" in e for e in errs)


def test_stat_direction_values_checked():
    errs = _errors({"kind": "stat_row", "stats": [{"value": 1, "label": "L", "direction": "sideways"}]})
    assert any("sections[0]" in e and "stats[0]" in e and "'sideways'" in e for e in errs)


# ── checklist ──

def test_checklist_requires_items():
    errs = _errors({"kind": "checklist", "items": []})
    assert any("sections[0]" in e and "'items'" in e for e in errs)


def test_checklist_item_requires_text():
    errs = _errors({"kind": "checklist", "items": [{"state": "done"}]})
    assert any("sections[0]" in e and "items[0]" in e and "'text'" in e for e in errs)


def test_checklist_state_values_checked():
    errs = _errors({"kind": "checklist", "items": [{"text": "x", "state": "maybe"}]})
    assert any("sections[0]" in e and "items[0]" in e and "'maybe'" in e for e in errs)


# ── callout ──

def test_callout_requires_text():
    errs = _errors({"kind": "callout", "style": "note"})
    assert any("sections[0]" in e and "'text'" in e for e in errs)
    errs = _errors({"kind": "callout", "text": ""})
    assert any("sections[0]" in e and "'text'" in e for e in errs)


def test_callout_style_values_checked():
    errs = _errors({"kind": "callout", "text": "hi", "style": "warning"})
    assert any("sections[0]" in e and "'style'" in e and "'warning'" in e for e in errs)


def test_errors_name_the_offending_section_index():
    errs = validation.validate(_edition([
        {"text": "fine"},
        {"text": "bad", "figure": {"kind": "callout", "text": "hi", "style": "warning"}},
    ]))
    assert errs and all("sections[1]" in e for e in errs)


# ── render ──

PATH = "figtest/text"


def _png_bytes(path):
    meta = store.get_view_meta(path)
    assert meta is not None, f"no view rendered at {path}"
    name = meta["image"].rsplit("/", 1)[-1]
    return (config.DATA_DIR / "images" / name).read_bytes()


@pytest.mark.browser
def test_text_figures_render_to_a_palette_exact_panel_image():
    sections = [{"heading": "Plans", "text": "Body copy."}]
    sections += [{"heading": kind, "figure": FIGURES[kind]} for kind in sorted(FIGURES)]

    result = server.publish_edition(PATH, _edition(sections))
    assert result["success"] is True, result["error"]
    with_figures = _png_bytes(PATH)

    # Same path, same prose, no figures: the figures must change the pixels.
    text_only = _edition([{"heading": "Plans", "text": "Body copy."}])
    assert server.publish_edition(PATH, text_only)["success"] is True
    assert _png_bytes(PATH) != with_figures

    img = Image.open(io.BytesIO(with_figures))
    assert img.mode == "L"
    assert img.size == (config.SCREEN_WIDTH, config.SCREEN_HEIGHT)
    # 4-bit E Ink Carta: every pixel must land on one of the panel's 16 levels.
    levels = [value for _count, value in img.getcolors(maxcolors=256)]
    assert levels and all(value % 17 == 0 for value in levels)
