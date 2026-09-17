"""MCP tool surface: publish_edition, delete_edition, rerender, get_status, list_views.

Agents publish editions, not layouts — this module is the only place that turns
their calls into rendered PNGs on disk. `home` and the `system/` namespace are
reserved: home is built exclusively from the `card` argument of
`publish_edition()`, and `system/agents` is an auto-generated overview (itself
an edition) so a dashboard with more agents than fit on the home grid stays
fully browsable.

Paginated editions are the one place a single `publish_edition` call produces
multiple views: page 1 lives at the published path, page k at `path/p{k}` —
which is why `p<digits>` is a reserved final path segment.
"""
import re
import time

from mcp.server.fastmcp import FastMCP

from . import config, renderers, store, validation

mcp = FastMCP("kindle-gazette")

RESERVED_PATHS = {"home"}
RESERVED_NAMESPACES = {"system"}
_PAGE_SEGMENT = re.compile(r"^p\d+$")

_START_TIME = time.time()


def _save_pages(path: str, view_type: str, data: dict, result: renderers.RenderResult) -> dict:
    """Persist every rendered page (one, except for paginated editions) and
    drop stale continuation pages from a previous, longer render."""
    title = data.get("title", path)
    first_meta: dict | None = None
    for i, (png_bytes, taps) in enumerate(result.pages):
        page_path = path if i == 0 else f"{path}/p{i + 1}"
        meta = {
            "version": 1,
            "title": title if i == 0 else f"{title} (p.{i + 1})",
            "image": f"/images/{store.path_to_name(page_path)}.png",
            "taps": taps,
            "back": result.back,
            "refresh_sec": result.refresh_sec,
            "error": None,
            "cache": {"key": page_path, "ttl_sec": result.refresh_sec},
            "_view_type": view_type,
            # Editions that didn't set `back` get it resolved at fetch time
            # (http_server): the agent's front page if one exists, else home.
            "_back_default": view_type == "edition" and data.get("back") is None,
        }
        store.save_view(page_path, meta, png_bytes, raw_data=data if i == 0 else None)
        if first_meta is None:
            first_meta = meta
    _cleanup_stale_pages(path, len(result.pages))
    return first_meta


def _cleanup_stale_pages(path: str, page_count: int) -> None:
    prefix = f"{path}/"
    for entry in store.list_views():
        suffix = entry["path"][len(prefix):] if entry["path"].startswith(prefix) else ""
        if _PAGE_SEGMENT.match(suffix) and int(suffix[1:]) > page_count:
            store.delete_view(entry["path"])


def render_and_save(path: str, data: dict) -> dict:
    """Render an edition payload to this path and persist every page."""
    return _save_pages(path, "edition", data, renderers.render_edition(data, path))


def build_home_view() -> dict:
    """Compose the home grid from all registered agents' cards. Reserved path —
    the one view that is not an edition, because a grid of tiles is navigation
    furniture rather than something an agent publishes."""
    cards_by_agent = store.get_home_cards()
    ordered = sorted(cards_by_agent.items(), key=lambda kv: kv[1]["slot"])
    overflow = len(ordered) > config.HOME_MAX_CARDS
    shown = ordered[: config.HOME_MAX_CARDS - 1] if overflow else ordered

    cards = [
        {"agent_id": agent_id, "title": c["title"], "summary": c["summary"], "nav_target": c["nav_target"]}
        for agent_id, c in shown
    ]
    if overflow:
        cards.append({
            "agent_id": "_more",
            "title": f"+{len(ordered) - len(shown)} more",
            "summary": ["Tap to see all connected agents"],
            "nav_target": "system/agents",
        })

    data = {"title": "Gazette", "cards": cards, "_home": True}
    return _save_pages("home", "home", data, renderers.render_home(data))


