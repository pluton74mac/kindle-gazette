"""The timeline and qr figure kinds: validation, server-side QR generation, and
a browser-tier render of both inside one article."""
import base64
import math
from io import BytesIO

import pytest
from PIL import Image

from kindle_gazette import config, renderers, server, store, validation

PATH = "figtest/tlqr"
NAME = "figtest_tlqr"


def _edition(sections):
    return {"title": "T", "sections": sections}


# ── validation: valid payloads ──

def test_timeline_and_qr_figures_are_valid():
    assert validation.validate(_edition([
        {"figure": {"kind": "timeline", "events": [
            {"time": "09:00", "text": "Standup with the team", "emphasis": True},
            {"time": "Tue", "text": "Draft lands"},
            {"text": "No time label on this one"},
        ], "caption": "Today"}},
        {"figure": {"kind": "qr", "data": "https://example.com/full-report",
                    "caption": "Scan for the full report"}},
        {"text": "closing paragraph", "figure": {"kind": "qr", "data": "x" * 1000}},
    ])) == []


# ── validation: timeline errors name the section, index and field ──

def test_timeline_missing_or_bad_events():
    errs = validation.validate(_edition([{"figure": {"kind": "timeline"}}]))
    assert any("sections[0]" in e and "'events'" in e and "non-empty" in e for e in errs)

    errs = validation.validate(_edition([{"figure": {"kind": "timeline", "events": []}}]))
    assert any("sections[0]" in e and "'events'" in e for e in errs)

    errs = validation.validate(_edition([
        {"figure": {"kind": "timeline", "events": {"time": "09:00", "text": "not a list"}}},
    ]))
    assert any("sections[0]" in e and "'events'" in e for e in errs)


def test_timeline_per_event_field_errors():
    errs = validation.validate(_edition([
        {"figure": {"kind": "timeline", "events": [{"time": "09:00"}]}},          # no text
        {"figure": {"kind": "timeline", "events": [{"text": "ok"}, "09:00 talk"]}},
        {"figure": {"kind": "timeline", "events": [{"text": "ok", "time": 900}]}},
        {"figure": {"kind": "timeline", "events": [{"text": "ok", "emphasis": "yes"}]}},
    ]))
    assert any("sections[0]" in e and "events[0]" in e and "'text'" in e for e in errs)
    assert any("sections[1]" in e and "events[1]" in e and "must be an object" in e for e in errs)
    assert any("sections[2]" in e and "events[0]" in e and "'time'" in e for e in errs)
    assert any("sections[3]" in e and "events[0]" in e and "'emphasis'" in e for e in errs)


# ── validation: qr data errors ──

def test_qr_data_missing_empty_and_overlong():
    errs = validation.validate(_edition([
        {"figure": {"kind": "qr"}},
        {"figure": {"kind": "qr", "data": ""}},
        {"figure": {"kind": "qr", "data": 12345}},
        {"figure": {"kind": "qr", "data": "x" * 1001}},
    ]))
    assert any("sections[0]" in e and "'data'" in e for e in errs)
    assert any("sections[1]" in e and "'data'" in e for e in errs)
    assert any("sections[2]" in e and "'data'" in e for e in errs)
    overlong = [e for e in errs if "sections[3]" in e]
    assert overlong and "1001" in overlong[0] and "1000" in overlong[0]


def test_qr_caption_must_be_a_string():
    errs = validation.validate(_edition([
        {"figure": {"kind": "qr", "data": "https://example.com", "caption": 7}},
    ]))
    assert any("sections[0]" in e and "'caption'" in e for e in errs)


# ── QR generation: pure black/white, square, integer module scale ──

@pytest.mark.parametrize("payload", ["https://example.com/full-report", "x" * 1000])
def test_qr_data_uri_is_a_square_two_tone_png(payload):
    src, size = renderers._qr_data_uri(payload)
    assert src.startswith("data:image/png;base64,")
    image = Image.open(BytesIO(base64.b64decode(src.split(",", 1)[1])))
    assert image.width == image.height == size
    # Pure black on white: nothing in between, so dithering can't blur a module.
    assert {v for _count, v in image.convert("L").getcolors(256)} <= {0, 255}
    # Integer module scale: every black/white run on a row shares a common
    # divisor of 2+ px, i.e. no module landed on a fractional boundary.
    pixels = image.convert("L").load()
    row = [pixels[x, size // 2] for x in range(size)]
    runs, run = [], 1
    for prev, cur in zip(row, row[1:]):
        if cur == prev:
            run += 1
        else:
            runs.append(run)
            run = 1
    runs.append(run)
    assert math.gcd(*runs) >= 2, f"fractional module scale: runs {sorted(set(runs))}"
    # Sized for the 1072px page: ~340px, give or take one module of rounding.
    assert 250 <= size <= 430


def test_qr_figure_context_carries_natural_size():
    context = renderers._figure_context({"kind": "qr", "data": "https://example.com", "caption": "c"})
    assert context["kind"] == "qr" and context["caption"] == "c"
    assert context["src"].startswith("data:image/png;base64,")
    image = Image.open(BytesIO(base64.b64decode(context["src"].split(",", 1)[1])))
    assert image.width == context["size"]


def test_figure_context_drops_undrawable_figures():
    assert renderers._figure_context({"kind": "qr", "data": ""}) is None
    assert renderers._figure_context({"kind": "timeline", "events": []}) is None
    assert renderers._figure_context({"kind": "timeline", "events": [{"text": "  "}]}) is None


def test_timeline_figure_context_normalizes_events():
    context = renderers._figure_context({"kind": "timeline", "events": [
        {"time": "09:00", "text": "Standup", "emphasis": True},
        {"text": "No time"},
        {"text": "   "},
    ]})
    assert context["events"] == [
        {"text": "Standup", "time": "09:00", "emphasis": True},
        {"text": "No time", "time": "", "emphasis": False},
    ]


# ── browser tier: both kinds render inside a real article page ──

@pytest.mark.browser
def test_edition_with_timeline_and_qr_renders():
    text_only = {"title": "Schedule", "sections": [
        {"heading": "The day", "text": "Everything ran on time."},
    ]}
    with_figures = {"title": "Schedule", "byline": "test-agent", "sections": [
        {"heading": "The day", "text": "Everything ran on time."},
        {"figure": {"kind": "timeline", "events": [
            {"time": "09:00", "text": "Standup with the team"},
            {"time": "11:30", "text": "Deploy window opens", "emphasis": True},
            {"time": "14:00", "text": "Review of the quarterly figures"},
            {"text": "Retro, once everyone is back"},
        ], "caption": "Today, in order"}},
        {"text": "The full write-up lives off-device.",
         "figure": {"kind": "qr", "data": "https://example.com/full-report",
                    "caption": "Scan for the full report"}},
    ]}

    assert server.publish_edition(PATH, text_only)["success"] is True
    plain_png = (config.DATA_DIR / "images" / f"{NAME}.png").read_bytes()

    result = server.publish_edition(PATH, with_figures)
    assert result["success"] is True, result["error"]
    assert "warnings" not in result
    figure_png = (config.DATA_DIR / "images" / f"{NAME}.png").read_bytes()

    # The figures visibly changed the page (template didn't drop them).
    assert figure_png != plain_png
    rendered = Image.open(BytesIO(figure_png))
    assert rendered.mode == "L"
    # Panel-exact after dithering, same contract as every view.
    assert {v for _count, v in rendered.getcolors(256)} <= {i * 17 for i in range(16)}
    assert store.get_view_meta(PATH) is not None
