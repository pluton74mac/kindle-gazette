"""Entrypoint: start the HTTP thread, ensure a home view exists, then run the MCP
stdio server. This blocks on stdio — an agent framework manages this as a subprocess
so nothing here needs its own daemonization.
"""
from __future__ import annotations

from . import browser, http_server, store
from .server import build_home_view, mcp


def main() -> None:
    # Returns None when a sibling kindle-gazette process already serves the HTTP
    # port — this copy then runs MCP-only against the shared data dir.
    http_server.start()
    if store.get_view_meta("home") is None:
        build_home_view()
    try:
        mcp.run(transport="stdio")
    finally:
        # Close Chromium while the render worker can still be reached — the
        # atexit fallback fires too late for a polite close (see browser.py).
        browser.shutdown()


if __name__ == "__main__":
    main()