def build_agents_overview() -> dict:
    """Full list of every registered agent — reachable from home's overflow tile,
    and useful on its own once you have more than a handful of agents.

    It is an ordinary edition carrying one `link_list` figure, so the overview
    dogfoods the public schema and every row is tappable."""
    cards_by_agent = store.get_home_cards()
    ordered = sorted(cards_by_agent.items(), key=lambda kv: kv[1]["slot"])
    links = [
        {"text": c["title"], "nav_target": c["nav_target"], "note": c["updated_at"]}
        for _agent_id, c in ordered
    ]
    sections = [{"text": f"{len(ordered)} agent(s) connected."}]
    if links:
        sections.append({"figure": {"kind": "link_list", "links": links}})
    data = {"title": "Agents", "back": "home", "sections": sections}
    return render_and_save("system/agents", data)


def _fail(path: str, error: str) -> dict:
    return {"success": False, "path": path, "image_url": None, "rendered_at": None, "error": error}


def _check_path(path: str) -> str | None:
    """The reserved-path rules, shared by publish and delete. Returns an error
    message, or None if the path is usable."""
    if not path:
        return "path must not be empty"
    if path in RESERVED_PATHS or path.split("/")[0] in RESERVED_NAMESPACES:
        return (f"'{path}' is reserved: 'home' and the 'system/' namespace are built by the "
                "server. Use your own namespace — publish_edition's `card` argument is how "
                "you appear on home.")
    last = path.split("/")[-1]
    if _PAGE_SEGMENT.match(last):
        return (f"final path segment '{last}' is reserved: a paginated edition serves page N "
                f"at '<path>/pN', so it would collide. Rename the segment.")
    return None


def _validate_card(card: dict) -> list[str]:
    """The home card is a tiny fixed shape; same actionable-error style as the
    edition's own validation."""
    errors: list[str] = []
    if not isinstance(card, dict):
        return [f"'card' must be an object like "
                '{"title": "Readiness", "summary": ["74/100"], "nav_target"?: "<view path>"}, '
                f"got {type(card).__name__}"]
    title = card.get("title")
    if title is None:
        errors.append("card: missing required field 'title' (string)")
    elif not isinstance(title, str) or not title.strip():
        errors.append("card: 'title' must be a non-empty string")
    summary = card.get("summary")
    if summary is None:
        errors.append("card: missing required field 'summary' (list of strings, up to 4 lines)")
    elif not isinstance(summary, list):
        errors.append(f"card: 'summary' must be a list of strings, got {type(summary).__name__}")
    else:
        for i, line in enumerate(summary):
            if not isinstance(line, str):
                errors.append(f"card: summary[{i}] must be a string, got {type(line).__name__}")
    target = card.get("nav_target")
    if target is not None and (not isinstance(target, str) or not target.strip()):
        errors.append("card: 'nav_target' must be a non-empty string view path "
                      "(defaults to the path you are publishing)")
    for field in card:
        if field not in ("title", "summary", "nav_target"):
            errors.append(f"card: unknown field {field!r} (expected 'title', 'summary', 'nav_target')")
    return errors


