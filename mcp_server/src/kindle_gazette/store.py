"""Disk persistence: view registry + home-card slots.

Everything here is a flat JSON file under config.DATA_DIR, written atomically
(tmp file + os.replace) so a crash mid-write can't corrupt state the Kindle or
a restarted MCP subprocess reads next. This is deliberately simple — no
database, no locking beyond what atomic rename already gives a single-process
server. Disk is the source of truth: the Kindle fetches whatever's on disk
regardless of whether an agent or the MCP subprocess is currently alive.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from . import config

_LOCK = threading.Lock()
_REGISTRY_PATH = config.DATA_DIR / "registry.json"
_HOME_CARDS_PATH = config.DATA_DIR / "home_cards.json"
_IMAGES_DIR = config.DATA_DIR / "images"

SAFE_NAME = re.compile(r"^[a-zA-Z0-9_\-.]+$")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _write_json_atomic(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def path_to_name(path: str) -> str:
    """Turn a view path like 'sports/readiness' into a filesystem-safe basename."""
    name = path.strip("/").replace("/", "_") or "home"
    if not SAFE_NAME.match(name):
        raise ValueError(f"Invalid view path: {path!r}")
    return name


def agent_id_for_path(path: str) -> str | None:
    """First path segment is the owning agent's namespace (sports/readiness -> sports)."""
    parts = path.strip("/").split("/")
    if len(parts) < 2:
        return None
    return parts[0]


# ── View registry + rendered output ──

def save_view(path: str, meta: dict, png_bytes: bytes, raw_data: dict | None = None) -> str:
    """Persist a rendered view's PNG + metadata, update the registry. Returns image name.

    `raw_data` is the pre-render payload the view was built from — kept beside
    the metadata so the `rerender` tool can rebuild every view after a
    template/theme edit without any agent re-pushing. Continuation pages of a
    paginated article pass None: they're derived from the base view's data."""
    name = path_to_name(path)
    with _LOCK:
        img_path = _IMAGES_DIR / f"{name}.png"
        tmp = img_path.with_suffix(".png.tmp")
        tmp.write_bytes(png_bytes)
        tmp.replace(img_path)

        meta_path = config.DATA_DIR / f"{name}.json"
        _write_json_atomic(meta_path, meta)

        if raw_data is not None:
            _write_json_atomic(config.DATA_DIR / f"{name}.data.json", raw_data)

        registry = _read_json(_REGISTRY_PATH, {})
        registry[path] = {
            "type": meta.get("_view_type"),
            "title": meta.get("title", path),
            "updated_at": _now(),
            "agent_id": agent_id_for_path(path),
        }
        _write_json_atomic(_REGISTRY_PATH, registry)
    return name


def get_view_data(path: str) -> dict | None:
    """The raw payload `save_view` persisted for this view, if any."""
    name = path_to_name(path)
    with _LOCK:
        return _read_json(config.DATA_DIR / f"{name}.data.json", None)


def list_data_paths() -> list[str]:
    """Registered view paths that have persisted raw data (i.e. re-renderable
    base views — article continuation pages never store data)."""
    with _LOCK:
        registry = _read_json(_REGISTRY_PATH, {})
        return sorted(
            path for path in registry
            if (config.DATA_DIR / f"{path_to_name(path)}.data.json").exists()
        )


def delete_view(path: str) -> bool:
    """Remove a view's rendered PNG, metadata, raw data, and registry row.
    Used when a re-rendered article shrinks and leaves stale /pN pages behind."""
    name = path_to_name(path)
    with _LOCK:
        removed = False
        for file in (
            _IMAGES_DIR / f"{name}.png",
            config.DATA_DIR / f"{name}.json",
            config.DATA_DIR / f"{name}.data.json",
        ):
            if file.exists():
                file.unlink()
                removed = True
        registry = _read_json(_REGISTRY_PATH, {})
        if path in registry:
            del registry[path]
            _write_json_atomic(_REGISTRY_PATH, registry)
            removed = True
    return removed


def get_view_meta(path: str) -> dict | None:
    name = path_to_name(path)
    meta_path = config.DATA_DIR / f"{name}.json"
    with _LOCK:
        data = _read_json(meta_path, None)
    if data is None:
        return None
    # Internal-only field, not part of the wire protocol.
    data = dict(data)
    data.pop("_view_type", None)
    return data


def get_image_path(name: str) -> Path | None:
    if not SAFE_NAME.match(name):
        return None
    candidate = (_IMAGES_DIR / name).resolve()
    if candidate.parent != _IMAGES_DIR.resolve() or not candidate.exists():
        return None
    return candidate


def list_views() -> list[dict]:
    with _LOCK:
        registry = _read_json(_REGISTRY_PATH, {})
    return [{"path": p, **v} for p, v in sorted(registry.items())]


def registry_count() -> int:
    with _LOCK:
        return len(_read_json(_REGISTRY_PATH, {}))


# ── Home card slots ──

def upsert_home_card(agent_id: str, title: str, summary: list[str], nav_target: str) -> dict:
    """Update (or create) an agent's home card. Slot assignment is stable: an agent
    keeps the slot it was first given, in first-registration order, even as other
    agents come and go."""
    with _LOCK:
        cards = _read_json(_HOME_CARDS_PATH, {})
        existing = cards.get(agent_id)
        slot = existing["slot"] if existing else _next_slot(cards)
        cards[agent_id] = {
            "title": title,
            "summary": summary,
            "nav_target": nav_target,
            "slot": slot,
            "updated_at": _now(),
        }
        _write_json_atomic(_HOME_CARDS_PATH, cards)
    return cards[agent_id]


def _next_slot(cards: dict) -> int:
    used = {c["slot"] for c in cards.values()}
    slot = 0
    while slot in used:
        slot += 1
    return slot


def get_home_cards() -> dict[str, dict]:
    with _LOCK:
        return _read_json(_HOME_CARDS_PATH, {})
