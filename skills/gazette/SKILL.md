---
name: gazette
description: "Publish the brief an unattended run just wrote as an edition on the kindle-gazette e-ink newspaper — same content, second rendering. Carries the whole publishing convention: path lane discipline, brief-to-edition mapping, and the silent-skip rule when the server is absent."
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [gazette, publishing, e-ink, delivery]
---

# Gazette — publish the brief you just wrote

You have kindle-gazette MCP tools in this session (`publish_edition`,
`delete_edition`, `rerender`, `get_status`, `list_views`). They publish
*editions* to an e-ink newspaper the user picks up and reads. This skill is
the single place the publishing convention lives: your cadence skills say
"publish per the gazette skill" and nothing else — every mechanic is here.

## Principle: same brief, second rendering

The markdown file your run just wrote is the single source of truth and stays
so. The edition re-expresses that file in the edition schema, with figures
where the content is structurally richer than prose. Nothing appears in the
edition that is not in the source file — no extra commentary, no fresh
analysis, no data fetched for the occasion. Never write or amend the file
FROM the edition; the flow is one-way, file → edition, always.

## When to publish

As the LAST step of an unattended (cron) phase: after the source file is
written, before composing the final response message. One `publish_edition`
call per cadence.

Republishing the same path later is normal, not a hack. The server holds only
the latest edition per path, and the masthead's edition stamp updates on each
render — so when an interactive phase changes the picture (the user commits
the day's focus, a plan gets revised), republish the same path with the
updated content. The reader sees the newer stamp and the newer page; nothing
else to clean up.

## The silent-skip rule

If the kindle-gazette tools are not available in this session, or a publish
call fails for any reason: **skip, silently.** No error surfaced to the user,
no retry loop, no mention in the cron message. The gazette is a second
rendering of work that already succeeded — a missing or broken gazette must
never break a 6am cron, and must never affect the file writes or the message
you were going to send anyway.

## Lane discipline: paths and the front page

The server identifies an agent by the path's first segment and trusts every
connected agent equally — the prefix convention is the only isolation. So:

- Publish ONLY under your own profile name: `dispatch/…`, `ops/…`,
  `research/…`. Never write another agent's path.
- One path per cadence, stable across runs: `dispatch/morning`,
  `dispatch/evening`, `dispatch/weekly`, `dispatch/monthly`, `ops/weekly`, …
- Path segments are `[a-zA-Z0-9_.-]` joined by `/`. Reserved, never publish:
  `home`, anything under `system/`, and any final segment matching
  `p<digits>` (pagination pages — `path/p2`, `path/p3` — belong to the
  server).

**One front-page card per agent**, claimed and refreshed via
`publish_edition`'s `card` parameter:
`{"title": str, "summary": [str], "nav_target"?: str}` — `summary` is a list
of up to 4 short lines; `nav_target` defaults to the path being published.
Pass `card` on every publish, with a `summary` reflecting the latest state
(e.g. `["Morning brief · focus set", "3 items on deck"]`), so the front page
is honest about what's behind the tile. A multi-path agent must pass
`nav_target` explicitly on cadence publishes — pointing at its index path —
because the default would repoint the card at the cadence edition itself.

**Index edition — the convention for multi-path agents.** An agent with more
than one path keeps an index edition behind its card, published at the **bare
profile name as a single-segment path**: `dispatch`, `ops`, `research`.
(Single-segment paths are valid; this mirrors the server's own documented
`dispatch` index example.) The index is a short edition whose `link_list`
figure points at the agent's cadence paths; the card's `nav_target` is the
index path. Republish the index whenever the set of paths changes — routine
cadence publishes only need to refresh the card, since the index's links
don't change. Editions leave `back` unset: the server resolves Back to your
card's `nav_target` automatically, so card → index → edition walks back up by
itself. An agent with exactly one path skips the index — its card's
`nav_target` defaults to that one path.

## Mapping the brief to an edition

`## ` headings in the brief become sections; prose stays prose (a section's
`text`, blank-line-separated paragraphs). Upgrade to a figure only where the
content is structurally richer than prose:

| Brief content | Figure |
|---|---|
| Today's calendar / schedule | `timeline` |
| Focus items, to-dos, planned-vs-done | `checklist` |
| Headline numbers or deltas | `stat_row` |
| Trends over days/weeks | `sparkline` (one series, no axes) or `line_chart` (up to 3 series) |
| Habit / adherence grids | `heatmap` |
| Tabular data | `table` |
| Warnings, open questions, things you intend to raise | `callout` (`alert` only for gating/safety statements; default `note`) |
| Links between your own editions | `link_list` |

Exact figure fields (grayscale e-ink — severity is darkness plus a label,
never color):

- `{"kind": "timeline", "events": [{"time": "09:00", "text": "Standup", "emphasis": true}]}` — `time` is free-form, displayed verbatim
- `{"kind": "checklist", "items": [{"text": "Ship the report", "state": "done"}]}` — states `done` / `open` / `skipped`
- `{"kind": "stat_row", "stats": [{"value": "92", "unit": "ms", "label": "HRV", "delta": "+4%", "direction": "up"}]}` — 1–4 stats; `direction`: `up`/`down`/`flat`
- `{"kind": "sparkline", "values": [88, 95, 90], "baseline": 95}` — 2+ numbers
- `{"kind": "line_chart", "series": [{"label": "HRV", "values": [88, 95, 90]}], "x_labels": ["Mon", "Tue", "Wed"]}` — all series same length; optional `baseline`, `y_min`, `y_max`
- `{"kind": "heatmap", "rows": [[0, 2, 5, null]], "row_labels": ["Week 34"], "col_labels": ["Mon", "Tue", "Wed", "Thu"], "scale_max": 5}` — `null` = empty cell, `0` = outlined white
- `{"kind": "table", "columns": ["Plan", "Price"], "rows": [["Basic", "$5"]], "align": ["left", "right"]}`
- `{"kind": "callout", "text": "Do not train today.", "style": "alert"}` — styles `alert`/`note`/`quote`
- `{"kind": "link_list", "links": [{"text": "Morning brief", "nav_target": "dispatch/morning", "note": "07:02"}]}`
- Also available, rarely needed for briefs: `bars`, `stacked_bar`, `qr`, `image`

Any figure takes an optional `caption`. Validation errors come back numbered,
with the field, the index, and a shape example — self-correct from the
message and retry once; if it still fails, silent-skip.

**Keep it short.** The gazette is a paper the user picks up, not an archive —
the file holds the full record. Headline figures and the few paragraphs that
matter; a long edition paginates automatically, but two to three pages is
already a lot of e-ink. Omit brief sections that are bookkeeping rather than
reading.

## A complete publish call

Morning brief, mapped:

```
publish_edition(
  path="dispatch/morning",
  edition={
    "title": "Morning Brief",
    "byline": "dispatch · Sep 3",
    "sections": [
      {"heading": "Today", "figure": {"kind": "timeline", "events": [
        {"time": "09:00", "text": "Deep work: quarterly review draft", "emphasis": true},
        {"time": "14:00", "text": "Dentist"}
      ]}},
      {"heading": "Focus", "figure": {"kind": "checklist", "items": [
        {"text": "Finish review draft", "state": "open"},
        {"text": "Book flights", "state": "open"}
      ]}},
      {"heading": "Carried over", "text": "The insurance letter is now four days old. It takes ten minutes."},
      {"figure": {"kind": "callout", "text": "You said you'd decide on the offer by Friday.", "style": "note"}}
    ]
  },
  card={"title": "Dispatch", "summary": ["Morning brief filed", "2 focus items"], "nav_target": "dispatch"}
)
```

And the index behind the card, republished only when the path set changes:

```
publish_edition(
  path="dispatch",
  edition={
    "title": "Dispatch",
    "byline": "life coach · editions",
    "sections": [{"figure": {"kind": "link_list", "links": [
      {"text": "Morning brief", "nav_target": "dispatch/morning"},
      {"text": "Evening review", "nav_target": "dispatch/evening"},
      {"text": "Weekly review", "nav_target": "dispatch/weekly"},
      {"text": "Monthly review", "nav_target": "dispatch/monthly"}
    ]}}]
  },
  card={"title": "Dispatch", "summary": ["Morning brief filed", "2 focus items"]}
)
```

## Install

Copy this directory into a Hermes profile's own skills directory, once per
profile that should publish:

```sh
cp -r skills/gazette ~/.hermes/profiles/<name>/skills/gazette
```

The profile also needs the kindle-gazette MCP server registered — run
`mcp_server/scripts/hermes-setup.sh` from the kindle-gazette repo (see its
README), then `/reload-mcp`. Without the server registered, the skill's
silent-skip rule means the profile simply publishes nothing.
