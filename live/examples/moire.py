"""Generate a fun 1072x1448 grayscale PNG for the Kindle PW4 e-ink screen."""
import math
from PIL import Image, ImageDraw, ImageFont

W, H = 1072, 1448

# --- moiré interference field ---
img = Image.new("L", (W, H), 255)
px = img.load()

c1 = (-150, H * 0.35)
c2 = (W + 150, H * 0.65)
wavelength = 26.0

for y in range(H):
    for x in range(W):
        d1 = math.hypot(x - c1[0], y - c1[1])
        d2 = math.hypot(x - c2[0], y - c2[1])
        v = math.cos(d1 / wavelength * 2 * math.pi) + math.cos(d2 / wavelength * 2 * math.pi)
        # map [-2,2] -> [0,255], boost contrast
        g = int((v + 2) / 4 * 255)
        g = 0 if g < 110 else 255 if g > 145 else int((g - 110) / 35 * 255)
        px[x, y] = g

# --- banner ---
draw = ImageDraw.Draw(img)

def load_font(size):
    for path in (
        "/System/Library/Fonts/Supplemental/Futura.ttc",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()

title_font = load_font(88)
sub_font = load_font(40)

title = "PAINTED OVER SSH"
sub = "no viewer, no server — just eips"

tb = draw.textbbox((0, 0), title, font=title_font)
sb = draw.textbbox((0, 0), sub, font=sub_font)
tw, th = tb[2] - tb[0], tb[3] - tb[1]
sw, sh = sb[2] - sb[0], sb[3] - sb[1]

pad = 46
box_w = max(tw, sw) + pad * 2
box_h = th + sh + pad * 2 + 30
bx = (W - box_w) // 2
by = (H - box_h) // 2

draw.rectangle([bx - 8, by - 8, bx + box_w + 8, by + box_h + 8], fill=0)
draw.rectangle([bx, by, bx + box_w, by + box_h], fill=255)
draw.rectangle([bx + 14, by + 14, bx + box_w - 14, by + box_h - 14], outline=0, width=3)

draw.text(((W - tw) // 2 - tb[0], by + pad - tb[1]), title, font=title_font, fill=0)
draw.text(((W - sw) // 2 - sb[0], by + pad + th + 30 - sb[1]), sub, font=sub_font, fill=0)

# crisp 1-bit dither looks best on e-ink, saved back as 8-bit gray
img = img.convert("1").convert("L")
img.save("moire.png")
print("done", img.size)
