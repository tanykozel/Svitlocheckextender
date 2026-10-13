"""Draws Лампочка Люся (assets/lyusya-avatar.png, 640x640): python assets/make_lyusya.py OUT.png [PREVIEW.png]"""

import math
import sys

from PIL import Image, ImageDraw, ImageFilter

S, OUT = 2560, 640  # draw big, downscale for smooth edges
cx = cy = S / 2

# Background: radial blue gradient.
img = Image.new("RGB", (S, S))
grad = Image.radial_gradient("L").resize((S, S))  # 0 in the centre -> 255 at the edge
inner, outer = (40, 104, 182), (10, 32, 74)
img = Image.composite(Image.new("RGB", (S, S), outer), Image.new("RGB", (S, S), inner), grad)

# Warm glow behind the bulb.
glow = Image.new("L", (S, S), 0)
ImageDraw.Draw(glow).ellipse((cx - 820, cy - 1100, cx + 820, cy + 540), fill=120)
glow = glow.filter(ImageFilter.GaussianBlur(230))
img = Image.composite(Image.new("RGB", (S, S), (255, 226, 120)), img, glow)

d = ImageDraw.Draw(img)
yellow, outline = (255, 214, 10), (226, 160, 0)
bx, by, br = cx, cy - 250, 600

# Glass: circle + neck, with a soft outline.
d.ellipse((bx - br - 18, by - br - 18, bx + br + 18, by + br + 18), fill=outline)
d.polygon([(bx - 430, by + 340), (bx + 430, by + 340), (bx + 270, by + 800), (bx - 270, by + 800)], fill=outline)
d.ellipse((bx - br, by - br, bx + br, by + br), fill=yellow)
d.polygon([(bx - 410, by + 330), (bx + 410, by + 330), (bx + 255, by + 785), (bx - 255, by + 785)], fill=yellow)
d.ellipse((bx - 430, by - 430, bx - 230, by - 230), fill=(255, 241, 160))  # shine

# Screw base.
top = by + 775
for i, color in enumerate([(205, 214, 228), (150, 163, 184), (205, 214, 228)]):
    d.rounded_rectangle((bx - 285, top + i * 125, bx + 285, top + i * 125 + 105), radius=48, fill=color)
d.rounded_rectangle((bx - 160, top + 375, bx + 160, top + 470), radius=46, fill=(150, 163, 184))

# Face.
ink = (40, 38, 60)
for ex in (bx - 205, bx + 205):
    d.ellipse((ex - 72, by - 40, ex + 72, by + 120), fill=ink)                 # eye
    d.ellipse((ex - 40, by - 10, ex + 2, by + 32), fill=(255, 255, 255))       # sparkle
    d.ellipse((ex + 14, by + 50, ex + 34, by + 70), fill=(255, 255, 255))
    for k in (-1, 0, 1):                                                       # lashes
        ang = math.radians(-90 + k * 32 + (18 if ex > bx else -18))
        x0, y0 = ex + 62 * math.cos(ang), by - 25 + 70 * math.sin(ang)
        d.line((x0, y0, x0 + 55 * math.cos(ang), y0 + 55 * math.sin(ang)), fill=ink, width=22)
for chx in (bx - 330, bx + 330):                                               # cheeks
    blush = Image.new("L", (S, S), 0)
    ImageDraw.Draw(blush).ellipse((chx - 95, by + 150, chx + 95, by + 250), fill=150)
    blush = blush.filter(ImageFilter.GaussianBlur(18))
    img = Image.composite(Image.new("RGB", (S, S), (255, 128, 128)), img, blush)
d = ImageDraw.Draw(img)
d.arc((bx - 150, by + 70, bx + 150, by + 330), start=20, end=160, fill=ink, width=34)  # smile

# Bow (blue, Ukraine colours with the yellow bulb), top right.
bow_x, bow_y = bx + 300, by - 470
blue, blue_dark = (34, 104, 214), (18, 66, 150)
d.polygon([(bow_x, bow_y), (bow_x - 230, bow_y - 150), (bow_x - 230, bow_y + 150)], fill=blue)
d.polygon([(bow_x, bow_y), (bow_x + 230, bow_y - 150), (bow_x + 230, bow_y + 150)], fill=blue)
d.ellipse((bow_x - 70, bow_y - 70, bow_x + 70, bow_y + 70), fill=blue_dark)

img = img.resize((OUT, OUT), Image.LANCZOS)
img.save(sys.argv[1], optimize=True)
if len(sys.argv) > 2:  # round-crop preview, as Telegram shows it
    mask = Image.new("L", (OUT, OUT), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, OUT, OUT), fill=255)
    preview = Image.new("RGB", (OUT, OUT), (240, 242, 245))
    preview.paste(img, (0, 0), mask)
    preview.save(sys.argv[2])
