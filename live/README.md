# live-e-ink

The Kindle as a **push-driven second monitor** for the PC: glanceable status
panels, annotations, anything the Mac wants to put on the glass, painted over
Tailscale SSH with `eips`.

Not to be confused with **agent-gazette** (the rest of this repo): there,
agents publish editions and the *device pulls* and pages through them. Here
the *PC pushes*, there are no agents, no server, no viewer loop — just a
framebuffer at the other end of an SSH session. It is in this repo because
it uses the same device access and painting mechanics the gazette relies on
(and was worked out while building it), and because it is the quickest way
to see what the panel is showing while you work on the gazette —
`screenshot.sh` is the gazette's own debugging tool.

## Scripts (run on the Mac)

All scripts target `$KINDLE_HOST` — export it as the Kindle's Tailscale IP
or hostname (the scripts refuse to run without it).

| Script | What it does |
|---|---|
| `push.sh <image.png>` | scp a PNG to the device and blit it full-screen (`eips -f -g`, full refresh) |
| `text.sh <col> <row> <text...>` | paint one line of text via `eips` (partial refresh) |
| `fbink.sh <fbink args...>` | run FBInk on the device — flash-free DU waveform, scaled fonts, full glyph set |
| `panel.sh [max_ticks]` | **the live monitor loop**: clock + Mac/Kindle status cells, repainted every `INTERVAL` (default 30s) with DU, one SSH connection per tick; holds the device awake and restores `preventScreenSaver` on ctrl-c |
| `screenshot.sh [out.png]` | pixel-exact screenshot of the glass: dumps `/dev/fb0` over SSH and decodes it (1088-byte stride, 1072×1448 visible). Works whenever the CPU is awake — screensaver included — but not in deep suspend (SSH dies with tailscaled) |
| `clear.sh` | clear the screen (`eips -c`) |
| `hold.sh on\|off` | toggle `preventScreenSaver` — hold the device awake while it's a monitor |
| `examples/moire.py` | renders the original demo artwork (needs Pillow, e.g. `../mcp_server/.venv/bin/python`) |

## Mechanics & gotchas (hardware-verified on the PW4)

- Native resolution is **1072×1448**, 8-bit grayscale. 1-bit Floyd–Steinberg
  dither looks best on e-ink; save back as 8-bit gray PNG.
- **PNG blits are full refreshes** (black flash); **text paints are partial
  refreshes** (instant, no flash, only the drawn rows repaint — so you can
  append to a screen without clearing it). A live panel wants a hybrid:
  PNG for the frame/typography, `eips` text for ticking cells.
- The built-in `eips` font is one fixed small size, ASCII-ish, and **missing
  glyphs** (notably `%`).
- `eips` has **no `--` end-of-options separator**: text starting with `-` is
  parsed as options, garbles the paint, *and* triggers a FULL (whole-screen)
  update — it looks like partial refresh breaking, but it isn't. `text.sh`
  guards against this by prefixing a space.
- Everything painted is **transient**: the Kindle framework repaints on
  suspend/wake (screensaver) and gazette.sh repaints on its events. Use
  `hold.sh on` while the device is being a monitor, and `hold.sh off` when
  done — leaving it on breaks agent-gazette's sleep lifecycle.
- Live device data via lipc, e.g.
  `lipc-get-prop com.lab126.powerd battLevel`.

## FBInk (preferred for text)

The device **already ships FBInk 1.25.0** at `/mnt/us/libkh/bin/fbink`
(bundled with libkh; more copies live under `koreader/`, `linkss/`,
`MRInstaller/` and `/var/local/kmc/armhf/bin/`). It fixes every `eips` text
limitation:

- `-W DU` uses the direct-update waveform: **no blink at all**, ~260ms —
  ideal for ticking cells. `-W GC16` when you want a clean grayscale repaint.
- `-S <n>` scales the bitmap font (`-S 3` makes a real headline), `-m`
  centers, `-x/-y` position in character cells, and the full glyph set is
  there (`%` included).
- Gotcha: invoked with **no message argument** over non-interactive SSH
  (e.g. clear-only `-c -f`), fbink sniffs the empty stdin and aborts early —
  append an explicit empty string: `fbink -c -f -W GC16 ""`.

Verified on the PW4: the `eips` mechanics above, plus an FBInk DU ticker
updating in place with zero flash.