@mcp.tool()
def publish_edition(path: str, edition: dict, card: dict | None = None) -> dict:
    """Publish an edition to a view path; the server renders it to PNG for the Kindle.

    `path` is namespaced by your agent, e.g. "sports/readiness" or "life/habits" —
    the first segment is your agent id. Publishing creates the edition; publishing
    again overwrites it.

    EDITION SHAPE (the only payload schema there is — no type field):
      {"title": str (required),
       "byline": str (optional, a small line under the title),
       "body": str      — plain text: blank-line-separated paragraphs, "## " lines
                          become headings,
       "sections": [{"heading"?: str, "text"?: str, "figure"?: {...}}]
                        — the structured alternative; a section may carry a heading,
                          paragraphs, and one figure (rendered after its text),
       "back": str      — view path the BACK button opens. Default: your agent's
                          front page — your home card's nav_target — when you have
                          one and this edition isn't it; otherwise "home". So in a
                          card -> index -> edition hierarchy, BACK walks back up
                          without you setting anything,
       "refresh_sec": number — auto-refresh interval on the device (default 0, off)}
    Exactly one of `body` or `sections` is required. Unknown top-level fields are
    accepted but reported back as warnings, so a typo never fails silently. On
    validation failure you get a numbered list of problems plus a minimal example
    of the expected shape.

    FIGURE KINDS (13; every kind also takes an optional "caption"):
    - {"kind": "sparkline", "values": [2+ nums], "baseline"?} — small trend line.
    - {"kind": "line_chart", "series": [{"label", "values"} x1-3], "x_labels"?,
      "baseline"?, "y_min"?, "y_max"?} — axes + legend; series drawn solid/dashed/
      dotted (equal values counts; they share one x axis).
    - {"kind": "bars", "bars": [{"label", "value", "max", "target"?}]} — labeled
      progress bars; "target" draws a tick on the track at target/max.
    - {"kind": "stacked_bar", "segments": [{"label", "value"}], "max"?} — one track
      split into segments with a legend ("max" defaults to the segment total).
    - {"kind": "heatmap", "rows": [[num|null, ...]], "row_labels"?, "col_labels"?,
      "scale_max"?} — grid of cells, darkness = value/scale_max; null = empty cell.
    - {"kind": "table", "columns": [...], "rows": [[cells]], "align"?} — header row
      + data rows; "align" is "left"/"right"/"center" per column.
    - {"kind": "stat_row", "stats": [{"value", "label", "unit"?, "delta"?,
      "direction"? ("up"|"down"|"flat")} x1-4]} — headline numbers with ▲/▼ deltas.
    - {"kind": "checklist", "items": [{"text", "state"? ("done"|"open"|"skipped")}]}.
    - {"kind": "callout", "text", "style"? ("alert"|"note"|"quote")} — text set
      apart: black band / bordered box / pull quote.
    - {"kind": "timeline", "events": [{"time"?, "text", "emphasis"?}]} — vertical
      timeline; "time" is a free-form label, "emphasis" bolds the event.
    - {"kind": "link_list", "links": [{"text", "nav_target", "note"?}]} — a list of
      tappable rows, each opening the view at its "nav_target" on the device; "note"
      is right-aligned metadata (a timestamp, a count). This is how one edition
      indexes others.
    - {"kind": "qr", "data": "<url or text, ≤1000 chars>"} — the server renders a
      scannable QR code; send the text, not pixels.
    - {"kind": "image", "data": "<base64 PNG/JPEG or data: URI>", "format"?} —
      photos and gradients are fine as-is; the server dithers for e-ink.

    PAGINATION: a long edition paginates automatically — page 1 at `path`, later
    pages at `path/p2`, `path/p3`... with PREV/NEXT buttons. Figures never split
    across a page boundary. A final path segment like "p2" is therefore reserved,
    as are "home" and the whole "system/" namespace.

    `card` (optional) puts you on the home grid: {"title": str, "summary": [str]
    (up to 4 short lines), "nav_target"?: str (defaults to `path`)}. Your agent id
    — the path's first segment — keeps one fixed home slot, assigned in
    first-registration order and stable across restarts; publishing with a card
    upserts that card and rebuilds home.

    The published edition is persisted, so the `rerender` tool can rebuild the PNG
    later (e.g. after a theme change) without you republishing.

    Returns {success, path, image_url, rendered_at, error}, plus "warnings" for
    unknown fields and "card": {agent_id, slot} when a card was given.
    """
    path = path.strip("/")
    path_error = _check_path(path)
    if path_error:
        return _fail(path, path_error)

    errors = validation.validate(edition)
    if errors:
        numbered = " ".join(f"{i}. {msg};" for i, msg in enumerate(errors, 1))
        return _fail(path, f"{numbered} expected shape example: "
                           f"{validation.failure_example(edition, errors)}")
    if card is not None:
        card_errors = _validate_card(card)
        if card_errors:
            numbered = " ".join(f"{i}. {msg};" for i, msg in enumerate(card_errors, 1))
            return _fail(path, f"{numbered} expected shape example: "
                               '{"title": "Readiness", "summary": ["74/100", "rest day"], '
                               '"nav_target": "sports/readiness"}')
    warnings = validation.collect_warnings(edition)

    try:
        meta = render_and_save(path, edition)
    except ValueError as exc:
        return _fail(path, str(exc))
    result = {"success": True, "path": path, "image_url": meta["image"],
              "rendered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "error": None}
    if warnings:
        result["warnings"] = warnings

    if card is not None:
        # The path's first segment owns the home slot; a single-segment path is
        # its own agent id ("dispatch" -> agent "dispatch").
        agent_id = store.agent_id_for_path(path) or path.split("/")[0]
        stored = store.upsert_home_card(
            agent_id,
            card["title"],
            list(card.get("summary") or []),
            (card.get("nav_target") or path).strip("/"),
        )
        build_home_view()
        build_agents_overview()
        result["card"] = {"agent_id": agent_id, "slot": stored["slot"]}
    return result


@mcp.tool()
def delete_edition(path: str) -> dict:
    """Remove an edition and every continuation page it paginated into.

    Deletes `path` plus its `path/p2`, `path/p3`... pages: the PNGs, the stored
    payload, and the registry rows. `home` and the `system/` namespace are
    reserved and cannot be deleted. Home cards are left alone — if some card
    still points at what you deleted, the result carries a warning naming it, so
    you can republish or move the card's target.

    Returns {success, deleted: [paths], error}.
    """
    path = path.strip("/")
    path_error = _check_path(path)
    if path_error:
        return {"success": False, "deleted": [], "error": path_error}

    prefix = f"{path}/"
    targets = [path]
    for entry in store.list_views():
        suffix = entry["path"][len(prefix):] if entry["path"].startswith(prefix) else ""
        if _PAGE_SEGMENT.match(suffix):
            targets.append(entry["path"])
    try:
        deleted = [target for target in sorted(targets) if store.delete_view(target)]
    except ValueError as exc:   # a path no view could ever have been saved under
        return {"success": False, "deleted": [], "error": str(exc)}
    if not deleted:
        return {"success": False, "deleted": [], "error": f"no view at '{path}'"}

    result = {"success": True, "deleted": deleted, "error": None}
    dangling = sorted(
        agent_id for agent_id, card in store.get_home_cards().items()
        if card.get("nav_target", "").strip("/") in set(deleted)
    )
    if dangling:
        result["warning"] = (
            f"home card(s) for {', '.join(dangling)} still point at '{path}', which no longer "
            "exists — republish it, or publish with a card whose nav_target is a live path."
        )
    return result


@mcp.tool()
def rerender(path: str | None = None) -> dict:
    """Re-render views from their stored data — no agent needs to re-push anything.

    Use this after the view templates or theme change (`templates/*.html`,
    `templates/themes/<name>/theme.css`, or a different KINDLE_GAZETTE_THEME),
    or if a PNG on disk is stale or missing. With `path`, re-renders just
    that view (a paginated edition re-renders all its pages). With no argument,
    re-renders every view that has stored data and rebuilds the generated `home`
    and `system/agents` views. Returns {success, rendered: [paths], errors: {path: msg}}.
    """
    rendered: list[str] = []
    errors: dict[str, str] = {}

    def attempt(target: str) -> None:
        try:
            if target == "home":
                build_home_view()
            elif target == "system/agents":
                build_agents_overview()
            else:
                data = store.get_view_data(target)
                if data is None:
                    raise ValueError(f"no stored data for view '{target}' — publish it again "
                                     "with publish_edition()")
                render_and_save(target, data)
            rendered.append(target)
        except Exception as exc:
            errors[target] = str(exc)

    if path is not None:
        attempt(path.strip("/"))
    else:
        for target in store.list_data_paths():
            if target != "home" and not target.startswith("system/"):
                attempt(target)
        attempt("home")
        attempt("system/agents")

    return {"success": not errors, "rendered": rendered, "errors": errors}


@mcp.tool()
def get_status() -> dict:
    """Server health: port, screen geometry, data dir, view/agent counts, uptime."""
    cards = store.get_home_cards()
    return {
        "port": config.HTTP_PORT,
        "data_dir": str(config.DATA_DIR),
        "screen": {"width": config.SCREEN_WIDTH, "height": config.SCREEN_HEIGHT},
        "views_count": store.registry_count(),
        "agents": sorted(cards.keys()),
        "home_max_cards": config.HOME_MAX_CARDS,
        "uptime_sec": round(time.time() - _START_TIME, 1),
    }


@mcp.tool()
def list_views() -> list:
    """Every registered view: path, type ("edition" or "home"), title, owning
    agent, and last-updated time."""
    return store.list_views()
