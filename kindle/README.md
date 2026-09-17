# Kindle-side files (KUAL extension)

| File | Purpose |
|---|---|
| `config.xml` | KUAL extension manifest (`<information>`/`<menus>` format) |
| `menu.json` | KUAL menu: Start / Show Home (static) / Stop — **the server URL lives here** |
| `bin/gazette.sh` | Interactive viewer: fetch, display, tap nav, sleep/wake, offline cache fallback |
| `bin/touch_tap` | Prebuilt ARM touch helper — **hardware-verified, do not rebuild** |
| `bin/touch_tap.c` | Reference source, newer than the binary (see its header) |
| `bin/show_static.sh` | Display a cached PNG from `/mnt/us/documents/kindle-gazette/` |
| `bin/stop.sh` | Stop the viewer (PID file first, then killall sweep) |
| `The Gazette.sh` | One-tap launcher **scriptlet** — deploys to `/mnt/us/documents/` (not extensions/), appears in the library as a book |
| `covers/` | Launcher cover images (600×960, panel-dithered): `cover-default.png` (folded broadsheet), `cover-hermes.png`. One is deployed as `extensions/kindle-gazette/cover.png` |
| `screensavers/` | Gazette screensaver plates for linkss — installed by `scripts/deploy-screensavers.sh` |
| `linkss/` | Optional boot hooks piggybacked on the linkss script: `ad_screensaver` watchdog + tailscaled restart (see `linkss/README.md`) |

## Deploy

```sh
# Set your server's IP/hostname in kindle/menu.json first (replace YOUR_SERVER_IP)
cp -r kindle/ /Volumes/Kindle/extensions/kindle-gazette/
chmod +x /Volumes/Kindle/extensions/kindle-gazette/bin/*
find /Volumes/Kindle/extensions/kindle-gazette -name '._*' -delete   # macOS resource forks break KUAL
```

Eject, unplug, then **KUAL → Kindle Gazette → Start Gazette**. When the
device is on your tailnet, `scripts/verify-hardware.sh deploy <kindle-addr>`
does the same over SSH and clears the on-device cache.

## One-tap launch from the library (scriptlet)

`The Gazette.sh` uses the Universal Hotfix's **scriptlet** mechanism: any
`.sh` in `/mnt/us/documents` is indexed as a book; tapping it runs it with
stdout piped to FBInk (live text on the glass). The launcher reads the server
URL from `menu.json`, streams the viewer's own log lines as a visible boot
log until the front page paints, then **stays alive silently until the
viewer exits** — the framework repaints the library over the screen the
moment the scriptlet exits, so holding the "book" open is what keeps the
gazette on the glass; the library returns exactly when the reader exits the
paper. Tapping the book while the press is already running just repaints the
front page.

Cover: the scriptlet's `# Icon:` line points at
`/mnt/us/extensions/kindle-gazette/cover.png`; copy whichever of
`covers/cover-default.png` / `covers/cover-hermes.png` you want there, or any
600×960 grayscale PNG of your own. Deploy:

```sh
cp kindle/covers/cover-default.png /Volumes/Kindle/extensions/kindle-gazette/cover.png
cp "kindle/The Gazette.sh" "/Volumes/Kindle/documents/The Gazette.sh"
chmod +x "/Volumes/Kindle/documents/The Gazette.sh"
```

## Optional auth token

Put a single-line token (no whitespace) in `extensions/kindle-gazette/token`.
The viewer then sends `X-Gazette-Token: <token>` on every request; pair it
with the server's `KINDLE_GAZETTE_TOKEN` env var. No file = no header.

## How the viewer behaves

All of this is hardware-verified on a Kindle Paperwhite 4 (FW 5.16.7):

- **Wake repaints from cache first**, ~2-3s after the unlock, before any
  network work. One short health probe then decides between fetching a fresh
  front page and arming a bounded retry loop. A fresh page identical to the
  cached bytes skips the second flash.
- **Offline is a first-class state.** With the server unreachable the front
  page and every previously opened edition stay browsable from cache; when
  the server returns, the retry loop recovers without interaction.
- **Sleep/wake** is driven by the power daemon's LIPC events. A lock/unlock
  pair queued while a wake is still being processed is collapsed, not
  replayed. The touch helper is never killed across sleep: a frozen process
  cannot read events, so its exclusive grab is effectively released while the
  device sleeps, and buffered swipe-to-unlock touches are drained on wake.
- **Tailscale (optional)** — fetches go through the device's local proxy
  when the Tailscale extension is installed; tailscaled is restarted only
  when the proxy itself is down, never because the server is.
- **Ad-supported devices:** the "SWIPE TO UNLOCK" ad overlay is painted over
  the wake repaint and cannot be swiped while the viewer holds the touch
  grab. Keep the `ad_screensaver` blanket module unloaded — the boot watchdog
  in `linkss/` does that persistently; `gazette.sh` has a marked spot for a
  per-launch unload if you don't use the hooks.
- **Stop** (Exit button or KUAL → Stop) removes the PID file, FIFO, and
  flag files and sweeps the `lipc-wait-event` pipeline so nothing is left
  running.

## Hardware verification checklist

`scripts/verify-hardware.sh checklist` prints this; deploy one change at a
time and keep a copy of the last working `gazette.sh` on the device.

1. KUAL shows the extension.
2. Server running with a test edition (a home card plus a long, paginating
   article).
3. Start Gazette → front page paints; the viewer log shows the touch helper,
   power watcher and (if present) proxy bring-up.
4. Tap navigation: card → article, NEXT, PREV, BACK, masthead refresh — every
   tap a clean hit, no phantom taps.
5. Power sleep/wake: both LIPC events caught, cached repaint, swipe residue
   drained.
6. Failure drill: stop the server, wake the device — cached view appears;
   restart the server — "Retry succeeded" with no interaction.
7. Stop: both exit paths leave no gazette processes or files behind.
8. Token auth: `/health` open; `/view` and `/images` 401 without the token,
   200 with the device token file installed.

Known operational pitfalls: a stale process already bound to port 8888 makes
the new server run MCP-only and serve old views (`lsof -iTCP:8888`); a cold
tailscaled start can take minutes to become routable, which the retry loop
covers; tailscaled log lines interleave with `viewer.log` when the proxy is
restarted (cosmetic).

## Notes for changing the Kindle-side code

- The viewer is busybox `ash`, not bash: no arrays, no `[[ ]]`, no
  `$'...'`, and JSON is parsed with `awk` (no jq or python on the device).
- Start the touch helper *before* opening the FIFO for reading (it blocks on
  `open()` until a reader attaches), and if you ever recreate the FIFO, close
  and reopen the read fd. Don't reorder without testing on hardware.
- Keep any blocking startup work short and bounded: the touch helper grabs
  the touchscreen early, and if the screen times out during a long wait
  before sleep/wake handling is running, the framework never gets touch
  back (recovery: kill the orphaned `touch_tap`).
- Clear the on-device cache on every deploy; stale PNGs from a previous
  session can mask a broken fetch.
- `touch_tap` is a static 32-bit ARM binary (`zig cc -target
  arm-linux-musleabi -O2 -static`). Its behaviour is tuned to this device's
  driver; porting to another Kindle model means re-verifying tap, sleep and
  wake on that hardware, not just recompiling. The server side is
  hardware-agnostic (screen size is a config value).
