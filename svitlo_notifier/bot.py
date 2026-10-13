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
from .planner import SCHEDULE_URL, Settings, State, plan, schedule_text, summary
from .schedule import KYIV

MAX_BUTTONS = 30
CHECK_EVERY_MIN = 10  # how often the scheduled job runs (.github/workflows/notify.yml)
LEAD_CHOICES = (15, 30, 60)
DEFAULT_LEAD = 30
Buttons = list[list[tuple[str, str]]]


class Directory(Protocol):
    def rems(self) -> list[dict]: ...
    def cities(self, rem_id: str) -> list[dict]: ...
    def streets(self, city_id: str) -> list[dict]: ...
    def addresses(self, street_id: str) -> list[dict]: ...
    def schedule(self, queue: int, subqueue: int) -> list[dict]: ...


Send = Callable[[int, str, Buttons | None], None]


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


# --- persisted state ----------------------------------------------------------------


@dataclass
class Subscription:
    """One address per chat. Choosing a new address replaces the old one."""

    queue: int
    subqueue: int
    label: str
    alerts: State = field(default_factory=State)
    lead_minutes: int = DEFAULT_LEAD

    def to_dict(self) -> dict:
        return {"queue": self.queue, "subqueue": self.subqueue, "label": self.label,
                "lead_minutes": self.lead_minutes, "alerts": self.alerts.to_dict()}

    @classmethod
    def from_dict(cls, raw: dict) -> "Subscription":
        return cls(int(raw["queue"]), int(raw["subqueue"]), str(raw.get("label", "")),
                   State.from_dict(raw.get("alerts", {})), int(raw.get("lead_minutes", DEFAULT_LEAD)))


@dataclass
class BotState:
    offset: int | None = None
    subs: dict[str, Subscription] = field(default_factory=dict)  # chat id -> subscription
    sessions: dict[str, dict] = field(default_factory=dict)  # chat id -> quiz progress

    def to_dict(self) -> dict:
        return {"offset": self.offset,
                "subs": {k: v.to_dict() for k, v in self.subs.items()},
                "sessions": self.sessions}

    @classmethod
    def from_dict(cls, raw: dict) -> "BotState":
        return cls(raw.get("offset"),
                   {k: Subscription.from_dict(v) for k, v in raw.get("subs", {}).items()},
                   dict(raw.get("sessions", {})))


# --- conversation ---------------------------------------------------------------------

HELP = (
    "Я надсилаю сповіщення про відключення світла за графіком Житомиробленерго: "
    "заздалегідь до вимкнення і до ввімкнення (скільки триватиме відключення), "
    "а також коли графік публікують чи змінюють.\n\n"
    "/start - обрати адресу (одна адреса на користувача)\n"
    "/change - змінити адресу\n"
    "/schedule - графік на сьогодні й завтра\n"
    "/status - стан зараз і найближчі зміни\n"
    "/settings - за скільки хвилин попереджати\n"
    "/stop - відписатися\n\n"
    f"Графік перевіряю кожні {CHECK_EVERY_MIN} хв, тому відповідаю не миттєво, а протягом ~{CHECK_EVERY_MIN} хв.\n"
    f"Повний графік: {SCHEDULE_URL}"
)


