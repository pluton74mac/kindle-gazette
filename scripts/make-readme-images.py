#!/usr/bin/env python
"""Build the README showcase images into docs/images/.

Sources (all rendered by the real pipeline, nothing mocked):
  mcp_server/preview/<theme>/*.png   — `uv run scripts/preview_themes.py`
                                        (run it first; preview/ is gitignored)
  kindle/screensavers/bg_ss0*.png    — the linkss plates
  kindle/covers/cover-*.png          — the library-launcher covers

Outputs (tracked, downscaled, RGBA on a transparent ground):
  docs/images/reading-flow.png   home → edition → index, classic theme
  docs/images/themes.png         the same edition page through all eight themes
  docs/images/device-dress.png   three screensaver plates + two library covers
(docs/images/hero-photo.jpg is a photograph of the device, not generated.)

Run from the repo root with the server venv's Python (it has Pillow):
  mcp_server/.venv/bin/python scripts/make-readme-images.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PREVIEW = ROOT / "mcp_server" / "preview"
OUT = ROOT / "docs" / "images"

THEMES = ["classic", "gazette", "slate", "braun", "cupertino", "departure", "terminal", "noir"]
FLOW = [("home.png", "Front page"), ("charts_p1.png", "An edition"), ("index.png", "An agent's index")]

INK = (128, 128, 128, 255)       # label text: mid-gray reads on light and dark READMEs
PAPER = 238                       # e-ink "white" is not white


def font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("Helvetica.ttc", "HelveticaNeue.ttc", "Arial.ttf", "DejaVuSans.ttf"):
        for base in ("/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
                     "/usr/share/fonts/truetype/dejavu"):
            p = Path(base) / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def page(theme: str, name: str) -> Image.Image:
    p = PREVIEW / theme / name
    if not p.exists():
        raise SystemExit(f"missing {p} — run `uv run scripts/preview_themes.py` in mcp_server/ first")
    return Image.open(p).convert("L")


def eink(im: Image.Image) -> Image.Image:
    """Pull pure white down to panel paper so a page reads as e-ink, not a PDF."""
    return im.point(lambda v: round(v * PAPER / 255))


def thumb(im: Image.Image, width: int) -> Image.Image:
    h = round(im.height * width / im.width)
    return im.resize((width, h), Image.LANCZOS)


def hairline(im: Image.Image) -> Image.Image:
    """1px mid-gray border so a white page has an edge on a white README."""
    rgba = im.convert("RGBA")
    ImageDraw.Draw(rgba).rectangle([0, 0, rgba.width - 1, rgba.height - 1], outline=(150, 150, 150, 255))
    return rgba


def row(items: list[tuple[Image.Image, str]], *, gap: int, label_size: int = 22, pad: int = 8) -> Image.Image:
    """Lay thumbnails in a row on a transparent ground with a caption under each."""
    f = font(label_size)
    label_h = label_size + 14 if any(t for _, t in items) else 0
    w = sum(i.width for i, _ in items) + gap * (len(items) - 1) + pad * 2
    h = max(i.height for i, _ in items) + label_h + pad * 2
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    x = pad
    for im, text in items:
        canvas.paste(im, (x, pad), im if im.mode == "RGBA" else None)
        if text:
            tw = d.textlength(text, font=f)
            d.text((x + (im.width - tw) / 2, pad + im.height + 8), text, font=f, fill=INK)
        x += im.width + gap
    return canvas


def stack(rows: list[Image.Image], gap: int) -> Image.Image:
    w = max(r.width for r in rows)
    h = sum(r.height for r in rows) + gap * (len(rows) - 1)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    y = 0
    for r in rows:
        canvas.paste(r, ((w - r.width) // 2, y), r)
        y += r.height + gap
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. reading flow — three classic pages
    flow = row([(hairline(thumb(eink(page("classic", n)), 360)), t) for n, t in FLOW], gap=28, label_size=24)
    flow.save(OUT / "reading-flow.png", optimize=True)

    # 2. themes — the same edition page through all eight, two rows of four
    tiles = [(hairline(thumb(eink(page(t, "charts_p1.png")), 260)), t) for t in THEMES]
    themes = stack([row(tiles[:4], gap=22, label_size=22), row(tiles[4:], gap=22, label_size=22)], gap=18)
    themes.save(OUT / "themes.png", optimize=True)

    # 3. device dress — plates and covers at one height
    height = 380
    def at_height(p: Path) -> Image.Image:
        im = Image.open(p).convert("L")
        return hairline(im.resize((round(im.width * height / im.height), height), Image.LANCZOS))
    plates = [(at_height(ROOT / "kindle" / "screensavers" / f"bg_ss0{i}.png"), f"Screensaver {i + 1}") for i in range(3)]
    covers = [(at_height(ROOT / "kindle" / "covers" / "cover-default.png"), "Library cover"),
              (at_height(ROOT / "kindle" / "covers" / "cover-hermes.png"), "Hermes cover")]
    dress = row(plates + covers, gap=26, label_size=22)
    dress.save(OUT / "device-dress.png", optimize=True)

    for p in sorted(OUT.glob("*.png")):  # the .jpg hero is a photo, not ours to rebuild
        im = Image.open(p)
        print(f"{p.relative_to(ROOT)}  {im.width}x{im.height}  {p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
