"""Custom «Лампочка Люся» character icons (640x640).

    python assets/make_lyusya_v2.py vinok OUT.png [PREVIEW.png]   # flower crown + bell
    python assets/make_lyusya_v2.py bow   OUT.png [PREVIEW.png]   # bow + phone with alert
"""

import math
import sys

from PIL import Image, ImageDraw, ImageFilter

S, OUT = 2560, 640
cx = cy = S / 2
INK = (44, 40, 64)
YELLOW, YELLOW_EDGE, SHINE = (255, 212, 20), (228, 158, 0), (255, 243, 170)


def background() -> Image.Image:
    grad = Image.radial_gradient("L").resize((S, S))
    img = Image.composite(Image.new("RGB", (S, S), (12, 36, 84)), Image.new("RGB", (S, S), (44, 112, 196)), grad)
    rays = Image.new("L", (S, S), 0)
    rd = ImageDraw.Draw(rays)
    for k in range(16):  # soft sun rays behind her
        a0 = math.radians(k * 22.5)
        a1 = a0 + math.radians(9)
        rd.polygon([(cx, cy - 150), (cx + 2200 * math.cos(a0), cy - 150 + 2200 * math.sin(a0)),
                    (cx + 2200 * math.cos(a1), cy - 150 + 2200 * math.sin(a1))], fill=38)
    rays = rays.filter(ImageFilter.GaussianBlur(30))
    img = Image.composite(Image.new("RGB", (S, S), (120, 170, 235)), img, rays)
    glow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(glow).ellipse((cx - 760, cy - 1000, cx + 760, cy + 480), fill=120)
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    return Image.composite(Image.new("RGB", (S, S), (255, 228, 130)), img, glow)


def blur_dot(img, box, color, strength=150, radius=18):
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).ellipse(box, fill=strength)
    return Image.composite(Image.new("RGB", (S, S), color), img, m.filter(ImageFilter.GaussianBlur(radius)))


def arm(d, x0, y0, x1, y1, hand=True):
    d.line((x0, y0, x1, y1), fill=YELLOW_EDGE, width=96)
    d.line((x0, y0, x1, y1), fill=YELLOW, width=70)
    if hand:
        d.ellipse((x1 - 70, y1 - 70, x1 + 70, y1 + 70), fill=YELLOW_EDGE)
        d.ellipse((x1 - 56, y1 - 56, x1 + 56, y1 + 56), fill=YELLOW)


def flower(d, x, y, r, petal, center=(255, 200, 40)):
    for k in range(6):
        a = math.radians(k * 60)
        px, py = x + r * 0.62 * math.cos(a), y + r * 0.62 * math.sin(a)
        d.ellipse((px - r * 0.5, py - r * 0.5, px + r * 0.5, py + r * 0.5), fill=petal)
    d.ellipse((x - r * 0.38, y - r * 0.38, x + r * 0.38, y + r * 0.38), fill=center)


