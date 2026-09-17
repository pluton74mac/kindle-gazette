"""Browser tier: edition pagination — page paths, PREV/NEXT wiring, stale-page
cleanup, rerender, and the reserved /pN segment."""
import pytest

from kindle_gazette import config, server, store

import _util

PATH = "news/digest"
NAME = "news_digest"


def _long_body(paragraphs=40):
    para = ("The quick brown fox jumps over the lazy dog while the market "
            "watches carefully and the sensors keep logging every reading. ") * 3
    chunks = []
    for i in range(paragraphs):
        if i % 8 == 0:
            chunks.append(f"## Section {i // 8 + 1}")
        chunks.append(f"Paragraph {i + 1}. {para}")
    return "\n\n".join(chunks)


def _publish(body, title="Long Read"):
    result = server.publish_edition(PATH, {"title": title, "body": body})
    assert result["success"] is True, result["error"]
    return result


def _tap(meta, label):
    hits = [t for t in meta["taps"] if t["label"] == label]
    return hits[0] if hits else None


@pytest.mark.browser
def test_long_edition_paginates_with_nav_and_titles():
    _publish(_long_body())

    metas = {}
    for page_path in (PATH, f"{PATH}/p2", f"{PATH}/p3"):
        metas[page_path] = store.get_view_meta(page_path)
        assert metas[page_path] is not None, f"expected a page at {page_path}"

    # Page images point at per-page PNGs, and the files exist.
    assert metas[f"{PATH}/p2"]["image"] == f"/images/{NAME}_p2.png"
    assert (config.DATA_DIR / "images" / f"{NAME}_p2.png").exists()

    # Registry rows: base keeps the title, continuations get "(p.k)".
    rows = {r["path"]: r for r in store.list_views()}
    assert rows[PATH]["title"] == "Long Read"
    assert rows[f"{PATH}/p2"]["title"] == "Long Read (p.2)"
    assert rows[f"{PATH}/p3"]["title"] == "Long Read (p.3)"

    # Page 1: NEXT -> p2, no PREV, BACK -> home, EXIT present.
    p1 = metas[PATH]
    assert _tap(p1, "Next page")["target"] == f"{PATH}/p2"
    assert _tap(p1, "Previous page") is None
    assert _tap(p1, "Back")["target"] == "home"
    assert any(t["action"] == "exit" for t in p1["taps"])

    # Page 2: PREV -> base path (not p1), NEXT -> p3, BACK still present.
    p2 = metas[f"{PATH}/p2"]
    assert _tap(p2, "Previous page")["target"] == PATH
    assert _tap(p2, "Next page")["target"] == f"{PATH}/p3"
    assert _tap(p2, "Back")["target"] == "home"

    # Page 3: PREV -> p2.
    p3 = metas[f"{PATH}/p3"]
    assert _tap(p3, "Previous page")["target"] == f"{PATH}/p2"

    # Last page has no NEXT.
    last = max(int(p.split("/p")[-1]) for p in rows if p.startswith(f"{PATH}/p"))
    last_meta = store.get_view_meta(f"{PATH}/p{last}")
    assert _tap(last_meta, "Next page") is None


@pytest.mark.browser
def test_continuation_pages_have_no_raw_data():
    _publish(_long_body())
    assert store.get_view_data(PATH) is not None
    assert store.get_view_data(f"{PATH}/p2") is None
    assert not (config.DATA_DIR / f"{NAME}_p2.data.json").exists()
    # Only the base path is re-renderable.
    assert PATH in store.list_data_paths()
    assert f"{PATH}/p2" not in store.list_data_paths()


@pytest.mark.browser
def test_shortened_edition_deletes_stale_pages():
    _publish(_long_body())
    assert store.get_view_meta(f"{PATH}/p3") is not None

    _publish("Just one short paragraph now.", title="Short Read")

    for stale in (f"{PATH}/p2", f"{PATH}/p3"):
        name = store.path_to_name(stale)
        assert store.get_view_meta(stale) is None
        assert not (config.DATA_DIR / f"{name}.json").exists()
        assert not (config.DATA_DIR / "images" / f"{name}.png").exists()
    rows = {r["path"] for r in store.list_views()}
    assert rows & {f"{PATH}/p2", f"{PATH}/p3"} == set()
    assert PATH in rows


