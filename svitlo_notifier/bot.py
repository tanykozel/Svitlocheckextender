"""Multi-user Telegram bot: friends pick their address in a quiz and get alerts for their queue.

Runs in short ticks (e.g. every 5-10 minutes on GitHub Actions): each tick reads the
messages and button taps that arrived since the last tick, answers them, then sends the
outage alerts that are due for every subscriber. Nothing runs between ticks, so replies
arrive on the next tick rather than instantly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Protocol

from .api import ApiError
from .planner import (SCHEDULE_URL, Settings, State, by_day, describe_day, describe_event, plan, schedule_text,
                      summary)
from .secure import chat_tag
from .schedule import KYIV, Event, EventKind, merge, transitions

MAX_BUTTONS = 30
MENU_VERSION = 5  # bump on every MENU change so Telegram's menu is refreshed
CHECK_EVERY_MIN = 10  # how often the scheduled job runs (.github/workflows/notify.yml)
LEAD_CHOICES = (15, 30, 60)
MENU = [
    ("start", "Обрати адресу"),
    ("schedule", "Графік на сьогодні й завтра"),
    ("status", "Стан за графіком"),
    ("settings", "Коли попереджати"),
    ("change", "Змінити адресу"),
    ("stop", "Відписатися"),
    ("help", "Про Люсю і допомога"),
]
DEFAULT_LEAD = 30
Buttons = list[list[tuple[str, str]]]


class Directory(Protocol):
    def rems(self) -> list[dict]: ...
    def cities(self, rem_id: str) -> list[dict]: ...
    def streets(self, city_id: str) -> list[dict]: ...
    def addresses(self, street_id: str) -> list[dict]: ...
    def schedule(self, queue: int, subqueue: int) -> list[dict]: ...


Send = Callable[[int, str, Buttons | None], "int | None"]  # returns the sent message id, if known
Unbutton = Callable[[int, int], None]  # remove the buttons under (chat id, message id)


# --- text helpers ----------------------------------------------------------------

_PREFIX = re.compile(r"^(м\.|с\.|смт\.?|селище|село|місто|вул\.|вулиця|пров\.|провулок|просп\.|пл\.)\s*")


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("ʼ", "'").replace("`", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return _PREFIX.sub("", text).strip()


def house_numbers(raw: str) -> list[str]:
    """'25 - побутові споживачі, 27А - побутові споживачі' -> ['25', '27а']."""
    numbers = []
    for part in raw.split(","):
        part = re.sub(r"\s*-\s*[\w\s]*споживачі\s*$", "", part.strip()).strip()
        if part:
            numbers.append(normalize(part).replace(" ", ""))
    return numbers


def match(options: list[dict], query: str) -> list[dict]:
    """Exact name match wins; otherwise every option containing the typed text."""
    q = normalize(query)
    if not q:
        return []
    exact = [o for o in options if normalize(str(o.get("name", ""))) == q]
    return exact or [o for o in options if q in normalize(str(o.get("name", "")))]


def as_buttons(options: list[dict], prefix: str, per_row: int = 2) -> Buttons:
    rows: Buttons = []
    for i in range(0, len(options), per_row):
        rows.append([(str(o["name"])[:60], f"{prefix}:{o['id']}") for o in options[i : i + per_row]])
    return rows


def resolve_queue(rows: list[dict], house: str) -> tuple[int, int] | str:
    """The queue for a house on a street, or "missing" / "ambiguous" when it can't be decided."""
    queues = {(int(r["cherga"]), int(r["pidcherga"])) for r in rows if r.get("cherga") is not None}
    if house:
        for row in rows:
            if row.get("cherga") is not None and house in house_numbers(str(row.get("name", ""))):
                return int(row["cherga"]), int(row["pidcherga"])
        return "missing"
    if len(queues) == 1:
        return next(iter(queues))
    return "ambiguous" if queues else "missing"


RESET_COMMANDS = {"/start", "/subscribe", "/change", "/address", "/stop"}