def draw(variant: str) -> Image.Image:
    img = background()
    d = ImageDraw.Draw(img)
    bx, by, br = cx, cy - 150, 520

    # Ribbons of the flower crown hang behind her (drawn first).
    if variant == "vinok":
        for i, col in enumerate([(40, 110, 220), (255, 214, 0)]):
            x = bx - 330 - i * 70
            d.line((x, by - 380, x - 260 - i * 50, by + 420), fill=col, width=60)

    # Arms behind the body.
    if variant == "vinok":
        arm(d, bx + 400, by + 260, bx + 760, by - 120)   # raised, holding the bell
        arm(d, bx - 400, by + 260, bx - 700, by + 60)    # waving
    else:
        arm(d, bx + 400, by + 280, bx + 700, by + 120)   # holding the phone
        arm(d, bx - 400, by + 260, bx - 740, by - 140)   # waving hello

    # Body: glass + neck with an outline, shine.
    d.ellipse((bx - br - 20, by - br - 20, bx + br + 20, by + br + 20), fill=YELLOW_EDGE)
    d.polygon([(bx - 385, by + 300), (bx + 385, by + 300), (bx + 245, by + 720), (bx - 245, by + 720)], fill=YELLOW_EDGE)
    d.ellipse((bx - br, by - br, bx + br, by + br), fill=YELLOW)
    d.polygon([(bx - 365, by + 290), (bx + 365, by + 290), (bx + 230, by + 705), (bx - 230, by + 705)], fill=YELLOW)
    d.ellipse((bx - 400, by - 380, bx - 230, by - 210), fill=SHINE)

    # Base.
    top = by + 695
    for i, c in enumerate([(206, 216, 232), (150, 164, 188), (206, 216, 232)]):
        d.rounded_rectangle((bx - 260, top + i * 112, bx + 260, top + i * 112 + 94), radius=44, fill=c)
    d.rounded_rectangle((bx - 140, top + 336, bx + 140, top + 420), radius=40, fill=(150, 164, 188))

    # Face: big eyes with lashes, open smile, cheeks.
    for ex in (bx - 185, bx + 185):
        d.ellipse((ex - 80, by - 20, ex + 80, by + 165), fill=INK)
        d.ellipse((ex - 44, by + 10, ex + 6, by + 60), fill=(255, 255, 255))
        d.ellipse((ex + 18, by + 92, ex + 42, by + 116), fill=(255, 255, 255))
        side = 1 if ex > bx else -1
        for k in (-1, 0, 1):
            a = math.radians(-90 + side * 25 + k * 30)
            x0, y0 = ex + 70 * math.cos(a), by + 15 + 85 * math.sin(a)
            d.line((x0, y0, x0 + 58 * math.cos(a), y0 + 58 * math.sin(a)), fill=INK, width=22)
    d.chord((bx - 125, by + 170, bx + 125, by + 370), start=0, end=180, fill=INK)          # open smile
    d.chord((bx - 70, by + 270, bx + 70, by + 362), start=0, end=180, fill=(240, 110, 120))  # tongue
    for chx in (bx - 315, bx + 315):
        img = blur_dot(img, (chx - 90, by + 175, chx + 90, by + 270), (255, 120, 120))
    d = ImageDraw.Draw(img)

    if variant == "vinok":
        # Ukrainian flower crown (вінок) with ribbons.
        for k, (ang, col) in enumerate([(-160, (225, 50, 60)), (-135, (255, 255, 255)), (-112, (40, 110, 220)),
                                         (-90, (225, 50, 60)), (-68, (40, 110, 220)), (-45, (255, 255, 255)),
                                         (-20, (225, 50, 60))]):
            a = math.radians(ang)
            fx, fy = bx + (br + 10) * math.cos(a), by + (br + 10) * math.sin(a)
            la = a + math.radians(20)
            d.ellipse((fx + 95 * math.cos(la) - 55, fy + 95 * math.sin(la) - 30,
                       fx + 95 * math.cos(la) + 55, fy + 95 * math.sin(la) + 30), fill=(60, 150, 70))
            flower(d, fx, fy, 135 if k % 2 == 0 else 110, col)
        # Bell in the raised hand: the "notification".
        hx, hy = bx + 760, by - 120
        d.pieslice((hx - 150, hy - 250, hx + 150, hy + 80), start=180, end=360, fill=(255, 190, 40))
        d.rectangle((hx - 150, hy - 85, hx + 150, hy + 10), fill=(255, 190, 40))
        d.rounded_rectangle((hx - 185, hy + 5, hx + 185, hy + 55), radius=25, fill=(230, 160, 20))
        d.ellipse((hx - 40, hy + 40, hx + 40, hy + 120), fill=(230, 160, 20))
        for k in (-1, 1):  # ringing lines
            d.arc((hx - 270, hy - 290, hx + 270, hy + 150), start=200 if k < 0 else 300, end=240 if k < 0 else 340,
                  fill=(255, 255, 255), width=26)
    else:
        # Big bow on top, and a phone with a red alert dot.
        bow_x, bow_y = bx + 260, by - 470
        for side in (-1, 1):
            d.polygon([(bow_x, bow_y), (bow_x + side * 250, bow_y - 170), (bow_x + side * 250, bow_y + 170)],
                      fill=(40, 110, 220))
        d.ellipse((bow_x - 80, bow_y - 80, bow_x + 80, bow_y + 80), fill=(20, 70, 160))
        px, py = bx + 700, by + 120
        d.rounded_rectangle((px - 110, py - 210, px + 110, py + 170), radius=36, fill=(30, 36, 52))
        d.rounded_rectangle((px - 85, py - 175, px + 85, py + 120), radius=18, fill=(150, 200, 255))
        d.ellipse((px + 50, py - 260, px + 170, py - 140), fill=(230, 50, 60))
        d.text((px + 92, py - 248), "!", fill=(255, 255, 255))
        arm(d, bx + 400, by + 280, px - 60, py + 60, hand=True)  # hand in front of the phone

    return img.resize((OUT, OUT), Image.LANCZOS)


if __name__ == "__main__":
    variant, out = sys.argv[1], sys.argv[2]
    icon = draw(variant)
    icon.save(out, optimize=True)
    if len(sys.argv) > 3:
        mask = Image.new("L", (OUT, OUT), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, OUT, OUT), fill=255)
        preview = Image.new("RGB", (OUT, OUT), (240, 242, 245))
        preview.paste(icon, (0, 0), mask)
        preview.save(sys.argv[3])