class Bot:
    def __init__(self, directory: Directory, send: Send, state: BotState) -> None:
        self.dir = directory
        self.send = send
        self.state = state

    def _session(self, chat: str) -> dict:
        return self.state.sessions.setdefault(chat, {})

    # entry points --------------------------------------------------------------------

    def handle_text(self, chat_id: int, text: str) -> None:
        chat = str(chat_id)
        command = text.strip().split()[0].lower().split("@")[0] if text.strip() else ""
        if command in ("/start", "/subscribe"):
            self.start(chat_id)
        elif command in ("/change", "/address"):
            self.ask_rem(chat_id)
        elif command == "/settings":
            self.ask_lead(chat_id)
        elif command == "/schedule":
            self.schedule(chat_id)
        elif command == "/stop":
            self.state.subs.pop(chat, None)
            self.state.sessions.pop(chat, None)
            self.send(chat_id, "Ви відписалися. Щоб знову отримувати сповіщення, надішліть /start.", None)
        elif command == "/status":
            self.status(chat_id)
        elif command == "/help":
            self.send(chat_id, HELP, None)
        else:
            step = self._session(chat).get("step")
            if step == "city":
                self.pick_city_by_text(chat_id, text)
            elif step == "street":
                self.pick_street_by_text(chat_id, text)
            elif step == "house":
                self.pick_house(chat_id, text)
            else:
                self.send(chat_id, "Надішліть /start, щоб обрати адресу, або /help.", None)

    def handle_button(self, chat_id: int, data: str) -> None:
        kind, _, value = data.partition(":")
        if data == "a:change":
            self.ask_rem(chat_id)
        elif data == "a:keep":
            self.send(chat_id, "Добре, адресу залишено без змін.", None)
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
            self.send(chat_id, "Вітаю! Оберу вашу адресу за 4 кроки, і надсилатиму сповіщення про світло.", None)
            self.ask_rem(chat_id)
            return
        self.send(chat_id, f"Ваша адреса: {sub.label} (черга {sub.queue}.{sub.subqueue}).\n"
                           "Можна підписатися лише на одну адресу. Змінити її?",
                  [[("Змінити адресу", "a:change"), ("Залишити", "a:keep")]])

    def ask_lead(self, chat_id: int) -> None:
        sub = self.state.subs.get(str(chat_id))
        if sub is None:
            self.send(chat_id, "Спершу оберіть адресу: /start", None)
            return
        buttons = [[(f"{'✓ ' if m == sub.lead_minutes else ''}за {m} хв", f"l:{m}") for m in LEAD_CHOICES]]
        self.send(chat_id, f"За скільки хвилин попереджати про вимкнення та ввімкнення? Зараз: {sub.lead_minutes} хв.\n"
                           f"(Графік перевіряю кожні {CHECK_EVERY_MIN} хв.)", buttons)

    def lead_chosen(self, chat_id: int, value: str) -> None:
        sub = self.state.subs.get(str(chat_id))
        if sub is None or not value.isdigit() or int(value) not in LEAD_CHOICES:
            return
        sub.lead_minutes = int(value)
        self.send(chat_id, f"✅ Попереджатиму за {value} хв.", None)

    def schedule(self, chat_id: int) -> None:
        sub = self.state.subs.get(str(chat_id))
        if sub is None:
            self.send(chat_id, f"Спершу оберіть адресу: /start\nПовний графік: {SCHEDULE_URL}", None)
            return
        raw = self.dir.schedule(sub.queue, sub.subqueue)
        self.send(chat_id, schedule_text(raw, datetime.now(KYIV), f"{sub.label}, черга {sub.queue}.{sub.subqueue}"),
                  None)

    def ask_rem(self, chat_id: int) -> None:
        self.state.sessions[str(chat_id)] = {"step": "rem"}
        rems = sorted(self.dir.rems(), key=lambda r: str(r.get("name")))
        self.send(chat_id, "1/4. Оберіть ваш район (РЕМ):", as_buttons(rems, "r", per_row=2))

    def rem_chosen(self, chat_id: int, rem_id: str) -> None:
        session = self.state.sessions[str(chat_id)] = {"step": "city", "rem": rem_id}
        cities = self.dir.cities(rem_id)
        towns = [c for c in cities if not str(c.get("name", "")).startswith("с.")][:MAX_BUTTONS]
        session["names"] = {str(c["id"]): str(c["name"]) for c in towns}
        self.send(chat_id, "2/4. Напишіть назву міста чи села (наприклад: Сусли) або оберіть зі списку:",
                  as_buttons(towns, "c") or None)

    def pick_city_by_text(self, chat_id: int, text: str) -> None:
        session = self._session(str(chat_id))
        found = match(self.dir.cities(session["rem"]), text)
        self._pick(chat_id, found, "c", self.city_chosen, "населений пункт")

    def city_chosen(self, chat_id: int, city_id: str) -> None:
        session = self._session(str(chat_id))
        city_name = session.get("names", {}).get(city_id, "")
        session.update({"step": "street", "city": city_id, "city_name": city_name})
        streets = self.dir.streets(city_id)
        if not streets:
            self.send(chat_id, "Для цього населеного пункту немає вулиць у базі. Спробуйте /start ще раз.", None)
            return
        session["names"] = {str(s["id"]): str(s["name"]) for s in streets}
        if len(streets) <= MAX_BUTTONS:
            self.send(chat_id, f"3/4. {city_name}: оберіть вулицю:", as_buttons(streets, "s"))
        else:
            self.send(chat_id, f"3/4. {city_name}: напишіть назву вулиці (наприклад: Центральна):", None)

    def pick_street_by_text(self, chat_id: int, text: str) -> None:
        session = self._session(str(chat_id))
        found = match(self.dir.streets(session["city"]), text)
        self._pick(chat_id, found, "s", self.street_chosen, "вулицю")

    def street_chosen(self, chat_id: int, street_id: str) -> None:
        session = self._session(str(chat_id))
        street_name = session.get("names", {}).get(street_id, "")
        session.update({"step": "house", "street": street_id, "street_name": street_name})
        rows = self.dir.addresses(street_id)
        queues = {(int(r["cherga"]), int(r["pidcherga"])) for r in rows if r.get("cherga") is not None}
        if len(queues) == 1:
            # The whole street is in one queue: no need to ask for the house.
            self.subscribe(chat_id, *queues.pop(), self._label(session))
        elif not queues:
            self.send(chat_id, "Не знайшов будинків на цій вулиці. Спробуйте /start ще раз.", None)
        else:
            self.send(chat_id, "4/4. Напишіть номер будинку (наприклад: 12 або 12А):", None)

    def pick_house(self, chat_id: int, text: str) -> None:
        session = self._session(str(chat_id))
        wanted = normalize(text).replace(" ", "")
        for row in self.dir.addresses(session["street"]):
            if wanted in house_numbers(str(row.get("name", ""))):
                self.subscribe(chat_id, int(row["cherga"]), int(row["pidcherga"]),
                               self._label(session, text.strip()))
                return
        self.send(chat_id, f"Будинок «{text.strip()}» не знайдено на цій вулиці. Перевірте номер і напишіть ще раз.",
                  None)

    def _pick(self, chat_id: int, found: list[dict], prefix: str,
              chosen: Callable[[int, str], None], what: str) -> None:
        session = self._session(str(chat_id))
        if len(found) == 1:
            session.setdefault("names", {})[str(found[0]["id"])] = str(found[0]["name"])
            chosen(chat_id, str(found[0]["id"]))
        elif not found:
            self.send(chat_id, f"Не знайшов такий {what}. Перевірте написання і спробуйте ще раз.", None)
        elif len(found) <= MAX_BUTTONS:
            session.setdefault("names", {}).update({str(o["id"]): str(o["name"]) for o in found})
            self.send(chat_id, "Знайшов кілька варіантів, оберіть:", as_buttons(found, prefix))
        else:
            self.send(chat_id, f"Забагато варіантів ({len(found)}). Напишіть точніше.", None)

    @staticmethod
    def _label(session: dict, house: str = "") -> str:
        street = " ".join(filter(None, (session.get("street_name", ""), house)))
        return ", ".join(filter(None, (session.get("city_name", ""), street)))

    def subscribe(self, chat_id: int, queue: int, subqueue: int, label: str) -> None:
        chat = str(chat_id)
        old = self.state.subs.get(chat)
        lead = old.lead_minutes if old else DEFAULT_LEAD
        # One address per chat: the new one replaces the old, with fresh alert history.
        self.state.subs[chat] = Subscription(queue, subqueue, label, lead_minutes=lead)
        self.state.sessions.pop(chat, None)
        head = "✅ Адресу змінено" if old else "✅ Готово"
        self.send(chat_id, f"{head}! {label}: черга {queue}.{subqueue}.\n"
                           f"Попереджатиму за {lead} хв до вимкнення і ввімкнення світла "
                           "(і скажу, скільки триватиме відключення), а також коли графік зміниться.\n"
                           "/schedule - графік, /settings - час попередження, /change - інша адреса, "
                           "/stop - відписатися.", None)

    def status(self, chat_id: int) -> None:
        sub = self.state.subs.get(str(chat_id))
        if not sub:
            self.send(chat_id, "Ви ще не обрали адресу. Надішліть /start.", None)
            return
        raw = self.dir.schedule(sub.queue, sub.subqueue)
        self.send(chat_id, summary(raw, datetime.now(KYIV), f"{sub.label} (черга {sub.queue}.{sub.subqueue})"),
                  None)

    # tick -----------------------------------------------------------------------------

    def process_updates(self, updates: list[dict], answer: Callable[[str], None] = lambda _id: None) -> None:
        for update in updates:
            self.state.offset = int(update["update_id"]) + 1
            try:
                if "callback_query" in update:
                    query = update["callback_query"]
                    answer(query["id"])
                    chat_id = (query.get("message") or {}).get("chat", {}).get("id")
                    if chat_id is not None:
                        self.handle_button(chat_id, str(query.get("data", "")))
                elif "message" in update and "text" in update["message"]:
                    message = update["message"]
                    self.handle_text(message["chat"]["id"], message["text"])
            except (ApiError, KeyError, ValueError) as exc:
                chat_id = _chat_of(update)
                print(f"warning: update {update.get('update_id')} failed: {exc}")
                if chat_id is not None:
                    self.send(chat_id, "Сталася помилка під час пошуку. Спробуйте /start ще раз трохи пізніше.",
                              None)

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
                    print(f"chat {chat} blocked the bot or was deleted; unsubscribing")
                    self.state.subs.pop(chat, None)
                    continue
                print(f"warning: sending to {chat} failed: {exc}; will retry next run")
                continue
            sub.alerts = new_alerts
        return sent


def _chat_of(update: dict) -> int | None:
    if "callback_query" in update:
        return ((update["callback_query"].get("message") or {}).get("chat") or {}).get("id")
    return ((update.get("message") or {}).get("chat") or {}).get("id")

