"""Headless-Chromium render worker (Playwright sync API).

Sync Playwright objects are not thread-safe and refuse to run on an asyncio
loop thread — but FastMCP tool calls can arrive from anywhere, including the
event loop. So this module owns a single-thread executor and funnels *every*
Playwright call through it: the browser, page, and playwright handle are all
created lazily inside that one worker thread and only ever touched there.
Callers block on `.result()`, which also serializes concurrent renders.
"""
from __future__ import annotations

import atexit
import glob
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from PIL import Image

from . import config

# Extracts tap regions from every visible [data-action] element. Kept as one
# shared snippet so single-page and paged renders can't drift apart.
#
# Rects are CLIPPED to the viewport, never moved into it: a paginated edition
# keeps its other pages in the DOM, just translated off to the side, and a
# tappable element there (a link_list row on page 3) must contribute no tap to
# page 1. An element with no on-screen area left after clipping is dropped.
_EXTRACT_TAPS_JS = """
() => {
    const W = window.innerWidth, H = window.innerHeight;
    const taps = [];
    for (const el of document.querySelectorAll('[data-action]')) {
        if (el.hidden) continue;
        if (getComputedStyle(el).display === 'none') continue;
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const x = Math.max(0, Math.round(r.left));
        const y = Math.max(0, Math.round(r.top));
        const w = Math.min(W, Math.round(r.right)) - x;
        const h = Math.min(H, Math.round(r.bottom)) - y;
        if (w <= 0 || h <= 0) continue;
        taps.push({
            x, y, w, h,
            action: el.dataset.action,
            target: el.dataset.target || "",
            label: el.dataset.label || (el.textContent || "").trim().slice(0, 40),
        });
    }
    return taps;
}
"""

_CHROMIUM_FALLBACKS_ENV = "KINDLE_GAZETTE_CHROMIUM"

_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None

# Which executable actually launched ("<playwright default>" or a fallback
# path) — diagnostic only, for logs and tests.
launched_with: str | None = None

# Worker-thread-only state; never touched from any other thread.
_playwright = None
_browser = None
_page = None


def _chromium_candidates() -> list[str]:
    """Fallback executables to try when Playwright's own bundled launch fails
    (e.g. the browsers were installed to a shared system path, or only a
    distro chromium exists)."""
    candidates = []
    env_path = os.environ.get(_CHROMIUM_FALLBACKS_ENV)
    if env_path:
        candidates.append(env_path)
    candidates.append("/opt/pw-browsers/chromium")
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if browsers_path:
        candidates.extend(sorted(glob.glob(f"{browsers_path}/chromium-*/chrome-linux/chrome")))
    which = shutil.which("chromium") or shutil.which("chromium-browser")
    if which:
        candidates.append(which)
    return candidates


def _launch_browser(p):
    global launched_with
    try:
        result = p.chromium.launch(headless=True)
        launched_with = "<playwright default>"
        return result
    except Exception as default_exc:
        attempted = ["<playwright default>"]
        for path in _chromium_candidates():
            attempted.append(path)
            if not os.path.exists(path):
                continue
            try:
                result = p.chromium.launch(headless=True, executable_path=path)
                launched_with = path
                return result
            except Exception:
                continue
        raise RuntimeError(
            "Could not launch Chromium. Attempted: " + ", ".join(attempted)
            + f". Default launch error: {default_exc}. "
            f"Install browsers (`playwright install chromium`) or set ${_CHROMIUM_FALLBACKS_ENV} "
            "to a Chromium executable."
        ) from default_exc


def _ensure_page():
    """Lazy init — runs in the worker thread only."""
    global _playwright, _browser, _page
    if _page is not None:
        return _page
    from playwright.sync_api import sync_playwright

    _playwright = sync_playwright().start()
    _browser = _launch_browser(_playwright)
    _page = _browser.new_page(
        viewport={"width": config.SCREEN_WIDTH, "height": config.SCREEN_HEIGHT},
        device_scale_factor=1,
    )
    return _page


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gazette-render")
        return _executor


# The panel shows only 16 gray levels (4-bit E Ink Carta) and truncates anything
# else — verified on-glass: undithered ramps band into 16 steps, while
# Floyd-Steinberg dithered ones read as smooth at 300ppi. Diffusing to exactly the
# panel's levels here means the device displays our pixels losslessly; flat tones
# and text are already palette-exact so only continuous gradients gain dot texture.
def _panel_palette() -> Image.Image:
    pal = Image.new("P", (1, 1))
    table: list[int] = []
    for i in range(16):
        table += [i * 17] * 3
    pal.putpalette(table + [0, 0, 0] * 240)
    return pal


_PANEL_PALETTE = _panel_palette()


def _to_grayscale_png(png_bytes: bytes) -> bytes:
    """Chromium screenshots are RGB; the Kindle protocol requires PIL mode "L",
    dithered to the panel's 16 levels so gradients survive the 4-bit glass."""
    img = (
        Image.open(BytesIO(png_bytes))
        .convert("RGB")
        .quantize(palette=_PANEL_PALETTE, dither=Image.Dither.FLOYDSTEINBERG)
        .convert("L")
    )
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _screenshot(page) -> bytes:
    raw = page.screenshot(
        clip={"x": 0, "y": 0, "width": config.SCREEN_WIDTH, "height": config.SCREEN_HEIGHT}
    )
    return _to_grayscale_png(raw)


def _render_page_worker(html: str) -> tuple[bytes, list[dict]]:
    page = _ensure_page()
    page.set_content(html)
    taps = page.evaluate(_EXTRACT_TAPS_JS)
    return _screenshot(page), taps


def _render_paged_worker(html: str) -> tuple[list[tuple[bytes, list[dict]]], int]:
    page = _ensure_page()
    page.set_content(html)
    count = int(page.evaluate("() => window.__gazettePageCount()"))
    pages: list[tuple[bytes, list[dict]]] = []
    for i in range(count):
        page.evaluate("(i) => window.__gazetteShowPage(i)", i)
        taps = page.evaluate(_EXTRACT_TAPS_JS)
        pages.append((_screenshot(page), taps))
    return pages, count


def render_page(html: str) -> tuple[bytes, list[dict]]:
    """Render one self-contained HTML document to (grayscale PNG bytes, taps)."""
    return _get_executor().submit(_render_page_worker, html).result()


def render_paged(html: str) -> tuple[list[tuple[bytes, list[dict]]], int]:
    """Render a paginated document (the article template): the page defines
    __gazettePageCount / __gazetteShowPage; each page is screenshotted with
    its own tap map. Returns (per-page results, page count)."""
    return _get_executor().submit(_render_paged_worker, html).result()


def _shutdown_worker() -> None:
    global _playwright, _browser, _page
    if _page is not None:
        try:
            _browser.close()
        except Exception:
            pass
        try:
            _playwright.stop()
        except Exception:
            pass
    _playwright = _browser = _page = None


def shutdown() -> None:
    """Close the browser and executor. Safe to call more than once."""
    global _executor
    with _lock:
        executor = _executor
        _executor = None
    if executor is not None:
        try:
            executor.submit(_shutdown_worker).result()
        except RuntimeError:
            # Interpreter teardown: concurrent.futures flags executors as shut
            # down before atexit callbacks run, so the worker can no longer be
            # reached. Chromium is a child process and dies with us — the only
            # loss is the polite close. Call shutdown() before exiting (as
            # __main__ does) to get the clean path.
            pass
        executor.shutdown(wait=True)


atexit.register(shutdown)
