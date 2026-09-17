"""Shared test setup for kindle-gazette.

config.py reads its environment at import time, so KINDLE_GAZETTE_DATA_DIR must
be set BEFORE anything imports kindle_gazette. That's why the os.environ call
sits at module top, ahead of every kindle_gazette import in the whole suite
(pytest imports conftest.py before collecting any test module).
"""
import os
import tempfile

os.environ.setdefault(
    "KINDLE_GAZETTE_DATA_DIR",
    tempfile.mkdtemp(prefix="kindle-gazette-tests-"),
)

import glob
import shutil

import pytest

from kindle_gazette import config, http_server

import _util


def _chromium_resolvable() -> bool:
    """Best-effort mirror of browser._chromium_candidates() plus Playwright's
    default install location — enough to decide whether the browser tier can
    run at all without actually launching anything."""
    candidates = []
    env_path = os.environ.get("KINDLE_GAZETTE_CHROMIUM")
    if env_path:
        candidates.append(env_path)
    candidates.append("/opt/pw-browsers/chromium")
    for base in (
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH"),
        os.path.expanduser("~/.cache/ms-playwright"),
        os.path.expanduser("~/Library/Caches/ms-playwright"),  # macOS default
    ):
        if base:
            candidates.extend(glob.glob(f"{base}/chromium-*/chrome-linux/chrome"))
            candidates.extend(glob.glob(f"{base}/chromium-*/chrome-mac*/*.app/Contents/MacOS/*"))
    if shutil.which("chromium") or shutil.which("chromium-browser"):
        return True
    return any(os.path.exists(c) for c in candidates)


def pytest_collection_modifyitems(items):
    if _chromium_resolvable():
        return
    skip = pytest.mark.skip(reason="no Chromium resolvable (playwright default or fallbacks)")
    for item in items:
        if "browser" in item.keywords:
            item.add_marker(skip)


def pytest_sessionfinish(session, exitstatus):
    """Close the singleton Chromium while the executor can still accept work.

    browser.shutdown() is also registered atexit, but by interpreter-exit time
    concurrent.futures has already flagged its executors as shut down, so that
    late call raises (harmlessly, as 'Exception ignored'). Closing here keeps
    the suite's output clean; the atexit call then no-ops."""
    from kindle_gazette import browser

    browser.shutdown()


@pytest.fixture(autouse=True)
def _clean_data_dir():
    """Wipe the (session-wide) data dir before every test so registry/home-card
    state never leaks between tests."""
    data = config.DATA_DIR
    for entry in data.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    (data / "images").mkdir()
    yield


@pytest.fixture
def gazette_server(monkeypatch):
    """A real ThreadingHTTPServer on an ephemeral localhost port. Yields the port."""
    port = _util.free_port()
    monkeypatch.setattr(config, "HTTP_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "HTTP_PORT", port)
    server = http_server.start()
    assert server is not None, "server failed to start on a fresh ephemeral port"
    yield port
    server.shutdown()
    server.server_close()
