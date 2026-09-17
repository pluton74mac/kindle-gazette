"""The link_list figure: validation, normalization, and — the point of the
kind — that every row comes back as a real tap in the rendered page's tap map,
including when it lands next to a page boundary."""
import pytest

from kindle_gazette import renderers, server, store, validation

PATH = "figtest/links"

LINKS = {
    "kind": "link_list",
    "links": [
        {"text": "Fleet status", "nav_target": "ops/fleet", "note": "2 min ago"},
        {"text": "Nutrition log", "nav_target": "life/nutrition"},
        {"text": "The Dispatch", "nav_target": "news/dispatch", "note": "06:50"},
    ],
    "caption": "Elsewhere in this edition",
}
TARGETS = {link["nav_target"] for link in LINKS["links"]}


def _edition(sections):
    return {"title": "Index", "sections": sections}


def _errors(figure):
    return validation.validate(_edition([{"text": "body", "figure": figure}]))


# ── validation ──

def test_link_list_payload_valid():
    assert _errors(LINKS) == []
    # note and caption are optional.
    assert _errors({"kind": "link_list", "links": [{"text": "A", "nav_target": "a/b"}]}) == []


def test_link_list_is_a_registered_kind():
    assert "link_list" in validation._FIGURE_KINDS


def test_link_list_requires_a_non_empty_links_list():
    for figure in ({"kind": "link_list"},
                   {"kind": "link_list", "links": []},
                   {"kind": "link_list", "links": "ops/fleet"}):
        errs = _errors(figure)
        assert any("sections[0]" in e and "'links'" in e and "non-empty" in e for e in errs), figure


def test_link_requires_text_and_nav_target():
    errs = _errors({"kind": "link_list", "links": [{"nav_target": "ops/fleet"}]})
    assert any("sections[0]" in e and "links[0]" in e and "'text'" in e for e in errs)
    errs = _errors({"kind": "link_list", "links": [{"text": "Fleet"}]})
    assert any("sections[0]" in e and "links[0]" in e and "'nav_target'" in e for e in errs)


def test_link_rejects_empty_and_wrongly_typed_fields():
    errs = _errors({"kind": "link_list", "links": [{"text": "  ", "nav_target": ""}]})
    assert any("links[0]" in e and "'text'" in e and "non-empty" in e for e in errs)
    assert any("links[0]" in e and "'nav_target'" in e and "non-empty" in e for e in errs)

    errs = _errors({"kind": "link_list", "links": [{"text": 7, "nav_target": ["a"]}]})
    assert any("links[0]" in e and "'text'" in e and "must be a string" in e for e in errs)
    assert any("links[0]" in e and "'nav_target'" in e and "must be a string" in e for e in errs)


def test_link_entry_must_be_an_object():
    errs = _errors({"kind": "link_list", "links": ["ops/fleet"]})
    assert any("sections[0]" in e and "links[0]" in e and "must be an object" in e for e in errs)


def test_link_note_must_be_a_string():
    errs = _errors({"kind": "link_list",
                    "links": [{"text": "A", "nav_target": "a/b", "note": 3}]})
    assert any("links[0]" in e and "'note'" in e and "must be a string" in e for e in errs)


def test_errors_name_the_offending_link_index():
    errs = _errors({"kind": "link_list", "links": [
        {"text": "A", "nav_target": "a/b"},
        {"text": "B"},
    ]})
    assert errs and all("links[1]" in e for e in errs)


# ── normalization ──

def test_figure_context_normalizes_links():
    context = renderers._figure_context({"kind": "link_list", "links": [
        {"text": " Fleet ", "nav_target": " ops/fleet ", "note": " 2 min ago "},
        {"text": "No note", "nav_target": "a/b"},
    ], "caption": "c"})
    assert context == {
        "kind": "link_list",
        "caption": "c",
        "links": [
            {"text": "Fleet", "nav_target": "ops/fleet", "note": "2 min ago"},
            {"text": "No note", "nav_target": "a/b", "note": None},
        ],
    }


def test_figure_context_drops_undrawable_links():
    """A row with no label or no destination would be a tap that goes nowhere."""
    context = renderers._figure_context({"kind": "link_list", "links": [
        {"text": "", "nav_target": "a/b"},
        {"text": "No target", "nav_target": "  "},
        "not an object",
        {"text": "Good", "nav_target": "a/b"},
    ]})
    assert [link["text"] for link in context["links"]] == ["Good"]
    # Nothing drawable at all: the whole figure is dropped, like every other kind.
    assert renderers._figure_context({"kind": "link_list", "links": []}) is None
    assert renderers._figure_context(
        {"kind": "link_list", "links": [{"text": "x", "nav_target": ""}]}) is None


# ── browser tier: the tap map ──

def _pages():
    """Every rendered page of PATH, in order."""
    metas = []
    for i in range(1, 20):
        page = PATH if i == 1 else f"{PATH}/p{i}"
        meta = store.get_view_meta(page)
        if meta is None:
            break
        metas.append(meta)
    return metas


def _filler(paragraphs):
    para = ("The quick brown fox jumps over the lazy dog while the market watches "
            "carefully and the sensors keep logging every reading. ") * 3
    return [{"text": f"Paragraph {i + 1}. {para}"} for i in range(paragraphs)]


@pytest.mark.browser
def test_every_link_becomes_a_tap():
    result = server.publish_edition(PATH, _edition([{"text": "Where to next."},
                                                    {"figure": LINKS}]))
    assert result["success"] is True, result["error"]

    taps = _pages()[0]["taps"]
    by_target = {t["target"]: t for t in taps if t["action"] == "navigate"}
    assert TARGETS <= set(by_target)
    for link in LINKS["links"]:
        tap = by_target[link["nav_target"]]
        # The row's own label, not scavenged text — and a real, hittable rect.
        assert tap["label"] == link["text"]
        assert tap["w"] > 0 and tap["h"] > 0


@pytest.mark.browser
@pytest.mark.parametrize("paragraphs", [10, 13, 16])
def test_links_survive_a_page_boundary(paragraphs):
    """Figures never split across pages, so however the prose before it falls,
    the link rows must all land — intact — on exactly one page.

    Also the regression guard for tap extraction on a paginated edition: the
    other pages stay in the DOM, translated off to the side, so a tap map that
    clamped off-screen rects into the viewport (rather than clipping them away)
    would report every page's links on every page."""
    sections = _filler(paragraphs) + [{"figure": LINKS}] + _filler(3)
    result = server.publish_edition(PATH, _edition(sections))
    assert result["success"] is True, result["error"]

    pages = _pages()
    assert len(pages) > 1, "test needs a multi-page edition to be meaningful"
    found = [
        {t["target"] for t in meta["taps"] if t["action"] == "navigate"} & TARGETS
        for meta in pages
    ]
    carrying = [page_targets for page_targets in found if page_targets]
    assert len(carrying) == 1, f"link rows spread over {len(carrying)} pages: {found}"
    assert carrying[0] == TARGETS, f"page carries only {carrying[0]}"
