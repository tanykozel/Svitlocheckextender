"""Draws assets/bot-avatar.png (640x640): python assets/make_avatar.py assets/bot-avatar.png preview.png"""
import math, sys
from PIL import Image, ImageDraw, ImageFilter

S = 2560          # draw big, downscale for smooth edges
OUT = 640         # Telegram recommends at least 512x512
img = Image.new("RGB", (S, S))
px = img.load()

# Radial blue gradient: lighter in the middle, deep navy at the edges.
cx = cy = S / 2
inner, outer = (37, 99, 175), (10, 32, 72)
for y in range(S):
    for x in range(S):
        t = min(1.0, math.hypot(x - cx, y - cy) / (S * 0.62))
        px[x, y] = tuple(int(inner[i] + (outer[i] - inner[i]) * t) for i in range(3))

# Soft yellow glow behind the bulb.
glow = Image.new("L", (S, S), 0)
gd = ImageDraw.Draw(glow)
r = 760
gd.ellipse((cx - r, cy - 260 - r, cx + r, cy - 260 + r), fill=150)
glow = glow.filter(ImageFilter.GaussianBlur(220))
img = Image.composite(Image.new("RGB", (S, S), (255, 214, 60)), img, glow)

d = ImageDraw.Draw(img)
yellow, amber, metal, metal_dark = (255, 213, 0), (240, 170, 0), (205, 214, 226), (150, 162, 180)

# Glass: a circle that narrows into a neck.
bx, by, br = cx, cy - 240, 560
d.ellipse((bx - br, by - br, bx + br, by + br), fill=yellow)
neck_top, neck_bottom = by + 330, by + 760
d.polygon([(bx - 395, neck_top), (bx + 395, neck_top), (bx + 250, neck_bottom), (bx - 250, neck_bottom)], fill=yellow)
# Highlight on the glass.
d.ellipse((bx - 400, by - 400, bx - 160, by - 160), fill=(255, 238, 140))

# Screw base with ridges.
top = neck_bottom - 10
for i in range(3):
    y0 = top + i * 120
    d.rounded_rectangle((bx - 270, y0, bx + 270, y0 + 100), radius=45, fill=metal if i % 2 == 0 else metal_dark)
d.rounded_rectangle((bx - 150, top + 360, bx + 150, top + 450), radius=45, fill=metal_dark)

# Lightning bolt inside the glass (deep blue, matches the background).
bolt = [(bx + 70, by - 380), (bx - 210, by + 60), (bx - 20, by + 60),
        (bx - 110, by + 420), (bx + 220, by - 60), (bx + 20, by - 60), (bx + 130, by - 380)]
d.polygon(bolt, fill=(18, 58, 118))

img = img.resize((OUT, OUT), Image.LANCZOS)
img.save(sys.argv[1], optimize=True)

# Preview of how Telegram shows it (round crop) - for review only.
mask = Image.new("L", (OUT, OUT), 0)
ImageDraw.Draw(mask).ellipse((0, 0, OUT, OUT), fill=255)
preview = Image.new("RGB", (OUT, OUT), (240, 242, 245))
preview.paste(img, (0, 0), mask)
preview.save(sys.argv[2])
