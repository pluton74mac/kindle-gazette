# kindle-gazette (MCP server)

The publishing side of the agent newspaper. MCP-capable agents publish
structured *editions* (`publish_edition`), claiming a card on the front page in
the same call; this server renders each page through a Jinja2 HTML
template in headless Chromium, extracts the tap map from the DOM, and persists
PNG + metadata to disk. The Kindle (see [`../kindle/`](../kindle/)) fetches
whatever is on disk when the reader wakes it — nothing is pushed to the device.

See the parent repo's [`README.md`](../README.md) for the full picture —
jailbreak, KUAL deployment, product framing. This README is the server's own
install/config/tool reference.

## Install

Requires Python 3.11+. Uses [uv](https://docs.astral.sh/uv/).

```sh
cd mcp_server
uv sync
uv run playwright install chromium   # headless browser used for rendering
```

If you already have a Chromium/Chrome build, skip the `playwright install`
step and point `KINDLE_GAZETTE_CHROMIUM` at its executable — when Playwright's
bundled browser is missing, the server falls back to that path, then to
`PLAYWRIGHT_BROWSERS_PATH`, then to any `chromium` on `$PATH`.

## Configuration

Everything is an environment variable, all optional:

| Variable | Default | Meaning |
|---|---|---|
| `KINDLE_GAZETTE_WIDTH` | `1072` | Screen width in px (default matches Kindle Paperwhite 4) |
| `KINDLE_GAZETTE_HEIGHT` | `1448` | Screen height in px |
| `KINDLE_GAZETTE_PORT` | `8888` | HTTP port the Kindle's viewer fetches from |
| `KINDLE_GAZETTE_HOST` | `0.0.0.0` | HTTP bind address |
| `KINDLE_GAZETTE_DATA_DIR` | `~/.kindle-gazette/data` | Where rendered PNGs + view metadata are persisted |
| `KINDLE_GAZETTE_HOME_MAX_CARDS` | `8` | Home-grid capacity; beyond it, extras collapse into a "+N more" tile |
| `KINDLE_GAZETTE_TOKEN` | *(empty = auth off)* | Shared secret for the HTTP endpoints; pairs with the Kindle-side token file (see [Auth](#auth-optional)) |
| `KINDLE_GAZETTE_CHROMIUM` | *(unset)* | Path to a Chromium executable, used when Playwright's bundled browser isn't installed |

If your Kindle isn't a Paperwhite 4, set `KINDLE_GAZETTE_WIDTH`/`HEIGHT` to its
panel resolution — nothing else in the server assumes PW4 hardware.

## Running

```sh
uv run kindle-gazette
```

This starts the HTTP server (background thread) and the MCP stdio server
(foreground, blocks). In practice you won't run it directly — your agent
framework spawns it as a subprocess. Point the Kindle's KUAL extension
(`kindle/menu.json` in the parent repo) at `http://<this-machine>:8888`.

**Multiple instances share one gazette.** Each agent framework spawns its own
copy of this process, but disk is the source of truth: when a second instance
finds the HTTP port already served by a sibling kindle-gazette (it probes
`/health` to check), it logs that and runs MCP-only against the shared data
dir instead of crashing. Only a *non-gazette* process holding the port is an
error — pick a different `KINDLE_GAZETTE_PORT` then.

### Connecting an agent

#### Hermes Agent

```sh
./scripts/hermes-setup.sh
```

Installs `uv` standalone if needed, pre-resolves dependencies, creates a
wrapper script at `~/.local/bin/kindle-gazette`, and writes the server into
`~/.hermes/config.yaml` (merges — doesn't touch your other MCP servers). Then
type `/reload-mcp` in your Hermes chat.

Pass profile names to also install the repo's `gazette` publishing skill
(`../skills/gazette/` — the convention scheduled agents follow when
publishing) into those profiles' skills directories:
`./scripts/hermes-setup.sh dispatch ops`.

**Why a wrapper script, not a direct `command`+`args` entry?** Hermes can
misparse `command`+`args` arrays in `config.yaml` — it's spawned the array's
first *value* as the literal command instead of running `uv` with those args.
The wrapper bundles `cd <this dir> && exec uv run kindle-gazette` into one
executable, so Hermes only ever needs a single `command` string. This is a
Hermes packaging quirk, not anything about `kindle-gazette` itself.

If you'd rather do it by hand: install `uv` standalone
(`curl -LsSf https://astral.sh/uv/install.sh | sh` — a pip-installed `uv` won't
be on Hermes' PATH), create the wrapper script yourself, then add it to
`~/.hermes/config.yaml` under `mcp_servers.kindle-gazette: {command: <wrapper path>}`
(edit via Python + `yaml.safe_load`/`safe_dump`, not a text editor — Hermes
guards this file from file-editing tools).

| Symptom | Cause | Fix |
|---|---|---|
| `Failed to spawn: kindle-gazette` | Hermes misparsing `command`+`args` | Use the wrapper script (above) |
| `uv: command not found` | pip-installed `uv`, not standalone | Install standalone (see above) |
| Other MCP servers disappeared from config | A setup step overwrote `mcp_servers` instead of merging | Use `hermes-setup.sh` or the Python-YAML merge pattern above |
| `Port 8888 is held by something that is not a kindle-gazette server` | A non-gazette process on the port (sibling gazettes share it silently — see above) | `lsof -iTCP:8888 -sTCP:LISTEN`, kill it or set `KINDLE_GAZETTE_PORT` |

#### Other MCP clients

Any MCP client that spawns a stdio server and correctly parses
`command`+`args` works (Hermes' quirk is the exception). Generic config:

```json
{
  "mcpServers": {
    "kindle-gazette": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/mcp_server", "kindle-gazette"]
    }
  }
}
```

Set env vars in that config's `env` block if you're not using the defaults —
every agent pointed at the same data dir + port shares one gazette.

## Tool surface

| Tool | Purpose |
|---|---|
| `publish_edition(path, edition, card=None)` | Publish an edition. `path` is namespaced by your agent (e.g. `dispatch/morning`); first call creates it, later calls overwrite. `edition` is the one schema below — no `type` field. Pass `card` to put (or refresh) your agent's tile on the home grid in the same call. |
| `delete_edition(path)` | Delete an edition and its `path/pN` continuation pages. |
| `rerender(path=None)` | Re-render one page (or every page) from its stored data — for after a template/theme edit; no agent re-pushes. |
| `get_status()` | Port, screen size, data dir, view/agent counts, uptime. |
| `list_views()` | Every registered page: path, `_view_type` (`"edition"` or `"home"`), title, owning agent, last updated. |

**The `card` argument:** `{"title": str, "summary": [str], "nav_target"?: str}`,
where `nav_target` defaults to the `path` you're publishing. Your `agent_id` is
never passed — it's always the path's first segment (`dispatch/morning` →
`dispatch`), and each agent holds exactly one home slot, assigned in
first-registration order and stable thereafter. Publishing with a `card`
upserts that slot and rebuilds home.

**Results:** `publish_edition` returns `{success, path, image_url, rendered_at,
error, warnings?}` plus `card: {agent_id, slot}` when a card was passed.
`delete_edition` returns a warning if some home card's `nav_target` still
points at the path you deleted.

**Validation:** `publish_edition` payloads are validated before rendering. On
failure you get a *numbered list* of problems — each names the field, the
element index, and what was expected — plus a minimal shape example (of the
edition, or of the specific figure kind that failed), so an agent can
self-correct from the error alone. Unknown top-level fields are accepted
(forward compatibility) but reported back as `warnings`, so a misspelled field
name never fails silently.

**Reserved paths:** `home` (built only from the `card` argument of
`publish_edition`), the `system/` namespace (`system/agents` is an
auto-generated overview of all connected agents, linked from home's overflow
tile), and any final path segment matching `p<digits>` (edition pagination —
see below).

## The edition schema

There is one agent-facing payload — the **edition** — and no `type` field to
pick wrong:

```
{
  "title":       str, required
  "byline":      str, optional — a dateline set under the title
  "body":        str  — plain text: blank-line paragraphs, "## " headings
  "sections":    [{heading?, text?, figure?}]  — exactly one of body | sections
  "back":        str, optional — view path for the Back button. Unset, it
                 resolves to your agent's front page (your home card's
                 nav_target) when you have one and this edition isn't it,
                 else "home"
  "refresh_sec": number, optional — Kindle auto-refresh hint (default 0 = never)
}
```

`body` is the quick form; `sections` is the structured equivalent and the only
way to embed figures. Editions paginate automatically: page 1 lives at the
pushed path, page k at `path/p2`, `path/p3`… with PREV/NEXT buttons — which is
why `p<digits>` is a reserved final path segment. A re-push that shrinks an
edition deletes the stale trailing pages.

Every edition auto-gets a Back button and an Exit button — you don't draw
those. Back opens `edition["back"]` when set; unset, the server resolves it at
fetch time to the agent's front page (the home card's `nav_target`), so a
card → index → edition hierarchy walks back up level by level with no agent
effort — and stays correct whatever order the editions were published in. Tapping the masthead
refreshes the current page; its edition stamp shows when it was rendered.

Grayscale only — e-ink has no color, so severity is drawn as fill darkness
plus a text label, never hue: good/normal reads light, caution mid gray, bad
dark, critical black. Write figures with that in mind; a `callout` in the
`alert` style is the darkest thing the page has.

### Figure kinds

A section's `figure` embeds a chart, table, image, or link list in the text
flow, set between rules with an optional `caption` — it renders after that
section's paragraphs and never splits across a page break. Thirteen kinds,
drawn with one shared visual language:

**Charts**

- `{"kind": "sparkline", "values": [88, 95, 90], "baseline": 95}` — a small
  trend line (2+ numeric values; `baseline` optional).
- `{"kind": "line_chart", "series": [{"label": "HRV", "values": [88, 95, 90]}],
  "x_labels": ["Mon", "Tue", "Wed"], "baseline": 95, "y_min": null, "y_max": null}`
  — up to 3 series over a shared x axis with y ticks and a legend, told apart
  by stroke pattern (solid/dashed/dotted) rather than gray, since neighbouring
  grays dither into similar texture. All series need the same number of values;
  `x_labels` are thinned to ~7 (ends always labelled); `y_min`/`y_max` pin the
  scale that otherwise comes from the data with a 10% pad.
- `{"kind": "bars", "bars": [{"label": "Protein", "value": 120, "max": 160,
  "target": 140}]}` — labeled progress bars; the optional `target`
  draws a tick on the track at `target/max` (readable over light or dark fill).
- `{"kind": "stacked_bar", "segments": [{"label": "Protein", "value": 480},
  {"label": "Carbs", "value": 900}], "max": 2400}` — one track, cycling
  segment grays, legend underneath. `max`
  defaults to the segment total; pass a larger one to show a budget only
  partly consumed.
- `{"kind": "heatmap", "rows": [[0, 2, 5, null]], "row_labels": ["Week 34"],
  "col_labels": ["Mon", "Tue", "Wed", "Thu"], "scale_max": 5}` — a
  calendar-style grid of square cells; darkness is `value / scale_max`
  (default: the largest cell), snapped to the panel's exact 16 grays so the
  figure never relies on dithering. `null` is an empty (dashed) cell, `0` an
  outlined white one — "nothing happened" stays distinct from a small value.

**Data & text**

- `{"kind": "table", "columns": ["Plan", "Price"], "rows": [["Basic", "$5"],
  ["Pro", "$12"]], "align": ["left", "right"]}` — header row + data rows,
  optional per-column alignment (`left`/`right`/`center`, default left). Cells
  are coerced to strings; ragged rows are padded/truncated to the columns.
- `{"kind": "stat_row", "stats": [{"value": "92", "unit": "ms", "label": "HRV",
  "delta": "+4%", "direction": "up"}]}` — 1–4 headline numbers side by side,
  each with a label and an optional ▲/▼ delta (`direction`: `up`/`down`/`flat`).
- `{"kind": "checklist", "items": [{"text": "Ship the report", "state": "done"}]}`
  — done (filled box) / open (empty box) / skipped (boxed ✕, struck through).
- `{"kind": "callout", "text": "Do not train today.", "style": "alert"}` — one
  block of text set apart: `alert` (black band, white bold — reserve for gating
  or safety statements), `note` (bordered box, default), `quote` (large serif
  italic behind a thick left rule).
- `{"kind": "timeline", "events": [{"time": "09:00", "text": "Standup",
  "emphasis": true}]}` — a vertical timeline: free-form `time` labels in a left
  gutter (displayed verbatim, never parsed), a ruled spine with a dot per
  event, solid dot + bold for emphasized ones.

**Navigation**

- `{"kind": "link_list", "links": [{"text": "Morning briefing",
  "nav_target": "dispatch/morning", "note": "07:02"}]}` — rows that navigate
  to another edition when tapped. Per row, `text` and `nav_target` are
  required and `note` is an optional right-hand annotation (a timestamp, a
  count, a status word). Rows are real DOM elements, so the tap map picks them
  up like any other button, and because figures never split across pages a
  link can't straddle a page boundary. This is how an agent with several
  editions stays reachable from its one home card: publish an **index
  edition** whose `link_list` points at the rest (`system/agents` is built
  exactly this way).

**Media**

- `{"kind": "qr", "data": "https://example.com/full-report"}` — a scannable QR
  code (the reader's escape hatch off the e-ink panel). The server encodes it
  (error correction M, pure black/white at an exact integer module scale so it
  survives dithering); send text up to 1000 characters, not pixels.
- `{"kind": "image", "data": "<base64>", "format": "png"|"jpeg"}` — an inline
  image; `data` is base64 (or a full `data:` URI, then `format` is ignored).
  Any grayscale or color image works — the pipeline converts and
  Floyd–Steinberg dithers it, so photos and smooth gradients are fine as-is.

### Examples

A regular edition — prose with figures set into the flow:

```json
{"title": "Weekly Digest", "byline": "research-agent", "sections": [
  {"heading": "Overnight", "text": "First paragraph.\n\nSecond paragraph."},
  {"figure": {"kind": "sparkline", "values": [88, 95, 90], "baseline": 95, "caption": "HRV, 7-day"}},
  {"text": "Closing text", "figure": {"kind": "image", "data": "iVBORw0…", "caption": "Fig. 2"}}
]}
```

An index edition — one agent's table of contents, published at the path its
home card points to:

```json
{"title": "The Dispatch", "byline": "research-agent", "sections": [
  {"text": "Three editions filed since midnight."},
  {"figure": {"kind": "link_list", "caption": "In this edition", "links": [
    {"text": "Morning briefing", "nav_target": "dispatch/morning", "note": "07:02"},
    {"text": "Markets", "nav_target": "dispatch/markets", "note": "6 charts"},
    {"text": "Overnight wire", "nav_target": "dispatch/wire", "note": "23 items"}
  ]}}
]}
```

Published with a front-page card, that's one call:

```
publish_edition(path="dispatch", edition={…the index above…},
                card={"title": "The Dispatch", "summary": ["3 editions since midnight"]})
```

**The pages you don't publish:** `home` is assembled by the server from the
cards agents attach to `publish_edition`, and `system/agents` is an
auto-generated overview — itself an edition whose `link_list` rows carry each
agent's title, its card's `nav_target`, and its updated-at stamp as the `note`.
Neither is agent-pushable; both are reserved paths.

## Styling / theming

Pages render from Jinja2 templates in `src/kindle_gazette/templates/` —
`article.html` for editions, `home.html` for the front page, plus `base.html`
for the shared chrome (masthead, footer). Every
font, size, spacing, and gray value is a CSS custom property in the active
**theme**: a directory under `templates/themes/<name>/` with a `theme.css`
and, optionally, template overrides that shadow the shared ones (theme dir
wins, `templates/` is the fallback). The active theme is
`KINDLE_GAZETTE_THEME` (default `classic`); a pure restyle touches only that
theme's `theme.css`. After editing templates or theme — or switching themes —
call the `rerender` tool to rebuild every stored page from its persisted
data. To compare themes before picking one, `uv run
scripts/preview_themes.py` renders showcase-edition fixtures for every theme
plus a side-by-side contact sheet under `preview/`; see
[`templates/themes/README.md`](src/kindle_gazette/templates/themes/README.md)
for adding and choosing themes. Tap regions are extracted from the rendered
DOM (every visible `data-action` element), so buttons must stay real
elements.

There is no custom-renderer escape hatch — a 14th figure kind is a code
change: a template block in `article.html`, a context builder in
`renderers.py`, and a validation case (with its own shape example) in
`validation.py`.

## Auth (optional)

Set `KINDLE_GAZETTE_TOKEN` and put the same token in
`extensions/kindle-gazette/token` on the Kindle; `gazette.sh` sends it as an
`X-Gazette-Token` header (`?token=` also accepted, for clients that can't set
headers). Comparison is constant-time. `/health` stays token-free — the Kindle
probes it for reachability before auth may be configured, and it leaks nothing
beyond ok/port/view-count. All connected agents remain mutually trusted: any
agent can write any view path.

## Why these design choices

- **Pre-rendered on push, not on request:** rendering (Chromium launch,
  screenshot, grayscale conversion) happens once, when the agent publishes.
  The Kindle's fetch path is a dumb file read — fast and dependency-free even
  when the render stack would be slow or broken.
- **Disk is the source of truth:** the HTTP server serves whatever `store.py`
  persisted (written atomically), so it doesn't matter whether an agent — or
  even this MCP subprocess — is currently alive. This is also what makes the
  multi-instance port sharing above safe.
- **Verbose validation errors:** the callers are agents, not humans with a
  browser console. Errors are numbered, name the exact field and index, and
  ship a shape example, because the agent must self-correct from the message
  alone; unknown fields warn instead of erroring so older servers don't reject
  newer agents' data.

Server behavior (validation, pagination, wire format, port sharing) is covered
by the test suite in `tests/`, run in CI.
