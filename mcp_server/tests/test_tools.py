"""The MCP tool surface (server.py): publish_edition and delete_edition. Pure
rejection paths run anywhere; the ones that actually render carry the `browser`
marker."""
import copy
import re
import time

import pytest

from kindle_gazette import config, server, store

import _util

VALID = _util.EDITION
RESULT_KEYS = {"success", "path", "image_url", "rendered_at", "error"}
CARD = {"title": "Readiness", "summary": ["74/100", "rest day"]}


def _publish(path=None, edition=None, card=None):
    result = server.publish_edition(path or "sports/readiness",
                                    copy.deepcopy(edition or VALID),
                                    copy.deepcopy(card) if card else None)
    assert result["success"] is True, result["error"]
    return result


# ── publish_edition: rejections (no rendering, run anywhere) ──

def test_publish_rejects_reserved_home():
    result = server.publish_edition("home", copy.deepcopy(VALID))
    assert result["success"] is False
    assert "reserved" in result["error"]
    assert "card" in result["error"]  # points at how to reach home instead
    assert set(result) == RESULT_KEYS


def test_publish_rejects_system_namespace():
    result = server.publish_edition("system/x", copy.deepcopy(VALID))
    assert result["success"] is False
    assert "reserved" in result["error"]


@pytest.mark.parametrize("empty", ["", "/", "///"])
def test_publish_rejects_empty_path(empty):
    result = server.publish_edition(empty, copy.deepcopy(VALID))
    assert result["success"] is False
    assert result["error"] == "path must not be empty"


def test_publish_rejects_page_segment_path():
    result = server.publish_edition("foo/p2", copy.deepcopy(VALID))
    assert result["success"] is False
    assert "reserved" in result["error"]
    # Page-like segments are reserved only in last position.
    result = server.publish_edition("p2/foo", {"title": "T"})
    assert "reserved" not in result["error"]


def test_publish_validation_errors_are_numbered_with_a_shape_example():
    result = server.publish_edition("ops/web", {"body": "no title"})
    assert result["success"] is False
    assert re.search(r"1\. ", result["error"])
    assert "'title'" in result["error"]
    assert "expected shape example" in result["error"]
    assert '"title": "Weekly Digest"' in result["error"]  # a concrete, valid edition
    assert set(result) == RESULT_KEYS


def test_publish_figure_errors_carry_that_figures_example():
    result = server.publish_edition("ops/web", {"title": "T", "sections": [
        {"figure": {"kind": "link_list", "links": [{"text": "A"}]}},
    ]})
    assert result["success"] is False
    assert "sections[0]: links[0]" in result["error"]
    assert '"kind": "link_list"' in result["error"]


@pytest.mark.parametrize("card, expected", [
    ({"summary": ["x"]}, "'title'"),
    ({"title": "", "summary": []}, "'title'"),
    ({"title": "T"}, "'summary'"),
    ({"title": "T", "summary": "one line"}, "'summary' must be a list"),
    ({"title": "T", "summary": [1]}, "summary[0]"),
    ({"title": "T", "summary": [], "nav_target": 5}, "'nav_target'"),
    ({"title": "T", "summary": [], "slot": 3}, "unknown field 'slot'"),
])
def test_publish_rejects_a_malformed_card(card, expected):
    result = server.publish_edition("sports/readiness", copy.deepcopy(VALID), card)
    assert result["success"] is False
    assert expected in result["error"]
    assert "expected shape example" in result["error"]
    # Nothing was rendered or registered on a card failure.
    assert store.get_view_meta("sports/readiness") is None
    assert store.get_home_cards() == {}


def test_get_status_keys():
    status = server.get_status()
    assert set(status) == {
        "port", "data_dir", "screen", "views_count", "agents",
        "home_max_cards", "uptime_sec",
    }
    assert status["screen"] == {"width": config.SCREEN_WIDTH, "height": config.SCREEN_HEIGHT}
    assert status["data_dir"] == str(config.DATA_DIR)
    assert status["views_count"] == 0
    assert status["agents"] == []
    assert isinstance(status["uptime_sec"], float)


def test_list_views_shape():
    assert server.list_views() == []
    store.save_view("ops/web", _util.make_meta("ops/web", [], title="Web"), b"png")
    views = server.list_views()
    assert len(views) == 1
    assert set(views[0]) == {"path", "type", "title", "updated_at", "agent_id"}
    assert views[0]["path"] == "ops/web"
    assert views[0]["type"] == "edition"
    assert views[0]["agent_id"] == "ops"


# ── publish_edition: success paths (render → browser tier) ──

@pytest.mark.browser
def test_publish_success_shape():
    result = server.publish_edition("ops/web", copy.deepcopy(VALID))
    # No "warnings" and no "card" key unless there is something to report.
    assert set(result) == RESULT_KEYS
    assert result["success"] is True
    assert result["path"] == "ops/web"
    assert result["image_url"] == "/images/ops_web.png"
    assert result["error"] is None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", result["rendered_at"])
    # A plain publish touches neither the home cards nor the generated views.
    assert store.get_home_cards() == {}
    assert store.get_view_meta("home") is None


@pytest.mark.browser
def test_publish_reports_unknown_field_warnings():
    data = copy.deepcopy(VALID)
    data["colour_scheme"] = "mauve"
    result = server.publish_edition("ops/web", data)
    assert result["success"] is True
    assert result["warnings"] == ["unknown field 'colour_scheme' (ignored)"]


