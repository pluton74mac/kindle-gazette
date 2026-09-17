"""store.py: path mapping, registry, home-card slots, traversal defenses,
atomic writes. No browser involved."""
import json

import pytest

from kindle_gazette import config, store

import _util


# ── path_to_name ──

def test_path_to_name_mapping():
    assert store.path_to_name("sports/readiness") == "sports_readiness"
    assert store.path_to_name("home") == "home"
    assert store.path_to_name("/ops/web/") == "ops_web"
    assert store.path_to_name("a/b/c") == "a_b_c"
    # Empty path maps to the home view by design.
    assert store.path_to_name("") == "home"
    assert store.path_to_name("/") == "home"


@pytest.mark.parametrize("bad", ["a b", "café/x", "a|b", "x;rm -rf", "a\nb", "sports/read?iness"])
def test_path_to_name_rejects_invalid(bad):
    with pytest.raises(ValueError):
        store.path_to_name(bad)


def test_agent_id_for_path():
    assert store.agent_id_for_path("sports/readiness") == "sports"
    assert store.agent_id_for_path("home") is None


# ── home card slots ──

def test_home_card_slots_register_in_order():
    assert store.upsert_home_card("a", "A", ["s"], "a/main")["slot"] == 0
    assert store.upsert_home_card("b", "B", ["s"], "b/main")["slot"] == 1
    assert store.upsert_home_card("c", "C", ["s"], "c/main")["slot"] == 2


def test_home_card_reregister_keeps_slot():
    store.upsert_home_card("a", "A", ["s"], "a/main")
    store.upsert_home_card("b", "B", ["s"], "b/main")
    store.upsert_home_card("c", "C", ["s"], "c/main")
    card = store.upsert_home_card("b", "B v2", ["fresh"], "b/other")
    assert card["slot"] == 1
    assert card["title"] == "B v2"
    assert store.get_home_cards()["b"]["slot"] == 1


def test_new_agent_gets_lowest_free_slot():
    store.upsert_home_card("a", "A", ["s"], "a/main")
    store.upsert_home_card("b", "B", ["s"], "b/main")
    store.upsert_home_card("c", "C", ["s"], "c/main")
    # There is no card-delete API; simulate agent b disappearing by rewriting
    # the store file directly, then check the freed slot is reused.
    cards = store.get_home_cards()
    del cards["b"]
    store._write_json_atomic(store._HOME_CARDS_PATH, cards)
    assert store.upsert_home_card("d", "D", ["s"], "d/main")["slot"] == 1


# ── image path traversal ──

@pytest.mark.parametrize("bad", [
    "../../etc/passwd",
    "/etc/passwd",
    "..%2f..%2fetc%2fpasswd",
    "%2e%2e/%2e%2e/etc/passwd",
    "images/../../secret.png",
])
def test_get_image_path_rejects_traversal(bad):
    assert store.get_image_path(bad) is None


def test_get_image_path_containment_and_hit():
    # ".." passes the character whitelist but must fail the containment check.
    assert store.get_image_path("..") is None
    # Non-existent but well-formed name: None, not an exception.
    assert store.get_image_path("nope.png") is None
    meta = _util.make_meta("ops/web", taps=[])
    store.save_view("ops/web", meta, b"\x89PNG-fake")
    resolved = store.get_image_path("ops_web.png")
    assert resolved is not None
    assert resolved.read_bytes() == b"\x89PNG-fake"
    assert resolved.parent == (config.DATA_DIR / "images").resolve()


# ── save_view / get_view_meta / delete_view ──

def test_save_view_get_meta_roundtrip_strips_view_type():
    taps = [{"x": 0, "y": 0, "w": 100, "h": 50, "action": "refresh", "target": "", "label": "Masthead"}]
    meta = _util.make_meta("ops/web", taps, title="Web")
    store.save_view("ops/web", meta, b"png", raw_data={"title": "Web", "body": "text"})

    got = store.get_view_meta("ops/web")
    assert got is not None
    assert "_view_type" not in got
    expected = dict(meta)
    expected.pop("_view_type")
    assert got == expected

    # Registry row picked up the type/title/agent.
    rows = {r["path"]: r for r in store.list_views()}
    assert rows["ops/web"]["type"] == "edition"
    assert rows["ops/web"]["title"] == "Web"
    assert rows["ops/web"]["agent_id"] == "ops"

    assert store.get_view_data("ops/web") == {"title": "Web", "body": "text"}


def test_get_view_meta_missing():
    assert store.get_view_meta("no/such") is None


def test_delete_view_removes_everything():
    meta = _util.make_meta("ops/web", taps=[])
    store.save_view("ops/web", meta, b"png", raw_data={"title": "Web", "body": "text"})
    name = "ops_web"
    assert (config.DATA_DIR / "images" / f"{name}.png").exists()
    assert (config.DATA_DIR / f"{name}.json").exists()
    assert (config.DATA_DIR / f"{name}.data.json").exists()

    assert store.delete_view("ops/web") is True
    assert not (config.DATA_DIR / "images" / f"{name}.png").exists()
    assert not (config.DATA_DIR / f"{name}.json").exists()
    assert not (config.DATA_DIR / f"{name}.data.json").exists()
    assert store.get_view_meta("ops/web") is None
    assert all(r["path"] != "ops/web" for r in store.list_views())
    # Second delete: nothing left to remove.
    assert store.delete_view("ops/web") is False


def test_atomic_write_leaves_no_tmp_files():
    meta = _util.make_meta("ops/web", taps=[])
    store.save_view("ops/web", meta, b"png-bytes", raw_data={"title": "Web", "body": "text"})

    leftovers = list(config.DATA_DIR.rglob("*.tmp"))
    assert leftovers == []

    # Written JSON reads back identically (and is the pretty-printed format).
    raw = (config.DATA_DIR / "ops_web.json").read_text()
    assert json.loads(raw) == meta
    assert raw.count("\n") > 5  # indent=2, not compact
