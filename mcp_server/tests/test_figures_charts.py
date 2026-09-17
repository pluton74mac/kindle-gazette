"""Chart figure kinds: line_chart, heatmap, stacked_bar, and the bars target
tick — validation shapes plus a browser-tier render of each."""
from io import BytesIO

import pytest

from kindle_gazette import config, server, store, validation

PATH = "figtest/charts"
NAME = "figtest_charts"


def _edition(sections):
    return {"title": "T", "sections": sections}


# ── validation: valid payloads ──

def test_chart_figures_valid():
    assert validation.validate(_edition([
        {"figure": {"kind": "line_chart",
                    "series": [{"label": "HRV", "values": [88, 95, 90]},
                               {"label": "RHR", "values": [61, 58, 60]}],
                    "x_labels": ["Mon", "Tue", "Wed"], "baseline": 95,
                    "y_min": 50, "y_max": 100, "caption": "c"}},
        {"figure": {"kind": "heatmap", "rows": [[0, 2, None, 3], [1, 4, 2, 0]],
                    "row_labels": ["Week 34", "Week 35"],
                    "col_labels": ["Mon", "Tue", "Wed", "Thu"], "scale_max": 5}},
        {"figure": {"kind": "stacked_bar", "max": 2400,
                    "segments": [{"label": "Protein", "value": 480},
                                 {"label": "Carbs", "value": 900}]}},
        {"figure": {"kind": "bars",
                    "bars": [{"label": "Protein", "value": 120, "max": 160, "target": 140}]}},
    ])) == []


def test_optional_fields_may_be_omitted_or_null():
    assert validation.validate(_edition([
        {"figure": {"kind": "line_chart", "series": [{"label": "HRV", "values": [1, 2]}],
                    "baseline": None, "y_min": None, "y_max": None}},
        {"figure": {"kind": "heatmap", "rows": [[1, 2]], "scale_max": None}},
        {"figure": {"kind": "stacked_bar", "segments": [{"label": "A", "value": 1}]}},
    ])) == []


# ── validation: line_chart ──

def test_line_chart_series_errors():
    errs = validation.validate(_edition([
        {"figure": {"kind": "line_chart"}},                                     # no series
        {"figure": {"kind": "line_chart", "series": [{"values": [1, 2]}]}},      # no label
        {"figure": {"kind": "line_chart", "series": [{"label": "A", "values": [1]}]}},
        {"figure": {"kind": "line_chart", "series": [{"label": "A", "values": [1, "x"]}]}},
    ]))
    assert any("sections[0]" in e and "'series'" in e for e in errs)
    assert any("sections[1]" in e and "series[0]" in e and "'label'" in e for e in errs)
    assert any("sections[2]" in e and "series[0]" in e and "2+ numbers" in e for e in errs)
    assert any("sections[3]" in e and "series[0]" in e and "2+ numbers" in e for e in errs)


def test_line_chart_rejects_more_than_three_series():
    errs = validation.validate(_edition([
        {"figure": {"kind": "line_chart", "series": [
            {"label": f"S{i}", "values": [1, 2]} for i in range(4)
        ]}},
    ]))
    assert any("sections[0]" in e and "at most 3" in e and "got 4" in e for e in errs)
    # Exactly three is fine.
    assert validation.validate(_edition([
        {"figure": {"kind": "line_chart", "series": [
            {"label": f"S{i}", "values": [1, 2]} for i in range(3)
        ]}},
    ])) == []


def test_line_chart_series_must_share_x_axis():
    errs = validation.validate(_edition([
        {"figure": {"kind": "line_chart", "series": [{"label": "A", "values": [1, 2, 3]},
                                                     {"label": "B", "values": [1, 2]}]}},
    ]))
    assert any("sections[0]" in e and "same number of 'values'" in e for e in errs)


def test_line_chart_scalar_and_label_field_errors():
    errs = validation.validate(_edition([
        {"figure": {"kind": "line_chart", "series": [{"label": "A", "values": [1, 2]}],
                    "baseline": "high", "y_min": "lo", "y_max": [3], "x_labels": [1, 2]}},
    ]))
    joined = " ".join(errs)
    for field in ("'baseline'", "'y_min'", "'y_max'"):
        assert f"sections[0]: line_chart {field} must be a number" in joined
    assert any("sections[0]" in e and "'x_labels'" in e and "list of strings" in e for e in errs)


# ── validation: heatmap ──

def test_heatmap_ragged_rows_rejected():
    errs = validation.validate(_edition([
        {"figure": {"kind": "heatmap", "rows": [[1, 2, 3], [1, 2]]}},
    ]))
    assert any("sections[0]" in e and "rows[1]" in e and "same length" in e for e in errs)


def test_heatmap_cell_and_row_shape_errors():
    errs = validation.validate(_edition([
        {"figure": {"kind": "heatmap", "rows": []}},
        {"figure": {"kind": "heatmap", "rows": [[]]}},
        {"figure": {"kind": "heatmap", "rows": [[1, "hot"]]}},
        {"figure": {"kind": "heatmap", "rows": [[1, 2]], "scale_max": "max"}},
    ]))
    assert any("sections[0]" in e and "'rows'" in e for e in errs)
    assert any("sections[1]" in e and "rows[0]" in e and "non-empty" in e for e in errs)
    assert any("sections[2]" in e and "rows[0][1]" in e and "number or null" in e for e in errs)
    assert any("sections[3]" in e and "'scale_max'" in e for e in errs)


def test_heatmap_label_counts_must_match():
    errs = validation.validate(_edition([
        {"figure": {"kind": "heatmap", "rows": [[1, 2], [3, 4]],
                    "row_labels": ["only one"], "col_labels": ["a", "b", "c"]}},
    ]))
    assert any("sections[0]" in e and "'row_labels'" in e and "needs 2" in e for e in errs)
    assert any("sections[0]" in e and "'col_labels'" in e and "needs 2" in e for e in errs)


