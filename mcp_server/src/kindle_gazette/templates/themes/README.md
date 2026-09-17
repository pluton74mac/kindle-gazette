# Themes

A **theme** is one design style for the whole gazette: a directory here named
after the theme, holding

- `theme.css` (required) — two parts, in order: the `:root` token block
  (every font, size, spacing, border, and gray value that `base.html`
  consumes — declare all of them; an omitted custom property resolves to
  nothing, not to another theme's value), then optional component overrides —
  plain CSS targeting the class names in `base.html`. The overrides work
  because `base.html` inlines `theme.css` *after* its shared style block, so
  equal-specificity theme rules win. A pure restyle is only this file.
- any template overrides (optional) — a file named like one of the shared
  templates (`article.html`, `home.html`, `base.html`, …) shadows it for this
  theme only. Use this when a style needs different *markup*, not just
  different tokens or CSS (e.g. `gazette`'s two-column article flow).
  Everything not overridden falls back to the shared `templates/` directory.
  An override is a **copy** of the shared template and does not track it: when
  the shared one gains a figure kind, every override must be brought forward
  by hand or that theme silently drops it. `test_themes.py` renders the
  showcase edition through every theme to catch exactly that.

There are only two things to render: an **edition** (an agent's prose and
figures, auto-paginated by `article.html`) and **home** (the server-built grid
of agent cards, `home.html`). So a theme's component overrides fall into three
groups, and nothing else:

- **chrome** — `.masthead*`, `.edition-stamp`, `.content`, `.footer`, `.btn*`,
  `.hint`, `.page-indicator`
- **home** — `.card-grid`, `.card`, `.card-title`, `.card-line`, `.empty-note`
- **the edition and its figures** — `.article-*`, `.figure-*`, and the
  per-kind classes: `.spark-*` / `.fline-*` (sparkline, line_chart),
  `.fheat-*` (heatmap), `.pbar*` (bars), `.stacked-*` + `.seg-*` + `.legend*`
  (stacked_bar), `.ftable*` (table), `.fstat*` (stat_row), `.fcheck*`
  (checklist), `.fcallout-*` (callout), `.ftl*` (timeline), `.fqr-img` (qr),
  `.flink*` (link_list)

The server renders with one theme at a time, chosen by the
`KINDLE_GAZETTE_THEME` env var (default `classic`). An unknown name fails
loudly at render time, listing what's available.

## Included themes

Each new theme's directory carries a `screenshots/` folder with the four
showcase pages `preview_themes.py` renders — grayscale 1072 × 1448, the
post-dither image the Kindle actually receives, first page only where the
edition paginates — so the table doubles as a picker.

| Theme | Intent | Look |
|---|---|---|
| `classic` | The default restrained broadsheet: serif masthead over a double rule, sans data, hairline borders. | — |
| `noir` | Token-only example variant: heavier rules and borders, darker muted text, all flat grays snapped to the panel's exact 16 levels. | — |
| `terminal` | Monospace technical console: inverted status-line masthead, banded card slots, bracketed tap targets, caret-led link rows. | [home](terminal/screenshots/home.png) · [charts](terminal/screenshots/charts.png) · [tables](terminal/screenshots/tables.png) · [index](terminal/screenshots/index.png) |
| `braun` | As little design as possible: Helvetica, wide margins, one rule where a rule is needed, recessed key-cap controls; nothing is bold. | [home](braun/screenshots/home.png) · [charts](braun/screenshots/charts.png) · [tables](braun/screenshots/tables.png) · [index](braun/screenshots/index.png) |
| `departure` | Station concourse: condensed caps, black organising bands top and bottom, huge numerals, link rows as board entries. Needs a condensed font on the render host — `preview_themes.py` warns if none is found. | [home](departure/screenshots/home.png) · [charts](departure/screenshots/charts.png) · [tables](departure/screenshots/tables.png) · [index](departure/screenshots/index.png) |
| `cupertino` | Apple reading grammar: Large Title masthead, grouped inset lists with chevrons, soft 28px corners, pill toolbar. | [home](cupertino/screenshots/home.png) · [charts](cupertino/screenshots/charts.png) · [tables](cupertino/screenshots/tables.png) · [index](cupertino/screenshots/index.png) |
| `gazette` | Period broadsheet: engraved masthead, ornamental rules, dinkus separator, roman-numeral story slots, two-column justified edition with a drop cap (own `article.html`), figures as "Fig. n" engravings. | [home](gazette/screenshots/home.png) · [charts](gazette/screenshots/charts.png) · [tables](gazette/screenshots/tables.png) · [index](gazette/screenshots/index.png) |
| `slate` | Contemporary editorial: near-black slate ink (`#111`), serif prose against wide-tracked uppercase sans micro-labels, one solid slate band per page. | [home](slate/screenshots/home.png) · [charts](slate/screenshots/charts.png) · [tables](slate/screenshots/tables.png) · [index](slate/screenshots/index.png) |

Note on home-card status chips: the six new designs were drawn with a severity
chip per card (`CRITICAL` / `WARNING` …), but a home card carries no `status`
field today, so the themes ship without chips — every theme renders correctly
from the current card data, and the chips are the only thing lost. If the card
schema ever grows an optional `status`, emit it in `home.html` and each theme
can style its own chip.

## Adding a theme

1. Copy `classic/` to `themes/<your-name>/` and edit `theme.css` (start
   token-only; add template overrides only when tokens can't express the
   change). Mind the e-ink constraints —
   grayscale only, flat tones on multiples of `#11`, no webfonts, tap targets
   ≥ 90px, keep every `data-action` element. `.flink-row` is a tap target too:
   whatever you do to it, keep it at least `var(--button-h)` tall.
2. Preview it against the others:

   ```sh
   uv run scripts/preview_themes.py
   ```

   which renders the four showcase pages per
   theme — `charts` (stat_row, line_chart, sparkline, bars, stacked_bar,
   heatmap), `tables` (callout, table, checklist, timeline, qr), `index`
   (link_list) and `home` — into `preview/<theme>/` plus a side-by-side
   `preview/contact_sheet.png`. Between them they cover every figure kind a
   theme can restyle. Editions paginate: a fixture that spills writes
   `<name>_p1.png`, `<name>_p2.png`, …
3. Describe its intent in one line in the table above, and copy the four
   first-page renders into `<your-name>/screenshots/` if you want it in the
   picker.

## Choosing a theme

Grays and hairlines that look fine on a monitor can die on reflective e-ink,
so decide by looking at renders — ideally on glass:

1. **Contact sheet first** — `uv run scripts/preview_themes.py` and compare
   `preview/contact_sheet.png` on a desktop.
2. **On the device last** — set `KINDLE_GAZETTE_THEME=<name>`, restart the
   server, call the `rerender` MCP tool: every persisted view is rebuilt in
   the new look without any agent re-pushing. Trying a candidate for a day
   costs one env var; switch back the same way.