def _kind(update: dict) -> tuple[int | None, str, bool]:
    """(chat id, request kind, starts over?) - e.g. (42, "/start", True) or (42, "btn:r", False)."""
    if "callback_query" in update:
        query = update["callback_query"]
        chat = ((query.get("message") or {}).get("chat") or {}).get("id")
        data = str(query.get("data", ""))
        return chat, f"btn:{data.partition(':')[0]}", data == "a:change"
    message = update.get("message") or {}
    text = str(message.get("text", "")).strip()
    chat = (message.get("chat") or {}).get("id")
    command = text.split()[0].lower().split("@")[0] if text.startswith("/") else ""
    return chat, command or "text", command in RESET_COMMANDS


def latest_requests(updates: list[dict]) -> list[dict]:
    """Keep only what each chat asked for most recently.

    Between two runs a user may tap or type several times (often because the bot looked silent).
    For each chat: everything before its last "start over" request (/start, /change, /stop) is dropped,
    and of back-to-back requests of the same kind (two /start, two district taps) only the last is kept.
    """
    kinds = [_kind(u) for u in updates]
    last_reset: dict[int, int] = {}
    for i, (chat, _kind_name, resets) in enumerate(kinds):
        if resets:
            last_reset[chat] = i
    kept: list[int] = []
    for i, (chat, kind_name, _resets) in enumerate(kinds):
        if chat in last_reset and i < last_reset[chat]:
            continue
        previous = next((j for j in reversed(kept) if kinds[j][0] == chat), None)
        if previous is not None and kinds[previous][1] == kind_name and kind_name != "text":
            kept.remove(previous)  # same kind again: the newer one replaces it
        kept.append(i)
    return [updates[i] for i in kept]


# --- persisted state ----------------------------------------------------------------


@dataclass
class Subscription:
    """One address per chat. Choosing a new address replaces the old one."""

    queue: int
    subqueue: int
    label: str
    alerts: State = field(default_factory=State)
    lead_minutes: int = DEFAULT_LEAD
    # Where the queue came from, so it can be re-checked: ZTOE sometimes moves addresses
    # to another queue. An empty street_id (owner set via variables) is never re-checked.
    street_id: str = ""
    house: str = ""  # normalized house number; empty when the whole street is one queue
    checked_at: str = ""  # ISO time of the last re-check
    problem: str = ""  # "missing" / "ambiguous" once reported, so the user is told only once

    def to_dict(self) -> dict:
        return {"queue": self.queue, "subqueue": self.subqueue, "label": self.label,
                "lead_minutes": self.lead_minutes, "street_id": self.street_id, "house": self.house,
                "checked_at": self.checked_at, "problem": self.problem, "alerts": self.alerts.to_dict()}

    @classmethod
    def from_dict(cls, raw: dict) -> "Subscription":
        return cls(int(raw["queue"]), int(raw["subqueue"]), str(raw.get("label", "")),
                   State.from_dict(raw.get("alerts", {})), int(raw.get("lead_minutes", DEFAULT_LEAD)),
                   str(raw.get("street_id", "")), str(raw.get("house", "")),
                   str(raw.get("checked_at", "")), str(raw.get("problem", "")))


@dataclass
class BotState:
    offset: int | None = None
    bot_id: int | None = None  # which Telegram bot this state belongs to (offsets are per bot)
    menu_version: int = 0  # bumped when MENU changes, so Telegram is updated once
    subs: dict[str, Subscription] = field(default_factory=dict)  # chat id -> subscription
    sessions: dict[str, dict] = field(default_factory=dict)  # chat id -> quiz progress
    keyboards: dict[str, int] = field(default_factory=dict)  # chat id -> message with the live buttons

    def switch_bot(self, bot_id: int) -> bool:
        """Adopt a new bot token. Returns True if the bot changed.

        Message counters, live buttons, half-finished quizzes and the menu belong to the old bot and
        are reset; subscriptions are kept (a private chat id is the user's id, the same for any bot),
        so people keep their address once they press Start in the new bot.
        """
        if self.bot_id == bot_id:
            return False
        changed = self.bot_id is not None
        self.bot_id = bot_id
        if changed:
            self.offset, self.keyboards, self.sessions, self.menu_version = None, {}, {}, 0
        return changed

    def to_dict(self) -> dict:
        return {"offset": self.offset, "bot_id": self.bot_id, "menu_version": self.menu_version,
                "subs": {k: v.to_dict() for k, v in self.subs.items()},
                "sessions": self.sessions, "keyboards": self.keyboards}

    @classmethod
    def from_dict(cls, raw: dict) -> "BotState":
        return cls(raw.get("offset"), raw.get("bot_id"), int(raw.get("menu_version", 0)),
                   {k: Subscription.from_dict(v) for k, v in raw.get("subs", {}).items()},
                   dict(raw.get("sessions", {})),
                   {k: int(v) for k, v in raw.get("keyboards", {}).items()})


