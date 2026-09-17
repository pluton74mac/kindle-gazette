"""validation.py: edition-schema validation, per-figure shape examples, and
forward-compat warnings."""
import copy
import json

import pytest

from kindle_gazette import validation

import _util

FIXTURES = {"prose": _util.EDITION, "showcase": _util.SHOWCASE_EDITION}


# ── the canonical editions validate ──

@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_edition_valid(name):
    assert validation.validate(copy.deepcopy(FIXTURES[name])) == []


def test_edition_shape_example_is_valid():
    """The example returned in top-level error messages must itself validate."""
    assert validation.validate(json.loads(validation.shape_example())) == []


@pytest.mark.parametrize("kind", sorted(validation._FIGURE_EXAMPLES))
def test_figure_shape_example_is_valid(kind):
    """Every per-kind example must validate as a figure inside an edition."""
    figure = json.loads(validation.shape_example(kind))
    assert figure["kind"] == kind
    assert validation.validate({"title": "T", "sections": [{"figure": figure}]}) == []


def test_shape_example_falls_back_to_the_edition():
    assert validation.shape_example("not_a_kind") == validation.shape_example()


def test_every_figure_kind_has_an_example():
    assert set(validation._FIGURE_EXAMPLES) == set(validation._FIGURE_KINDS)


# ── failure_example picks the figure the errors are about ──

def test_failure_example_names_the_offending_figure_kind():
    data = {"title": "T", "sections": [{"figure": {"kind": "checklist", "items": []}}]}
    errors = validation.validate(data)
    assert errors
    assert validation.failure_example(data, errors) == validation.shape_example("checklist")


@pytest.mark.parametrize("kind", [["sparkline"], {"a": 1}, 7, None])
def test_failure_example_survives_a_junk_kind(kind):
    """`kind` is agent input: an unhashable one must not blow up the lookup."""
    data = {"title": "T", "sections": [{"figure": {"kind": kind}}]}
    errors = validation.validate(data)
    assert errors
    assert validation.failure_example(data, errors) == validation.shape_example()


def test_failure_example_falls_back_to_the_edition():
    # A top-level error, even alongside a figure error, wants the whole shape.
    data = {"sections": [{"figure": {"kind": "checklist", "items": []}}]}
    errors = validation.validate(data)
    assert validation.failure_example(data, errors) == validation.shape_example()
    # Two different broken kinds: no single figure example would help.
    data = {"title": "T", "sections": [
        {"figure": {"kind": "checklist", "items": []}},
        {"figure": {"kind": "callout"}},
    ]}
    errors = validation.validate(data)
    assert validation.failure_example(data, errors) == validation.shape_example()


# ── required top-level fields ──

def test_missing_title():
    errs = validation.validate({"body": "text"})
    assert any("'title'" in e for e in errs)


def test_no_type_field_is_required_or_understood():
    """The discriminator is gone: a payload carrying one is valid, and `type`
    comes back as an unknown field rather than a schema selector."""
    data = {"type": "article", "title": "T", "body": "x"}
    assert validation.validate(data) == []
    assert validation.collect_warnings(data) == ["unknown field 'type' (ignored)"]


def test_body_xor_sections():
    neither = validation.validate({"title": "T"})
    both = validation.validate({"title": "T", "body": "x", "sections": [{"text": "y"}]})
    for errs in (neither, both):
        assert any("exactly one of 'body'" in e for e in errs)
    # Each alone is fine.
    assert validation.validate({"title": "T", "body": "x"}) == []
    assert validation.validate({"title": "T", "sections": [{"text": "y"}]}) == []


def test_common_field_type_errors():
    errs = validation.validate({"title": 5, "back": 3, "refresh_sec": "soon",
                                "byline": [], "body": 7})
    joined = " ".join(errs)
    assert "'title' must be a string" in joined
    assert "'back' must be a string" in joined
    assert "'refresh_sec' must be a number" in joined
    assert "'byline' must be a string" in joined
    assert "'body' must be a string" in joined


def test_sections_must_be_a_list_of_objects():
    errs = validation.validate({"title": "T", "sections": "one section"})
    assert any("'sections' must be a list" in e for e in errs)
    errs = validation.validate({"title": "T", "sections": ["just a string"]})
    assert any("sections[0] must be an object" in e for e in errs)


def test_section_needs_text_or_figure():
    errs = validation.validate({"title": "T", "sections": [{"heading": "H"}]})
    assert any("sections[0]" in e and "'text'" in e for e in errs)


# ── article figure blocks ──

def _edition(sections):
    return {"title": "T", "sections": sections}


def test_figure_only_section_is_valid():
    assert validation.validate(_edition([
        {"figure": {"kind": "sparkline", "values": [1, 2, 3], "baseline": 2, "caption": "c"}},
        {"figure": {"kind": "bars", "bars": [{"label": "Protein", "value": 120, "max": 160}]}},
        {"figure": {"kind": "image", "data": "aGVsbG8=", "format": "jpeg"}},
        {"text": "closing paragraph", "figure": {"kind": "image", "data": "data:image/png;base64,aGVsbG8="}},
    ])) == []


def test_figure_bad_kind_and_shape():
    errs = validation.validate(_edition([{"figure": {"kind": "pie", "values": [1]}}]))
    assert any("sections[0]" in e and "'kind'" in e and "pie" in e for e in errs)

    errs = validation.validate(_edition([{"figure": "sparkline"}]))
    assert any("sections[0]" in e and "must be an object" in e for e in errs)


def test_figure_per_kind_field_errors():
    errs = validation.validate(_edition([
        {"figure": {"kind": "sparkline", "values": [1]}},              # too few values
        {"figure": {"kind": "sparkline", "values": [1, 2], "baseline": "x"}},
        {"figure": {"kind": "bars", "bars": []}},                      # empty
        {"figure": {"kind": "bars", "bars": [{"value": "n/a"}]}},      # missing label, bad nums
        {"figure": {"kind": "image"}},                                 # missing data
        {"figure": {"kind": "image", "data": "aGVsbG8=", "format": "gif"}},
    ]))
    assert any("sections[0]" in e and "2+ numbers" in e for e in errs)
    assert any("sections[1]" in e and "'baseline'" in e for e in errs)
    assert any("sections[2]" in e and "non-empty" in e for e in errs)
    assert any("sections[3]" in e and "'label'" in e for e in errs)
    assert any("sections[3]" in e and "'value'" in e for e in errs)
    assert any("sections[4]" in e and "'data'" in e for e in errs)
    assert any("sections[5]" in e and "'format'" in e for e in errs)


# ── unknown top-level fields: warning, not error ──

@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_unknown_field_warns_not_errors(name):
    data = copy.deepcopy(FIXTURES[name])
    data["colour_scheme"] = "mauve"
    assert validation.validate(data) == []
    assert validation.collect_warnings(data) == ["unknown field 'colour_scheme' (ignored)"]


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_known_fields_produce_no_warnings(name):
    assert validation.collect_warnings(copy.deepcopy(FIXTURES[name])) == []


def test_every_known_field_is_accepted_without_warning():
    data = {"title": "T", "byline": "b", "body": "x", "back": "home", "refresh_sec": 900}
    assert validation.validate(data) == []
    assert validation.collect_warnings(data) == []
