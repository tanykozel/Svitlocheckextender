"""Renders assets/demo/svitlo-demo.mp4: a Telegram-style replay of the bot.

The bot's replies come from the real Bot class (fed a scripted conversation), so the texts
match production. Address data is real (ZTOE lookup, 2026-10-13); the queue and the
schedule are illustrative.

    python assets/demo/make_demo.py assets/demo/svitlo-demo.mp4
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from svitlo_notifier.bot import Bot, BotState  # noqa: E402
from svitlo_notifier.planner import describe_event, schedule_text  # noqa: E402
from svitlo_notifier.schedule import KYIV, EventKind, merge, parse_slots, transitions  # noqa: E402

W, H = 720, 1280
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
AVATAR = Path(__file__).resolve().parents[1] / "lyusya-avatar.png"

BG, HEADER = (196, 220, 178), (255, 255, 255)
BOT_BUBBLE, USER_BUBBLE = (255, 255, 255), (225, 255, 199)
BUTTON, BUTTON_TEXT = (110, 160, 110), (255, 255, 255)
INK, MUTED, ACCENT = (20, 24, 28), (110, 120, 130), (42, 120, 214)

f_text = ImageFont.truetype(FONT, 25)
f_small = ImageFont.truetype(FONT, 19)
f_btn = ImageFont.truetype(FONT, 21)
f_head = ImageFont.truetype(BOLD, 27)
f_title = ImageFont.truetype(BOLD, 52)
f_sub = ImageFont.truetype(FONT, 28)
f_emoji = ImageFont.truetype(EMOJI, 109)


# --- text with colour emoji ---------------------------------------------------------------

def is_emoji(ch: str) -> bool:
    if len(ch) != 1:
        return False
    cp = ord(ch)
    return cp >= 0x1F300 or 0x2600 <= cp <= 0x27BF or 0x2300 <= cp <= 0x23FF


_emoji_cache: dict[tuple[str, int], Image.Image] = {}


def emoji_image(ch: str, size: int) -> Image.Image:
    key = (ch, size)
    if key not in _emoji_cache:
        canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((0, 0), ch, font=f_emoji, embedded_color=True)
        box = canvas.getbbox() or (0, 0, 1, 1)
        _emoji_cache[key] = canvas.crop(box).resize((size, size), Image.LANCZOS)
    return _emoji_cache[key]


def tokens(text: str) -> list[str]:
    """Split into emoji characters and plain-text runs (variation selectors dropped)."""
    out, run = [], ""
    for ch in text.replace("️", ""):
        if is_emoji(ch):
            if run:
                out.append(run)
                run = ""
            out.append(ch)
        else:
            run += ch
    if run:
        out.append(run)
    return out


def width(text: str, font: ImageFont.FreeTypeFont) -> int:
    em = int(font.size * 1.15)
    return sum(em if is_emoji(t) else int(font.getlength(t)) for t in tokens(text))


def wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            while width(word, font) > max_w:  # very long words (links) are broken by characters
                cut = len(word)
                while cut > 1 and width(word[:cut], font) > max_w:
                    cut -= 1
                if line:
                    lines.append(line)
                    line = ""
                lines.append(word[:cut])
                word = word[cut:]
            candidate = f"{line} {word}".strip()
            if width(candidate, font) <= max_w or not line:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def draw_line(img: Image.Image, xy: tuple[int, int], text: str, font, fill) -> None:
    x, y = xy
    d = ImageDraw.Draw(img)
    em = int(font.size * 1.15)
    for t in tokens(text):
        if is_emoji(t):
            img.paste(emoji_image(t, em), (x, y - 2), emoji_image(t, em))
            x += em
        else:
            d.text((x, y), t, font=font, fill=fill)
            x += int(font.getlength(t))


# --- chat model -----------------------------------------------------------------------------

class Msg:
    def __init__(self, who: str, text: str, buttons=None, time: str = ""):
        self.who, self.text, self.buttons, self.time = who, text, buttons or [], time
        self.tapped: str | None = None


def measure(m: Msg) -> tuple[int, int, list[str]]:
    max_w = 500
    lines = wrap(m.text, f_text, max_w - 40)
    w = min(max_w, max(width(l, f_text) for l in lines) + 40 + 60)
    h = 24 + len(lines) * 34 + 26
    if m.buttons:
        h += 10 + len(m.buttons) * 54
    return w, h, lines


def render(chat: list[Msg], caption: str = "", typing: bool = False) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Messages, newest at the bottom.
    y = H - 110 - (60 if typing else 0)
    for m in reversed(chat):
        w, h, lines = measure(m)
        y -= h + 14
        if y + h < 90:
            break
        if m.who == "bot":
            x = 18
            bubble_w = 500 if m.buttons else w
            d.rounded_rectangle((x, y, x + bubble_w, y + h - (10 + len(m.buttons) * 54 if m.buttons else 0)),
                                radius=20, fill=BOT_BUBBLE)
        else:
            x = W - 18 - w
            d.rounded_rectangle((x, y, x + w, y + h), radius=20, fill=USER_BUBBLE)
        for i, line in enumerate(lines):
            draw_line(img, (x + 20, y + 16 + i * 34), line, f_text, INK)
        text_bottom = y + 16 + len(lines) * 34
        d.text((x + (500 if m.who == "bot" and m.buttons else w) - 70, text_bottom - 4), m.time, font=f_small,
               fill=MUTED)
        if m.buttons:
            by = text_bottom + 26
            for row in m.buttons:
                bw = (500 - 8 * (len(row) - 1)) // len(row)
                for j, label in enumerate(row):
                    bx = 18 + j * (bw + 8)
                    color = (70, 130, 70) if m.tapped == label else BUTTON
                    d.rounded_rectangle((bx, by, bx + bw, by + 46), radius=12, fill=color)
                    tw = d.textlength(label, font=f_btn)
                    d.text((bx + (bw - tw) / 2, by + 11), label, font=f_btn, fill=BUTTON_TEXT)
                    if m.tapped == label:
                        cxp, cyp = bx + bw / 2, by + 23
                        d.ellipse((cxp - 30, cyp - 30, cxp + 30, cyp + 30), outline=(255, 255, 255), width=4)
                by += 54

    if typing:
        d.rounded_rectangle((18, H - 160, 230, H - 115), radius=18, fill=BOT_BUBBLE)
        d.text((36, H - 150), "бот пише…", font=f_small, fill=MUTED)

    # Header with avatar.
    d.rectangle((0, 0, W, 90), fill=HEADER)
    avatar = Image.open(AVATAR).convert("RGB").resize((60, 60), Image.LANCZOS)
    mask = Image.new("L", (60, 60), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 60, 60), fill=255)
    img.paste(avatar, (20, 15), mask)
    d.text((95, 16), "Світло Люся 💡".replace(" 💡", ""), font=f_head, fill=INK)
    d.text((95, 52), "бот", font=f_small, fill=MUTED)

    # Input bar with the Menu button.
    d.rectangle((0, H - 95, W, H), fill=HEADER)
    d.rounded_rectangle((18, H - 75, 160, H - 22), radius=26, fill=ACCENT)
    d.text((40, H - 63), "☰ Menu", font=f_btn, fill=(255, 255, 255))
    d.text((190, H - 62), "Повідомлення", font=f_text, fill=(170, 175, 180))

    if caption:
        band = Image.new("RGBA", (W, 90), (15, 35, 70, 225))
        img.paste(band, (0, 96), band)
        tw = width(caption, f_sub)
        draw_line(img, ((W - tw) // 2, 120), caption, f_sub, (255, 255, 255))
    return img


def card(title: str, lines: list[str]) -> Image.Image:
    img = Image.new("RGB", (W, H), (14, 40, 84))
    d = ImageDraw.Draw(img)
    avatar = Image.open(AVATAR).convert("RGB").resize((260, 260), Image.LANCZOS)
    mask = Image.new("L", (260, 260), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 260, 260), fill=255)
    img.paste(avatar, ((W - 260) // 2, 170), mask)
    y = 470
    for part in wrap(title, f_title, W - 80):
        tw = d.textlength(part, font=f_title)
        d.text(((W - tw) / 2, y), part, font=f_title, fill=(255, 214, 0))
        y += 66
    y += 50
    for line in lines:
        for part in wrap(line, f_sub, W - 120):
            draw_line(img, (60, y), part, f_sub, (230, 236, 245))
            y += 44
        y += 14
    return img


# --- conversation, produced by the real bot ---------------------------------------------------

REMS = ["Андрушівський", "Баранівський", "Бердичівський", "Брусилівський", "Житомирський", "Звягельський",
        "Коростенський", "Коростишівський", "Любарський", "Малинський", "Овруцький", "Олевський",
        "Попільнянський", "Пулинський", "Радомишльський", "Романівський", "Хорошівський", "Черняхівський",
        "Чуднівський"]
STREETS = ["Аки Камбарова", "Вишнева", "Гранітна", "Зарічна", "Захисників України", "Західна", "Звягельська",
           "Зелена", "Івана Тимощука", "Лісова", "Незалежності", "Нова", "Поліська", "Польова", "Садова",
           "Суслівська", "Східна", "Центральна", "Я.Купала"]
DAY = datetime(2026, 10, 13, tzinfo=KYIV)


def slots(day: datetime, outages: list[tuple[int, int]]) -> list[dict]:
    out = []
    for i in range(48):
        h, m = divmod(i * 30, 60)
        eh, em = divmod((i + 1) * 30, 60)
        red = any(a <= h < b for a, b in outages)
        out.append({"date": f"{day:%d.%m.%Y}", "span": f"{h:02d}:{m:02d}-{eh:02d}:{em:02d}",
                    "color": "red" if red else "white"})
    return out


SCHEDULE = slots(DAY, [(14, 18), (22, 24)]) + slots(DAY + timedelta(days=1), [(6, 10)])


class DemoDirectory:
    def rems(self):
        return [{"id": str(i), "name": n} for i, n in enumerate(REMS)]

    def cities(self, rem_id):
        return [{"id": "16823", "name": "м. Звягель"}, {"id": "17039", "name": "селище Городниця"},
                {"id": "17040", "name": "селище Ємільчине"}, {"id": "17041", "name": "селище Яблунець"},
                {"id": "17012", "name": "с. Сусли"}]

    def streets(self, city_id):
        return [{"id": str(179875 + i), "name": f"вул. {n}"} for i, n in enumerate(STREETS)]

    def addresses(self, street_id):
        return [{"id": "1", "name": "10 - побутові споживачі, 12 - побутові споживачі", "cherga": 3, "pidcherga": 1},
                {"id": "2", "name": "14 - побутові споживачі", "cherga": 4, "pidcherga": 2}]

    def schedule(self, queue, subqueue):
        return SCHEDULE


def main(out: str) -> None:
    replies: list[tuple[str, list]] = []
    bot = Bot(DemoDirectory(), lambda chat, text, buttons: replies.append((text, buttons)) or len(replies),
              BotState())

    def ask(text: str = "", button: str = "") -> list[tuple[str, list]]:
        replies.clear()
        if button:
            bot.handle_button(1, button)
        else:
            bot.handle_text(1, text)
        return list(replies)

    def labels(buttons):
        return [[label for label, _ in row] for row in (buttons or [])]

    frames: list[tuple[Image.Image, float]] = []
    chat: list[Msg] = []
    clock = iter(f"15:{m:02d}" for m in range(20, 60))

    def show(seconds: float, caption: str = "", typing: bool = False):
        frames.append((render(chat, caption, typing), seconds))

    def user(text: str, caption: str = ""):
        chat.append(Msg("user", text, time=next(clock)))
        show(1.2, caption)
        show(0.8, caption, typing=True)

    def bot_says(replies_, caption: str = "", hold: float = 2.6):
        if any(buttons for _t, buttons in replies_):
            for m in chat:  # like the real bot: new buttons retire the old ones
                m.buttons = []
        for text, buttons in replies_:
            chat.append(Msg("bot", text, labels(buttons), time=next(clock)))
        show(hold, caption)

    def tap(label: str, caption: str = ""):
        for m in reversed(chat):
            if any(label in row for row in m.buttons):
                m.tapped = label
                break
        show(1.0, caption)

    frames.append((card("Світло Люся", [
        "💡 Привіт! Я попереджаю про відключення світла за графіком Житомиробленерго.",
        "Демо: реальні адреси, графік - для прикладу.",
    ]), 4.0))

    user("/start", "1. Обираємо адресу за 4 кроки")
    bot_says(ask("/start"), "1. Обираємо адресу за 4 кроки", hold=3.0)
    tap("Звягельський", "Крок 1: район")
    bot_says(ask(button="r:5"), "Крок 2: місто або село")
    user("сусли", "Крок 2: можна просто написати")
    bot_says(ask("сусли"), "Крок 3: вулиця", hold=3.0)
    tap("вул. Центральна", "Крок 3: вулиця")
    bot_says(ask(button="s:179892"), "Крок 4: номер будинку")
    user("12", "Крок 4: номер будинку")
    bot_says(ask("12"), "✅ Підписано! Черга визначена автоматично", hold=3.5)

    user("/schedule", "Графік на сьогодні й завтра")
    sub = bot.state.subs["1"]
    chat.append(Msg("bot", schedule_text(SCHEDULE, DAY.replace(hour=13, minute=20),
                                         f"{sub.label}, черга {sub.queue}.{sub.subqueue}"), time=next(clock)))
    show(4.5, "Графік на сьогодні й завтра")

    timeline = merge(parse_slots(SCHEDULE))
    events = transitions(timeline)
    off = next(e for e in events if e.kind == EventKind.OFF)
    on = next(e for e in events if e.kind == EventKind.ON and e.at >= off.until)
    next_off = next(e for e in events if e.kind != EventKind.ON and e.at > on.at)
    frames.append((card("…за 30 хв до вимкнення", ["Люся сама надсилає попередження - нічого не треба відкривати."]),
                   2.2))
    chat.append(Msg("bot", describe_event(off, off.at - timedelta(minutes=30), sub.label), time="13:30"))
    show(4.0, "🔴 Попередження: скільки триватиме")
    chat.append(Msg("bot", describe_event(on, on.at - timedelta(minutes=30), sub.label, next_off), time="17:30"))
    show(4.0, "🟢 Світло повертається + наступне вимкнення")

    frames.append((card("Що вміє Люся", [
        "🔴 Попереджає за 15 / 30 / 60 хв до вимкнення і ввімкнення",
        "⏱ Каже, скільки триватиме відключення",
        "📅 Графік на сьогодні й завтра + посилання на ZTOE",
        "⚠️ Сама помічає, якщо змінилась черга адреси",
        "👥 Друзі підписуються самі: одна адреса, змінити - /change",
    ]), 6.0))

    with tempfile.TemporaryDirectory() as tmp:
        listing = []
        for i, (img, seconds) in enumerate(frames):
            path = Path(tmp) / f"f{i:03d}.png"
            img.save(path)
            listing += [f"file '{path}'", f"duration {seconds}"]
        listing.append(f"file '{Path(tmp) / f'f{len(frames) - 1:03d}.png'}'")
        (Path(tmp) / "list.txt").write_text("\n".join(listing))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(Path(tmp) / "list.txt"), "-vf", "fps=30,format=yuv420p",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "23", "-movflags", "+faststart", out],
                       check=True)
        # Keep a few stills for quick review.
        stills = Path(out).with_suffix("")
        if len(sys.argv) > 2:
            stills = Path(sys.argv[2])
            stills.mkdir(parents=True, exist_ok=True)
            for i, (img, _s) in enumerate(frames):
                img.save(stills / f"frame{i:02d}.png")
    print(f"{out}: {sum(s for _, s in frames):.0f} s, {len(frames)} scenes")


if __name__ == "__main__":
    shutil.which("ffmpeg") or sys.exit("ffmpeg is required")
    main(sys.argv[1])