# --- conversation ---------------------------------------------------------------------

NOT_UNDERSTOOD = "Я тебе не розумію 🙈 Обери команду з меню ☰ (кнопка «Menu» внизу) або надішли /help."

HELP = (
    "Привіт, я Лампочка Люся 💡\n"
    "Попереджаю про відключення світла за графіком Житомиробленерго: заздалегідь до вимкнення "
    "і до ввімкнення, кажу, скільки мене не буде, і повідомляю, коли графік змінюється.\n\n"
    "/start - обрати адресу (одна на людину)\n"
    "/change - змінити адресу\n"
    "/schedule - графік на сьогодні й завтра\n"
    "/status - стан за графіком зараз (без урахування аварійних відключень)\n"
    "/settings - за скільки хвилин попереджати\n"
    "/stop - відписатися\n\n"
    f"Графік перевіряю приблизно кожні {CHECK_EVERY_MIN} хв, тож відповідаю не миттєво - трохи терпіння 🙏\n"
    "Аварійні відключення, на жаль, передбачити не можу.\n"
    f"Повний графік: {SCHEDULE_URL}"
)


class Bot:
    def __init__(self, directory: Directory, send: Send, state: BotState,
                 unbutton: Unbutton = lambda _chat, _message: None) -> None:
        self.dir = directory
        self._send = send
        self._unbutton = unbutton
        self.state = state

    def retire_buttons(self, chat_id: int) -> None:
        """Remove the buttons from the bot's last message with buttons, if any."""
        message_id = self.state.keyboards.pop(str(chat_id), None)
        if message_id is not None:
            self._unbutton(chat_id, message_id)

    def send(self, chat_id: int, text: str, buttons: Buttons | None) -> None:
        """Send a message. A new set of buttons retires the previous one, so only the latest can be tapped."""
        chat = str(chat_id)
        if buttons and chat in self.state.keyboards:
            self._unbutton(chat_id, self.state.keyboards.pop(chat))
        message_id = self._send(chat_id, text, buttons)
        if buttons and message_id is not None:
            self.state.keyboards[chat] = int(message_id)

    def _session(self, chat: str) -> dict:
        return self.state.sessions.setdefault(chat, {})

    # entry points --------------------------------------------------------------------

    def handle_text(self, chat_id: int, text: str) -> None:
        chat = str(chat_id)
        command = text.strip().split()[0].lower().split("@")[0] if text.strip().startswith("/") else ""
        if command in ("/start", "/subscribe"):
            self.start(chat_id)
        elif command in ("/change", "/address"):
            self.ask_rem(chat_id)
        elif command == "/settings":
            self.ask_lead(chat_id)
        elif command == "/schedule":
            self.schedule(chat_id)
        elif command in ("/test", "/demo"):
            self.demo(chat_id)
        elif command == "/stop":
            self.state.subs.pop(chat, None)
            self.state.sessions.pop(chat, None)
            self.send(chat_id, "Добре, більше не турбуватиму 💤 Захочеш повернути мене - надішли /start.", None)
        elif command == "/status":
            self.status(chat_id)
        elif command == "/help":
            self.send(chat_id, HELP, None)
        elif command:  # any other /command, even mid-quiz, is not an answer
            self.send(chat_id, NOT_UNDERSTOOD, None)
        else:
            step = self._session(chat).get("step")
            if step == "rem":
                self.pick_rem_by_text(chat_id, text)
            elif step == "city":
                self.pick_city_by_text(chat_id, text)
            elif step == "street":
                self.pick_street_by_text(chat_id, text)
            elif step == "house":
                self.pick_house(chat_id, text)
            else:
                self.send(chat_id, NOT_UNDERSTOOD, None)

    def handle_button(self, chat_id: int, data: str) -> None:
        kind, _, value = data.partition(":")
        if data == "a:change":
            self.ask_rem(chat_id)
        elif data == "a:keep":
            self.retire_buttons(chat_id)
            self.send(chat_id, "Добре, залишаю твою адресу як є 👌", None)
        elif kind == "l":
            self.lead_chosen(chat_id, value)
        elif kind == "r":
            self.rem_chosen(chat_id, value)
        elif kind == "c":
            self.city_chosen(chat_id, value)
        elif kind == "s":
            self.street_chosen(chat_id, value)

    # quiz steps ------------------------------------------------------------------------

    def start(self, chat_id: int) -> None:
        sub = self.state.subs.get(str(chat_id))
        if sub is None:
            self.send(chat_id, "Привіт! Я Лампочка Люся 💡 Знайду твою адресу за 4 кроки і попереджатиму, коли мене вимикатимуть і вмикатимуть.", None)
            self.ask_rem(chat_id)
            return
        # No question here: changing the address is the user's own choice via the menu (/change).
        self.retire_buttons(chat_id)  # e.g. an old "Змінити / Залишити" question
        self.send(chat_id, f"Я вже стежу за твоєю адресою: {sub.label} (черга {sub.queue}.{sub.subqueue}) 💡\n"
                           "Щоб змінити її, обери «Змінити адресу» в меню ☰.", None)

    def ask_lead(self, chat_id: int) -> None:
        sub = self.state.subs.get(str(chat_id))
        if sub is None:
            self.send(chat_id, "Спершу обери адресу: /start", None)
            return
        buttons = [[(f"{'✓ ' if m == sub.lead_minutes else ''}за {m} хв", f"l:{m}") for m in LEAD_CHOICES]]
        self.send(chat_id, f"За скільки хвилин тебе попереджати про вимкнення та ввімкнення? Зараз: {sub.lead_minutes} хв.\n"
                           f"(Графік перевіряю приблизно кожні {CHECK_EVERY_MIN} хв.)", buttons)

    def lead_chosen(self, chat_id: int, value: str) -> None:
        sub = self.state.subs.get(str(chat_id))
        if sub is None or not value.isdigit() or int(value) not in LEAD_CHOICES:
            return
        sub.lead_minutes = int(value)
        self.send(chat_id, f"✅ Домовились! Попереджатиму за {value} хв.", None)

    def schedule(self, chat_id: int) -> None:
        sub = self.state.subs.get(str(chat_id))
        if sub is None:
            self.send(chat_id, f"Спершу обери адресу: /start\nПовний графік: {SCHEDULE_URL}", None)
            return
        raw = self.dir.schedule(sub.queue, sub.subqueue)
        self.send(chat_id, schedule_text(raw, datetime.now(KYIV), f"{sub.label}, черга {sub.queue}.{sub.subqueue}"),
                  None)

    def demo(self, chat_id: int) -> None:
        """Send one example of every alert type for the user's real address, clearly marked as a test."""
        sub = self.state.subs.get(str(chat_id))
        if sub is None:
            self.send(chat_id, "Спершу обери адресу: /start - тоді покажу приклади.", None)
            return
        now = datetime.now(KYIV)
        raw = self.dir.schedule(sub.queue, sub.subqueue)
        days = by_day(raw)
        events = [e for e in transitions(merge([i for d in days.values() for i in d])) if e.at > now]
        off = next((e for e in events if e.kind == EventKind.OFF), None)
        if off is None:  # nothing scheduled: show a made-up 4-hour outage
            start = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            off = Event(EventKind.OFF, start, start + timedelta(hours=4))
        on = next((e for e in events if e.kind == EventKind.ON and e.at >= off.until), None) or \
            Event(EventKind.ON, off.until, off.until + timedelta(hours=6))
        next_off = next((e for e in events if e.kind != EventKind.ON and e.at > on.at), None)
        lead = timedelta(minutes=sub.lead_minutes)
        today = days.get(now.date(), [])

        mark = "🧪 ТЕСТ - це лише приклад, не справжнє сповіщення\n\n"
        samples = [
            describe_event(off, off.at - lead, sub.label),
            describe_event(on, on.at - lead, sub.label, next_off),
            describe_day(now.date(), today, sub.label, changed=True),
            f"⚠️ Житомиробленерго змінило чергу для твоєї адреси ({sub.label}): було {sub.queue}.{sub.subqueue}, "
            f"тепер X.Y.\nЯ вже стежу за новою чергою 👀 Графік: /schedule",
        ]
        self.send(chat_id, f"Ось {len(samples)} приклади моїх сповіщень для твоєї адреси "
                           f"(попереджаю за {sub.lead_minutes} хв):", None)
        for text in samples:
            self.send(chat_id, mark + text, None)

    def ask_rem(self, chat_id: int) -> None:
        self.state.sessions[str(chat_id)] = {"step": "rem"}
        rems = sorted(self.dir.rems(), key=lambda r: str(r.get("name")))
        self.send(chat_id, "1/4. Обери свій район (РЕМ):", as_buttons(rems, "r", per_row=2))

    def pick_rem_by_text(self, chat_id: int, text: str) -> None:
        """Typed district: "Звягельський", "звягельський район", "Звягельський РЕМ" all work."""
        query = re.sub(r"\s*(район|р-н|рем)\.?\s*$", "", text.strip(), flags=re.IGNORECASE)
        self._pick(chat_id, match(self.dir.rems(), query), "r", self.rem_chosen, "такий район")

    def rem_chosen(self, chat_id: int, rem_id: str) -> None:
        session = self.state.sessions[str(chat_id)] = {"step": "city", "rem": rem_id}
        cities = self.dir.cities(rem_id)
        towns = [c for c in cities if not str(c.get("name", "")).startswith("с.")][:MAX_BUTTONS]
        session["names"] = {str(c["id"]): str(c["name"]) for c in towns}
        self.send(chat_id, "2/4. Напиши назву міста чи села (наприклад: Сусли) або обери зі списку:",
                  as_buttons(towns, "c") or None)

    def pick_city_by_text(self, chat_id: int, text: str) -> None:
        session = self._session(str(chat_id))
        found = match(self.dir.cities(session["rem"]), text)
        self._pick(chat_id, found, "c", self.city_chosen, "такий населений пункт")

    def city_chosen(self, chat_id: int, city_id: str) -> None:
        session = self._session(str(chat_id))
        city_name = session.get("names", {}).get(city_id, "")
        session.update({"step": "street", "city": city_id, "city_name": city_name})
        streets = self.dir.streets(city_id)
        if not streets:
            self.send(chat_id, "Ой, для цього населеного пункту в базі немає вулиць 😕 Спробуй /start ще раз.", None)
            return
        session["names"] = {str(s["id"]): str(s["name"]) for s in streets}
        if len(streets) <= MAX_BUTTONS:
            self.send(chat_id, f"3/4. {city_name}: обери вулицю:", as_buttons(streets, "s"))
        else:
            self.send(chat_id, f"3/4. {city_name}: напиши назву вулиці (наприклад: Центральна):", None)

    def pick_street_by_text(self, chat_id: int, text: str) -> None:
        session = self._session(str(chat_id))
        found = match(self.dir.streets(session["city"]), text)
        self._pick(chat_id, found, "s", self.street_chosen, "таку вулицю")

    def street_chosen(self, chat_id: int, street_id: str) -> None:
        session = self._session(str(chat_id))
        street_name = session.get("names", {}).get(street_id, "")
        session.update({"step": "house", "street": street_id, "street_name": street_name})
        found = resolve_queue(self.dir.addresses(street_id), "")
        if isinstance(found, tuple):
            # The whole street is in one queue: no need to ask for the house.
            self.subscribe(chat_id, *found, self._label(session), street_id=street_id)
        elif found == "missing":
            self.send(chat_id, "Ой, на цій вулиці не знайшла будинків 😕 Спробуй /start ще раз.", None)
        else:
            self.send(chat_id, "4/4. Напиши номер будинку (наприклад: 12 або 12А):", None)

    def pick_house(self, chat_id: int, text: str) -> None:
        session = self._session(str(chat_id))
        wanted = normalize(text).replace(" ", "")
        found = resolve_queue(self.dir.addresses(session["street"]), wanted) if wanted else "missing"
        if isinstance(found, tuple):
            self.subscribe(chat_id, *found, self._label(session, text.strip()),
                           street_id=session["street"], house=wanted)
            return
        self.send(chat_id, f"Не знайшла будинок «{text.strip()}» на цій вулиці 🤔 Перевір номер і напиши ще раз.",
                  None)

    def _pick(self, chat_id: int, found: list[dict], prefix: str,
              chosen: Callable[[int, str], None], what: str) -> None:
        session = self._session(str(chat_id))
        if len(found) == 1:
            session.setdefault("names", {})[str(found[0]["id"])] = str(found[0]["name"])
            chosen(chat_id, str(found[0]["id"]))
        elif not found:
            self.send(chat_id, f"Не знайшла {what} 🤔 Перевір написання і спробуй ще раз.", None)
        elif len(found) <= MAX_BUTTONS:
            session.setdefault("names", {}).update({str(o["id"]): str(o["name"]) for o in found})
            self.send(chat_id, "Знайшла кілька варіантів - обери свій:", as_buttons(found, prefix))
        else:
            self.send(chat_id, f"Ой, аж {len(found)} варіантів 😅 Напиши трохи точніше.", None)

    @staticmethod
    def _label(session: dict, house: str = "") -> str:
        street = " ".join(filter(None, (session.get("street_name", ""), house)))
        return ", ".join(filter(None, (session.get("city_name", ""), street)))

    def subscribe(self, chat_id: int, queue: int, subqueue: int, label: str,
                  street_id: str = "", house: str = "") -> None:
        chat = str(chat_id)
        old = self.state.subs.get(chat)
        lead = old.lead_minutes if old else DEFAULT_LEAD
        # One address per chat: the new one replaces the old, with fresh alert history.
        self.state.subs[chat] = Subscription(queue, subqueue, label, lead_minutes=lead,
                                             street_id=street_id, house=house,
                                             checked_at=datetime.now(KYIV).isoformat())
        self.state.sessions.pop(chat, None)
        head = "✅ Адресу змінено" if old else "✅ Готово"
        self.send(chat_id, f"{head}! {label}: черга {queue}.{subqueue}.\n"
                           f"Тепер я попереджатиму тебе за {lead} хв до вимкнення і ввімкнення світла, "
                           "скажу, скільки мене не буде, і повідомлю, якщо графік зміниться 💡\n\n"
                           "/schedule - графік · /settings - коли попереджати · /change - інша адреса · "
                           "/stop - відписатися", None)

    def status(self, chat_id: int) -> None:
        sub = self.state.subs.get(str(chat_id))
        if not sub:
            self.send(chat_id, "Адресу ще не обрано. Надішли /start - і я почну стежити 💡", None)
            return
        raw = self.dir.schedule(sub.queue, sub.subqueue)
        self.send(chat_id, summary(raw, datetime.now(KYIV), f"{sub.label} (черга {sub.queue}.{sub.subqueue})"),
                  None)

    # tick -----------------------------------------------------------------------------

    def process_updates(self, updates: list[dict], answer: Callable[[str], None] = lambda _id: None) -> None:
        if updates:
            self.state.offset = max(int(u["update_id"]) for u in updates) + 1
        for update in updates:
            if "callback_query" in update:
                answer(update["callback_query"]["id"])  # stop every tapped button's spinner, kept or not
        for update in latest_requests(updates):
            try:
                if "callback_query" in update:
                    query = update["callback_query"]
                    chat_id = (query.get("message") or {}).get("chat", {}).get("id")
                    if chat_id is not None:
                        self.handle_button(chat_id, str(query.get("data", "")))
                elif "message" in update and "text" in update["message"]:
                    message = update["message"]
                    self.handle_text(message["chat"]["id"], message["text"])
                elif "message" in update and "chat" in update["message"]:
                    # Stickers, photos, voice, files...: say so instead of staying silent.
                    self.send(update["message"]["chat"]["id"], NOT_UNDERSTOOD, None)
            except (ApiError, KeyError, ValueError) as exc:
                chat_id = _chat_of(update)
                print(f"warning: update {update.get('update_id')} failed: {exc}")
                if chat_id is not None:
                    self.send(chat_id, "Ой, щось пішло не так під час пошуку 😕 Спробуй /start трохи пізніше.",
                              None)

    def refresh_queues(self, now: datetime, every: timedelta = timedelta(hours=6)) -> int:
        """Re-check each subscriber's address; follow ZTOE when it moves the address to another queue.

        One address request per street, at most every `every`. Returns how many queues changed.
        """
        changed = 0
        streets: dict[str, list[dict] | None] = {}
        for chat, sub in list(self.state.subs.items()):
            if not sub.street_id:
                continue
            if sub.checked_at and now - datetime.fromisoformat(sub.checked_at) < every:
                continue
            if sub.street_id not in streets:
                try:
                    streets[sub.street_id] = self.dir.addresses(sub.street_id)
                except ApiError as exc:
                    print(f"warning: addresses for street {sub.street_id} unavailable: {exc}")
                    streets[sub.street_id] = None
            rows = streets[sub.street_id]
            if rows is None:
                continue  # try again next tick
            sub.checked_at = now.isoformat()
            found = resolve_queue(rows, sub.house)
            try:
                if isinstance(found, tuple):
                    sub.problem = ""
                    if found != (sub.queue, sub.subqueue):
                        old = f"{sub.queue}.{sub.subqueue}"
                        sub.queue, sub.subqueue = found
                        sub.alerts = State()  # new queue: start its alert history fresh
                        changed += 1
                        self.send(int(chat), f"⚠️ Житомиробленерго змінило чергу для твоєї адреси ({sub.label}): "
                                             f"було {old}, тепер {sub.queue}.{sub.subqueue}.\n"
                                             "Я вже стежу за новою чергою 👀 Графік: /schedule", None)
                elif found != sub.problem:
                    sub.problem = found
                    text = ("⚠️ Не можу знайти твою адресу в базі Житомиробленерго. Поки попереджаю за "
                            f"чергою {sub.queue}.{sub.subqueue}. Перевір адресу: /change"
                            if found == "missing" else
                            "⚠️ На твоїй вулиці тепер кілька різних черг. Вкажи номер будинку, щоб я "
                            f"попереджала точно: /change (поки що стежу за чергою {sub.queue}.{sub.subqueue})")
                    self.send(int(chat), text, None)
            except Exception as exc:  # noqa: BLE001 - delivery problems are handled in send_alerts
                print(f"warning: could not notify {chat_tag(chat)} about its queue: {type(exc).__name__}")
        return changed

    def send_alerts(self, now: datetime, is_gone: Callable[[Exception], bool] = lambda _e: False) -> int:
        """Send due alerts to every subscriber; one schedule request per distinct queue."""
        schedules: dict[tuple[int, int], list[dict]] = {}
        sent = 0
        for chat, sub in list(self.state.subs.items()):
            key = (sub.queue, sub.subqueue)
            if key not in schedules:
                try:
                    schedules[key] = self.dir.schedule(*key)
                except ApiError as exc:
                    print(f"warning: schedule {key} unavailable: {exc}")
                    schedules[key] = None  # type: ignore[assignment]
            raw = schedules[key]
            if raw is None:
                continue
            messages, new_alerts = plan(raw, now, sub.alerts, Settings(lead=timedelta(minutes=sub.lead_minutes), label=sub.label))
            try:
                for text in messages:
                    self.send(int(chat), text, None)
                    sent += 1
            except Exception as exc:  # noqa: BLE001 - decide per error below
                if is_gone(exc):
                    print(f"{chat_tag(chat)} blocked the bot or was deleted; unsubscribing")
                    self.state.subs.pop(chat, None)
                    continue
                print(f"warning: sending to {chat_tag(chat)} failed: {type(exc).__name__}; will retry next run")
                continue
            sub.alerts = new_alerts
        return sent


def _chat_of(update: dict) -> int | None:
    if "callback_query" in update:
        return ((update["callback_query"].get("message") or {}).get("chat") or {}).get("id")
    return ((update.get("message") or {}).get("chat") or {}).get("id")

