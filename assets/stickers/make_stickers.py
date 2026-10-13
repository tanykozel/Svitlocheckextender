"""Світло Люся sticker set: 512x512 transparent PNGs, Telegram sticker format.

    python assets/stickers/make_stickers.py assets/stickers
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

N = 2048                      # drawing canvas; downscaled to 512
U = N / 1000                  # 1 unit = 1/1000 of the canvas
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
INK = (44, 40, 64, 255)
ON = ((255, 212, 20, 255), (228, 158, 0, 255), (255, 243, 170, 255))
OFF = ((205, 210, 222, 255), (150, 158, 176, 255), (235, 238, 245, 255))


def u(*v):
    return [x * U for x in v]


def body(d, lit=True, cx=500, cy=430):
    fill, edge, shine = ON if lit else OFF
    r = 250
    d.ellipse(u(cx - r - 10, cy - r - 10, cx + r + 10, cy + r + 10), fill=edge)
    d.polygon([tuple(u(cx - 185, cy + 140)), tuple(u(cx + 185, cy + 140)), tuple(u(cx + 118, cy + 345)),
               tuple(u(cx - 118, cy + 345))], fill=edge)
    d.ellipse(u(cx - r, cy - r, cx + r, cy + r), fill=fill)
    d.polygon([tuple(u(cx - 175, cy + 135)), tuple(u(cx + 175, cy + 135)), tuple(u(cx + 110, cy + 338)),
               tuple(u(cx - 110, cy + 338))], fill=fill)
    d.ellipse(u(cx - 190, cy - 180, cx - 110, cy - 100), fill=shine)
    top = cy + 335
    for i, c in enumerate([(206, 216, 232, 255), (150, 164, 188, 255), (206, 216, 232, 255)]):
        d.rounded_rectangle(u(cx - 125, top + i * 54, cx + 125, top + i * 54 + 45), radius=22 * U, fill=c)
    d.rounded_rectangle(u(cx - 66, top + 162, cx + 66, top + 202), radius=20 * U, fill=(150, 164, 188, 255))


def vinok(d, cx=500, cy=430):
    for k, (ang, col) in enumerate([(-160, (225, 50, 60)), (-130, (255, 255, 255)), (-105, (40, 110, 220)),
                                     (-80, (225, 50, 60)), (-55, (40, 110, 220)), (-28, (255, 255, 255))]):
        a = math.radians(ang)
        fx, fy = cx + 258 * math.cos(a), cy + 258 * math.sin(a)
        rr = 60 if k % 2 == 0 else 50
        d.ellipse(u(fx + 30, fy - 14, fx + 80, fy + 14), fill=(60, 150, 70, 255))
        for j in range(6):
            b = math.radians(j * 60)
            px, py = fx + rr * 0.62 * math.cos(b), fy + rr * 0.62 * math.sin(b)
            d.ellipse(u(px - rr * 0.5, py - rr * 0.5, px + rr * 0.5, py + rr * 0.5), fill=col + (255,))
        d.ellipse(u(fx - rr * 0.38, fy - rr * 0.38, fx + rr * 0.38, fy + rr * 0.38), fill=(255, 200, 40, 255))


def eyes(d, kind, cx=500, cy=430):
    for ex in (cx - 88, cx + 88):
        side = 1 if ex > cx else -1
        if kind == "closed":
            d.arc(u(ex - 42, cy - 10, ex + 42, cy + 60), start=200, end=340, fill=INK, width=int(14 * U))
            continue
        if kind == "wink" and side == 1:
            d.arc(u(ex - 42, cy + 10, ex + 42, cy + 70), start=200, end=340, fill=INK, width=int(14 * U))
            continue
        big = 1.25 if kind == "wide" else 1.0
        d.ellipse(u(ex - 38 * big, cy - 10 * big, ex + 38 * big, cy + 78 * big), fill=INK)
        d.ellipse(u(ex - 20, cy + 4, ex + 4, cy + 28), fill=(255, 255, 255, 255))
        if kind == "heart":
            d.ellipse(u(ex - 38, cy - 10, ex + 38, cy + 78), fill=(0, 0, 0, 0))
            heart(d, ex, cy + 30, 36, (230, 50, 80, 255))
            continue
        for k in (-1, 0, 1):
            a = math.radians(-90 + side * 25 + k * 30)
            x0, y0 = ex + 34 * math.cos(a), cy + 6 + 42 * math.sin(a)
            d.line(u(x0, y0, x0 + 28 * math.cos(a), y0 + 28 * math.sin(a)), fill=INK, width=int(10 * U))


def mouth(d, kind, cx=500, cy=430):
    if kind == "open":
        d.chord(u(cx - 60, cy + 82, cx + 60, cy + 178), start=0, end=180, fill=INK)
        d.chord(u(cx - 34, cy + 130, cx + 34, cy + 175), start=0, end=180, fill=(240, 110, 120, 255))
    elif kind == "o":
        d.ellipse(u(cx - 30, cy + 100, cx + 30, cy + 170), fill=INK)
    elif kind == "sad":
        d.arc(u(cx - 55, cy + 125, cx + 55, cy + 200), start=200, end=340, fill=INK, width=int(14 * U))
    else:  # smile
        d.arc(u(cx - 70, cy + 40, cx + 70, cy + 160), start=20, end=160, fill=INK, width=int(15 * U))


def cheeks(img, cx=500, cy=430, color=(255, 120, 120)):
    m = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(m)
    for chx in (cx - 150, cx + 150):
        md.ellipse(u(chx - 44, cy + 85, chx + 44, cy + 130), fill=140)
    m = m.filter(ImageFilter.GaussianBlur(8 * U))
    layer = Image.new("RGBA", img.size, color + (255,))
    img.paste(layer, (0, 0), m)


def arm(d, x0, y0, x1, y1, lit=True):
    fill, edge, _ = ON if lit else OFF
    d.line(u(x0, y0, x1, y1), fill=edge, width=int(46 * U))
    d.line(u(x0, y0, x1, y1), fill=fill, width=int(32 * U))
    d.ellipse(u(x1 - 32, y1 - 32, x1 + 32, y1 + 32), fill=edge)
    d.ellipse(u(x1 - 25, y1 - 25, x1 + 25, y1 + 25), fill=fill)


def heart(d, x, y, r, color):
    d.ellipse(u(x - r, y - r * 0.9, x, y + r * 0.1), fill=color)
    d.ellipse(u(x, y - r * 0.9, x + r, y + r * 0.1), fill=color)
    d.polygon([tuple(u(x - r * 0.98, y - r * 0.25)), tuple(u(x + r * 0.98, y - r * 0.25)), tuple(u(x, y + r))],
              fill=color)


def glow(img, cx=500, cy=430, color=(255, 225, 110)):
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).ellipse(u(cx - 330, cy - 330, cx + 330, cy + 330), fill=170)
    m = m.filter(ImageFilter.GaussianBlur(60 * U))
    img.paste(Image.new("RGBA", img.size, color + (255,)), (0, 0), m)


def caption(img, text):
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(BOLD, int(86 * U))
    w = d.textlength(text, font=font)
    x, y = (N - w) / 2, 880 * U
    d.text((x, y), text, font=font, fill=(255, 255, 255, 255), stroke_width=int(14 * U), stroke_fill=(30, 60, 130, 255))


def sticker(name: str) -> Image.Image:
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    lit = name != "off"
    if lit and name != "alert":
        glow(img)
    d = ImageDraw.Draw(img)

    if name == "on":
        for k in range(10):  # sparkle rays
            a = math.radians(k * 36)
            d.line(u(500 + 330 * math.cos(a), 430 + 330 * math.sin(a), 500 + 400 * math.cos(a), 430 + 400 * math.sin(a)),
                   fill=(255, 200, 30, 255), width=int(18 * U))
        arm(d, 690, 560, 860, 330); arm(d, 310, 560, 140, 330)
    elif name == "back":
        arm(d, 690, 560, 870, 360); arm(d, 310, 560, 150, 640)
    elif name == "alert":
        arm(d, 690, 560, 870, 340); arm(d, 310, 560, 140, 640)
    elif name == "calendar":
        arm(d, 310, 560, 140, 640)
    elif name == "battery":
        arm(d, 310, 560, 140, 640)
    elif name == "thanks":
        arm(d, 690, 560, 600, 700); arm(d, 310, 560, 400, 700)

    body(d, lit)
    vinok(d)
    cheeks(img, color=(255, 120, 120) if lit else (190, 180, 210))
    d = ImageDraw.Draw(img)
    face = {"on": ("normal", "open"), "off": ("closed", "sad"), "alert": ("wide", "o"), "back": ("wink", "open"),
            "calendar": ("normal", "smile"), "battery": ("normal", "smile"), "thanks": ("heart", "open")}[name]
    eyes(d, face[0]); mouth(d, face[1])

    if name == "off":
        f = ImageFont.truetype(BOLD, int(80 * U))
        for i, (x, y, s) in enumerate([(720, 210, 1.0), (790, 130, 0.8), (845, 65, 0.6)]):
            d.text(u(x, y), "Z", font=ImageFont.truetype(BOLD, int(80 * s * U)), fill=(120, 140, 200, 255),
                   stroke_width=int(6 * U), stroke_fill=(255, 255, 255, 255))
    elif name == "alert":  # ringing bell in the raised hand
        hx, hy = 870, 300
        d.pieslice(u(hx - 70, hy - 110, hx + 70, hy + 40), start=180, end=360, fill=(255, 190, 40, 255))
        d.rectangle(u(hx - 70, hy - 36, hx + 70, hy + 6), fill=(255, 190, 40, 255))
        d.rounded_rectangle(u(hx - 86, hy + 2, hx + 86, hy + 26), radius=12 * U, fill=(230, 160, 20, 255))
        d.ellipse(u(hx - 18, hy + 18, hx + 18, hy + 54), fill=(230, 160, 20, 255))
        for a0, a1 in ((205, 240), (300, 335)):
            d.arc(u(hx - 125, hy - 135, hx + 125, hy + 75), start=a0, end=a1, fill=(230, 60, 60, 255), width=int(14 * U))
    elif name == "calendar":
        x0, y0 = 690, 470
        d.rounded_rectangle(u(x0, y0, x0 + 230, y0 + 230), radius=24 * U, fill=(255, 255, 255, 255),
                            outline=(40, 110, 220, 255), width=int(10 * U))
        d.rectangle(u(x0 + 5, y0 + 5, x0 + 225, y0 + 62), fill=(40, 110, 220, 255))
        for r in range(3):
            for c in range(3):
                col = (230, 60, 60, 255) if (r, c) in ((1, 1), (2, 0)) else (190, 200, 220, 255)
                d.rectangle(u(x0 + 25 + c * 65, y0 + 80 + r * 48, x0 + 70 + c * 65, y0 + 115 + r * 48), fill=col)
        arm(d, 690, 560, 700, 600)
    elif name == "battery":
        x0, y0 = 700, 470
        d.rounded_rectangle(u(x0, y0, x0 + 140, y0 + 250), radius=20 * U, fill=(40, 46, 64, 255))
        d.rectangle(u(x0 + 45, y0 - 22, x0 + 95, y0), fill=(40, 46, 64, 255))
        for k in range(3):
            d.rectangle(u(x0 + 20, y0 + 170 - k * 70, x0 + 120, y0 + 225 - k * 70), fill=(70, 200, 90, 255))
        d.polygon([tuple(u(x0 + 80, y0 + 40)), tuple(u(x0 + 45, y0 + 135)), tuple(u(x0 + 75, y0 + 135)),
                   tuple(u(x0 + 60, y0 + 215)), tuple(u(x0 + 100, y0 + 110)), tuple(u(x0 + 70, y0 + 110))],
                  fill=(255, 220, 40, 255))
        arm(d, 690, 560, 710, 600)
    elif name == "thanks":
        heart(d, 820, 220, 70, (230, 50, 80, 255))
        heart(d, 180, 260, 45, (230, 50, 80, 255))

    caption(img, {"on": "Світло є!", "off": "Мене вимкнули", "alert": "Увага!", "back": "Я повернулась!",
                  "calendar": "Графік", "battery": "Заряджай!", "thanks": "Дякую!"}[name])
    return img.resize((512, 512), Image.LANCZOS)


NAMES = ["on", "off", "alert", "back", "calendar", "battery", "thanks"]

if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    tiles = []
    for i, name in enumerate(NAMES, start=1):
        st = sticker(name)
        st.save(out / f"{i:02d}-{name}.png", optimize=True)
        tiles.append(st)
    sheet = Image.new("RGBA", (512 * 4, 512 * 2), (225, 236, 220, 255))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % 4) * 512, (i // 4) * 512), t)
    sheet.convert("RGB").resize((1024, 512), Image.LANCZOS).save(out / "preview-sheet.png")
    print(f"{len(tiles)} stickers -> {out}")