# ── validation: stacked_bar + bars target ──

def test_stacked_bar_segment_errors():
    errs = validation.validate(_edition([
        {"figure": {"kind": "stacked_bar", "segments": []}},
        {"figure": {"kind": "stacked_bar", "segments": [{"label": "A", "value": "lots"}]}},
        {"figure": {"kind": "stacked_bar", "segments": [{"label": "A", "value": 1}], "max": "2400"}},
    ]))
    assert any("sections[0]" in e and "'segments'" in e and "non-empty" in e for e in errs)
    assert any("sections[1]" in e and "segments[0]" in e and "'value'" in e for e in errs)
    assert any("sections[2]" in e and "'max'" in e for e in errs)


def test_bars_target_must_be_a_number():
    errs = validation.validate(_edition([
        {"figure": {"kind": "bars",
                    "bars": [{"label": "Protein", "value": 120, "max": 160, "target": "140g"}]}},
    ]))
    assert any("sections[0]" in e and "bars[0]" in e and "'target'" in e for e in errs)
    # A numeric target is fine, and the tick is optional.
    assert validation.validate(_edition([
        {"figure": {"kind": "bars",
                    "bars": [{"label": "Protein", "value": 120, "max": 160, "target": 140},
                             {"label": "Water", "value": 1.5, "max": 3}]}},
    ])) == []


# ── browser tier: the figures actually render ──

def _png(path_name=NAME):
    return (config.DATA_DIR / "images" / f"{path_name}.png").read_bytes()


def _assert_panel_exact(png_bytes):
    """Every view must come off the renderer as mode "L" on the panel's 16
    grays — the heatmap additionally computes its fills to land there exactly."""
    from PIL import Image

    image = Image.open(BytesIO(png_bytes))
    assert image.mode == "L"
    assert {v for _count, v in image.getcolors(256)} <= {i * 17 for i in range(16)}


@pytest.mark.browser
def test_chart_figures_render_into_an_edition():
    text_only = {"title": "Charts", "sections": [
        {"heading": "Numbers", "text": "The week held steady."},
    ]}
    assert server.publish_edition(PATH, text_only)["success"] is True
    plain_png = _png()

    with_figures = {"title": "Charts", "byline": "test-agent", "sections": [
        {"heading": "Numbers", "text": "The week held steady."},
        {"figure": {"kind": "line_chart",
                    "series": [{"label": "HRV", "values": [88, 95, 90, 102, 84, 91, 97]},
                               {"label": "RHR", "values": [61, 58, 60, 57, 62, 59, 58]},
                               {"label": "Sleep", "values": [70, 74, 68, 80, 66, 72, 78]}],
                    "x_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    "baseline": 80, "caption": "Three series, one baseline"}},
        {"figure": {"kind": "heatmap",
                    "rows": [[0, 2, 5, None], [1, 4, 0, 3], [None, 0, 2, 5]],
                    "row_labels": ["Week 34", "Week 35", "Week 36"],
                    "col_labels": ["Mon", "Tue", "Wed", "Thu"],
                    "caption": "Sessions per day"}},
        {"figure": {"kind": "stacked_bar", "max": 2400,
                    "segments": [{"label": "Protein", "value": 480},
                                 {"label": "Carbs", "value": 900},
                                 {"label": "Fat", "value": 620}],
                    "caption": "Calories by macro"}},
        {"text": "Targets are the ticks on each track.",
         "figure": {"kind": "bars",
                    "bars": [{"label": "Protein", "value": 120, "max": 160, "target": 140},
                             {"label": "Steps", "value": 11000, "max": 12000, "target": 8000}],
                    "caption": "Daily targets"}},
    ]}

    result = server.publish_edition(PATH, with_figures)
    assert result["success"] is True, result["error"]
    assert "warnings" not in result
    figure_png = _png()

    # The figures visibly changed the page (no branch silently dropped them).
    assert figure_png != plain_png
    _assert_panel_exact(figure_png)


@pytest.mark.browser
@pytest.mark.parametrize("figure", [
    {"kind": "line_chart", "series": [{"label": "Only", "values": [3, 1, 4, 1, 5]}],
     "y_min": 0, "y_max": 6},
    {"kind": "heatmap", "rows": [[0, None], [7, 3]]},
    {"kind": "stacked_bar", "segments": [{"label": "All of it", "value": 10}]},
])
def test_each_chart_figure_renders_alone(figure):
    """Minimal payloads (no labels, no caption, single series/segment) still
    produce a page — the geometry helpers must not need the optional fields."""
    result = server.publish_edition(PATH, _edition([{"figure": figure}]) | {"title": "Solo"})
    assert result["success"] is True, result["error"]
    _assert_panel_exact(_png())


@pytest.mark.browser
def test_bars_target_tick_renders():
    """The target tick is drawn whether the fill has passed it or not, so a
    bars figure with targets must differ pixel-wise from one without."""
    bars = [{"label": "Protein", "value": 120, "max": 160},
            {"label": "Water", "value": 1.5, "max": 3}]
    path = "figtest/progress"
    name = store.path_to_name(path)

    assert server.publish_edition(
        path, _edition([{"figure": {"kind": "bars", "bars": bars}}]))["success"] is True
    without = _png(name)

    with_targets = [dict(bars[0], target=140), dict(bars[1], target=2)]
    assert server.publish_edition(
        path, _edition([{"figure": {"kind": "bars", "bars": with_targets}}]))["success"] is True
    ticked = _png(name)

    assert ticked != without
    _assert_panel_exact(ticked)
