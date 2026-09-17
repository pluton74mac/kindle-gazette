"""Render the Gazette screensaver plates for the Kindle PW4 (linkss hack).

Output: kindle/screensavers/bg_ss00..02.png — 1072x1448, 8-bit grayscale
PNGs whose content is 1-bit Floyd-Steinberg dithered (crispest on e-ink).
linkss cycles them in filename order, one per suspend.

Run with the repo venv:  mcp_server/.venv/bin/python scripts/make-screensavers.py
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 1072, 1448
REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "kindle" / "screensavers"
OUT.mkdir(exist_ok=True)

SUPP = "/System/Library/Fonts/Supplemental"


def font(name: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(f"{SUPP}/{name}", size, index=index)


def center_text(draw, y, text, fnt, fill, tracking=0):
    """Draw text centered at width/2; crude letter-tracking in pixels."""
    if tracking:
        widths = [draw.textlength(ch, font=fnt) for ch in text]
        total = sum(widths) + tracking * (len(text) - 1)
        x = (W - total) / 2
        for ch, w in zip(text, widths):
            draw.text((x, y), ch, font=fnt, fill=fill)
            x += w + tracking
    else:
        w = draw.textlength(text, font=fnt)
        draw.text(((W - w) / 2, y), text, font=fnt, fill=fill)


def finish(img: Image.Image, path: Path):
    """1-bit FS dither, back to 8-bit gray (the format linkss expects)."""
    img.convert("1").convert("L").save(path)
    print(f"wrote {path.relative_to(REPO)}")


# --- plate 00: The Messenger (dark, full-bleed caduceus engraving) --------
src = Image.open(REPO / "scripts/assets/caduceus-src.jpg").convert("L")
scale = max(W / src.width, H / src.height)
src = src.resize((round(src.width * scale), round(src.height * scale)), Image.LANCZOS)
# bias the vertical crop upward: keep the ball finial + wings, trim mostly leg
top = min(60, src.height - H)
plate = src.crop(((src.width - W) // 2, top, (src.width - W) // 2 + W, top + H))
plate = ImageOps.autocontrast(plate, cutoff=1)

d = ImageDraw.Draw(plate)
d.rectangle([0, H - 150, W, H], fill=0)  # caption band over the dark foot
d.line([(W - 340) / 2, H - 118, (W + 340) / 2, H - 118], fill=255, width=2)
center_text(d, H - 104, "THE GAZETTE", font("Bodoni 72 Smallcaps Book.ttf", 44), 255, tracking=10)
center_text(d, H - 44, "THE PRESSES ARE RESTING", font("Bodoni 72 Smallcaps Book.ttf", 24), 200, tracking=8)
finish(plate, OUT / "bg_ss00.png")

# --- plate 01: Masthead (light, typographic night edition) ----------------
plate = Image.new("L", (W, H), 255)
d = ImageDraw.Draw(plate)
m = 96  # side margin

# ear rules
d.line([m, 150, W - m, 150], fill=0, width=2)
ear = font("Bodoni 72 Smallcaps Book.ttf", 30)
d.text((m, 108), "THE AGENT PRESS", font=ear, fill=0)
w = d.textlength("NIGHT EDITION", font=ear)
d.text((W - m - w, 108), "NIGHT EDITION", font=ear, fill=0)

center_text(d, 260, "The Gazette", font("Didot.ttc", 150, index=2), 0)  # 0=Regular 1=Italic 2=Bold
d.line([m, 470, W - m, 470], fill=0, width=6)
d.line([m, 484, W - m, 484], fill=0, width=2)

center_text(d, 530, "PRINTED UPON THE GLASS  ·  CIRCULATION: ONE", font("Bodoni 72 Smallcaps Book.ttf", 28), 0, tracking=4)

# centerpiece ornament
center_text(d, 660, "u", font("Bodoni Ornaments.ttf", 220), 0)

it = font("Didot.ttc", 46, index=1)  # italic
center_text(d, 960, "The presses are resting.", it, 0)
center_text(d, 1030, "A fresh edition awaits the morning bell.", font("Didot.ttc", 36, index=1), 60)

d.line([(W - 340) / 2, 1310, (W + 340) / 2, 1310], fill=0, width=2)
center_text(d, 1330, "HERMES  ·  MMXXVI", font("Bodoni 72 Smallcaps Book.ttf", 30), 0, tracking=8)
finish(plate, OUT / "bg_ss01.png")

# --- plate 02: Moiré Nocturne (the original live-e-ink demo field) --------
plate = Image.new("L", (W, H), 255)
px = plate.load()
c1, c2 = (-150, H * 0.35), (W + 150, H * 0.65)
wavelength = 26.0
for y in range(H):
    for x in range(W):
        d1 = math.hypot(x - c1[0], y - c1[1])
        d2 = math.hypot(x - c2[0], y - c2[1])
        v = math.cos(d1 / wavelength * 2 * math.pi) + math.cos(d2 / wavelength * 2 * math.pi)
        g = int((v + 2) / 4 * 255)
        px[x, y] = 0 if g < 110 else 255 if g > 145 else int((g - 110) / 35 * 255)

d = ImageDraw.Draw(plate)
d.rectangle([0, H - 150, W, H], fill=0)
d.line([(W - 340) / 2, H - 118, (W + 340) / 2, H - 118], fill=255, width=2)
center_text(d, H - 104, "THE GAZETTE", font("Bodoni 72 Smallcaps Book.ttf", 44), 255, tracking=10)
center_text(d, H - 44, "INTERFERENCE, AT REST", font("Bodoni 72 Smallcaps Book.ttf", 24), 200, tracking=8)
finish(plate, OUT / "bg_ss02.png")