@pytest.mark.browser
def test_publish_stores_the_edition_for_rerender():
    _publish("ops/web")
    assert store.get_view_data("ops/web") == VALID
    assert "ops/web" in store.list_data_paths()


@pytest.mark.browser
def test_publish_with_card_rebuilds_home_and_defaults_nav_target():
    before = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result = _publish("sports/readiness", card=CARD)
    assert result["card"] == {"agent_id": "sports", "slot": 0}

    # nav_target defaults to the published path.
    stored = store.get_home_cards()["sports"]
    assert stored["nav_target"] == "sports/readiness"
    assert stored["title"] == "Readiness"
    assert stored["summary"] == ["74/100", "rest day"]

    home = store.get_view_meta("home")
    assert home is not None
    assert any(t["action"] == "navigate" and t["target"] == "sports/readiness"
               for t in home["taps"])

    rows = {r["path"]: r for r in store.list_views()}
    assert rows["home"]["updated_at"] >= before  # ISO-8601 sorts chronologically
    assert rows["home"]["type"] == "home"
    # The system/agents overview is (re)built alongside home, as an edition.
    assert rows["system/agents"]["type"] == "edition"
    agents = store.get_view_meta("system/agents")
    assert any(t["action"] == "navigate" and t["target"] == "sports/readiness"
               for t in agents["taps"])


@pytest.mark.browser
def test_card_nav_target_may_point_elsewhere():
    _publish("news/dispatch", card=dict(CARD, nav_target="news/dispatch/p2"))
    assert store.get_home_cards()["news"]["nav_target"] == "news/dispatch/p2"


@pytest.mark.browser
def test_agent_id_comes_from_the_first_path_segment():
    _publish("life/health/sleep/detail", card=CARD)
    cards = store.get_home_cards()
    assert set(cards) == {"life"}
    assert cards["life"]["nav_target"] == "life/health/sleep/detail"


@pytest.mark.browser
def test_single_segment_path_is_its_own_agent():
    result = _publish("dispatch", card=CARD)
    assert result["card"]["agent_id"] == "dispatch"
    assert set(store.get_home_cards()) == {"dispatch"}


@pytest.mark.browser
def test_republishing_keeps_the_agents_slot():
    assert _publish("a/one", card=CARD)["card"]["slot"] == 0
    assert _publish("b/one", card=CARD)["card"]["slot"] == 1
    assert _publish("a/two", card=dict(CARD, title="A v2"))["card"]["slot"] == 0
    assert store.get_home_cards()["a"]["nav_target"] == "a/two"


# ── delete_edition ──

@pytest.mark.parametrize("path, expected", [
    ("home", "reserved"),
    ("system/agents", "reserved"),
    ("news/digest/p2", "reserved"),   # pages die with their base edition, not alone
    ("", "path must not be empty"),
])
def test_delete_refuses_reserved_paths(path, expected):
    result = server.delete_edition(path)
    assert result["success"] is False
    assert result["deleted"] == []
    assert expected in result["error"]


def test_delete_missing_view_reports_it():
    result = server.delete_edition("ops/nope")
    assert result == {"success": False, "deleted": [], "error": "no view at 'ops/nope'"}


@pytest.mark.browser
def test_delete_removes_the_edition_and_its_continuation_pages():
    para = ("The quick brown fox jumps over the lazy dog while the market watches "
            "carefully and the sensors keep logging every reading. ") * 3
    body = "\n\n".join(f"Paragraph {i}. {para}" for i in range(40))
    _publish("news/digest", {"title": "Long Read", "body": body})
    assert store.get_view_meta("news/digest/p2") is not None

    result = server.delete_edition("news/digest")
    assert result["success"] is True
    assert result["error"] is None
    assert "warning" not in result
    assert result["deleted"][0] == "news/digest"
    assert "news/digest/p2" in result["deleted"]

    for path in result["deleted"]:
        name = store.path_to_name(path)
        assert store.get_view_meta(path) is None
        assert store.get_view_data(path) is None
        assert not (config.DATA_DIR / "images" / f"{name}.png").exists()
    assert store.list_views() == []


@pytest.mark.browser
def test_delete_leaves_sibling_paths_alone():
    _publish("news/digest")
    _publish("news/digest-notes")
    _publish("news/other")

    result = server.delete_edition("news/digest")
    assert result["deleted"] == ["news/digest"]
    assert {r["path"] for r in store.list_views()} == {"news/digest-notes", "news/other"}


@pytest.mark.browser
def test_delete_warns_about_a_dangling_home_card():
    _publish("sports/readiness", card=CARD)
    result = server.delete_edition("sports/readiness")
    assert result["success"] is True
    assert "sports" in result["warning"]
    assert "sports/readiness" in result["warning"]
    # The card is left in place — deleting a view is not deregistering an agent.
    assert store.get_home_cards()["sports"]["nav_target"] == "sports/readiness"


@pytest.mark.browser
def test_delete_does_not_warn_for_an_unrelated_card():
    _publish("sports/readiness", card=CARD)
    _publish("sports/detail")
    result = server.delete_edition("sports/detail")
    assert result["success"] is True
    assert "warning" not in result
