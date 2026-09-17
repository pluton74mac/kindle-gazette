"""Runtime configuration, entirely env-driven so the server isn't tied to one Kindle model.

Every setting has a sensible default for a Kindle Paperwhite 4 (the hardware this
project was built and tested against), but nothing in the rendering or serving code
assumes those numbers — override the env vars for a different screen size.
"""
from __future__ import annotations

import os
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Screen geometry. Defaults match Kindle Paperwhite 4 (1072x1448, portrait, 8-bit grayscale).
SCREEN_WIDTH = _env_int("KINDLE_GAZETTE_WIDTH", 1072)
SCREEN_HEIGHT = _env_int("KINDLE_GAZETTE_HEIGHT", 1448)

# HTTP server the Kindle's shell viewer polls.
HTTP_HOST = os.environ.get("KINDLE_GAZETTE_HOST", "0.0.0.0")
HTTP_PORT = _env_int("KINDLE_GAZETTE_PORT", 8888)

# Shared secret for the HTTP endpoints (empty = auth disabled). Pairs with the
# Kindle-side token file, sent on every request as the X-Gazette-Token header.
AUTH_TOKEN = os.environ.get("KINDLE_GAZETTE_TOKEN", "")

# Where rendered PNGs + view/registry metadata are persisted. Survives MCP subprocess
# restarts — the Kindle's offline cache and this on-disk store are what let the
# gazette keep serving the last-known state even when no agent is connected.
DATA_DIR = Path(os.environ.get("KINDLE_GAZETTE_DATA_DIR", str(Path.home() / ".kindle-gazette" / "data")))

# Which design style renders the pages. A theme is a directory under
# templates/themes/<name>/ holding a theme.css (design tokens) and, optionally,
# template overrides. Switching: set this env var, restart the server, call the
# `rerender` MCP tool — every persisted view is rebuilt in the new look.
THEME = os.environ.get("KINDLE_GAZETTE_THEME", "classic")

# Max number of agent cards shown directly on the home grid. Beyond this, the extra
# agents collapse into a single "more agents" tile that links to a full list view —
# keeps the fixed 2-column grid layout legible regardless of how many agents connect.
HOME_MAX_CARDS = _env_int("KINDLE_GAZETTE_HOME_MAX_CARDS", 8)

DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "images").mkdir(exist_ok=True)