@pytest.mark.browser
def test_rerender_all_rebuilds_editions_and_generated_views():
    _publish(_long_body())
    assert server.publish_edition("ops/jobs", _util.EDITION)["success"]
    assert server.publish_edition(
        "news/extra", _util.EDITION,
        {"title": "News", "summary": ["fresh digest"], "nav_target": PATH})["success"]

    # Wipe the PNGs so we can prove rerender recreates them.
    for png in (config.DATA_DIR / "images").glob("*.png"):
        png.unlink()

    result = server.rerender(None)
    assert result["errors"] == {}
    assert result["success"] is True
    assert set(result["rendered"]) >= {PATH, "ops/jobs", "home", "system/agents"}
    # Continuation pages are not listed individually but come back with the base.
    assert f"{PATH}/p2" not in result["rendered"]
    assert (config.DATA_DIR / "images" / f"{NAME}.png").exists()
    assert (config.DATA_DIR / "images" / f"{NAME}_p2.png").exists()
    assert (config.DATA_DIR / "images" / "home.png").exists()
    assert (config.DATA_DIR / "images" / "system_agents.png").exists()
    assert store.get_view_meta(f"{PATH}/p2") is not None


@pytest.mark.browser
def test_image_figure_height_counts_toward_pagination():
    """Regression: the page count used to be measured at script-parse time,
    before images decoded — an un-sized data-URI image had zero height, the
    count came out low, and the article's tail pages were never rendered."""
    import base64
    from io import BytesIO

    from PIL import Image

    img = Image.new("L", (200, 600), 128)
    buf = BytesIO()
    img.save(buf, format="PNG")
    tall_image = base64.b64encode(buf.getvalue()).decode()

    para = "A paragraph that occupies a line or two of the article column. " * 2
    data = {"title": "Tail Test", "sections": [
        {"text": "\n\n".join([para] * 4)},
        {"figure": {"kind": "image", "data": tall_image, "caption": "600px tall"}},
        {"text": "\n\n".join([para] * 4)},
    ]}
    assert server.publish_edition(PATH, data)["success"] is True
    # Text alone fits one page; the image's real height must push it to two.
    assert store.get_view_meta(f"{PATH}/p2") is not None, \
        "image height ignored by pagination — article tail was dropped"


@pytest.mark.browser
def test_edition_with_figures_renders():
    """Sections may embed sparkline / bars / image figures in the text flow."""
    import base64
    from io import BytesIO

    from PIL import Image

    # A recognizable image payload: solid black 64x64 PNG.
    img = Image.new("L", (64, 64), 0)
    buf = BytesIO()
    img.save(buf, format="PNG")
    black_square = base64.b64encode(buf.getvalue()).decode()

    text_only = {"title": "Figures", "sections": [
        {"heading": "Numbers", "text": "The trend held steady overnight."},
    ]}
    with_figures = {"title": "Figures", "byline": "test-agent", "sections": [
        {"heading": "Numbers", "text": "The trend held steady overnight."},
        {"figure": {"kind": "sparkline", "values": [88, 95, 90, 102, 84],
                    "baseline": 95, "caption": "7-day trend"}},
        {"figure": {"kind": "bars", "bars": [{"label": "Protein", "value": 120, "max": 160}],
                    "caption": "Daily targets"}},
        {"text": "A closing paragraph after the figures.",
         "figure": {"kind": "image", "data": black_square, "caption": "A black square"}},
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
    assert {v for _c, v in rendered.getcolors(256)} <= {i * 17 for i in range(16)}


def test_user_path_ending_in_page_segment_rejected():
    # No browser needed: rejected before any rendering happens.
    result = server.publish_edition("foo/p2", {"title": "T", "body": "x"})
    assert result["success"] is False
    assert "reserved" in result["error"]
    # Page-like segments are only reserved in last position: "p2/foo" must not
    # trip the pN rule. (Payload is deliberately invalid so no render happens —
    # keeps this test out of the browser tier.)
    result = server.publish_edition("p2/foo", {"title": "T", "sections": "oops"})
    assert "reserved" not in (result.get("error") or "")
    assert "'sections' must be a list" in result["error"]
