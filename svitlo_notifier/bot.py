"""Multi-user Telegram bot: friends pick their address in a quiz and get alerts for their queue.

Runs in short ticks (e.g. every 5-10 minutes on GitHub Actions): each tick reads the
messages and button taps that arrived since the last tick, answers them, then sends the
outage alerts that are due for every subscriber. Nothing runs between ticks, so replies
arrive on the next tick rather than instantly.
"""

from __future__ import annotations

import difflib
import html
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Protocol

from .api import ApiError
from .planner import (SCHEDULE_URL, Settings, State, by_day, describe_day, describe_event, passed_events, plan,
                      schedule_text, summary)
from .secure import chat_tag
from .schedule import KYIV, Event, EventKind, Status, merge, status_at, transitions

MAX_BUTTONS = 30
MENU_VERSION = 6  # bump on every MENU change so Telegram's menu is refreshed
CHECK_EVERY_MIN = 10  # how often the scheduled job runs (.github/workflows/notify.yml)
LEAD_CHOICES = (15, 30, 60)
MENU = [
    ("start", "Обрати адресу"),
    ("schedule", "Графік на сьогодні й завтра"),
    ("status", "Стан за графіком"),
    ("setting", "Коли попереджати"),
    ("change", "Змінити адресу"),
    ("stop", "Відписатися"),
    ("help", "Про Люсю і допомога"),
]
DEFAULT_LEAD = 30
# Chats clean themselves (owner, 16.10): messages older than this are deleted. Telegram lets a bot delete
# messages in a private chat only while they are less than 48 hours old, so 46 h leaves a safe margin.
CLEAN_AFTER = 46 * 3600
# Every queue is watched for the dashboard's "how often does the schedule change" chart,
# not only the queues that have subscribers.
WATCH_QUEUES = [(q, s) for q in range(1, 7) for s in (1, 2)]
WATCH_EVERY = timedelta(minutes=30)
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


_CUSTOMERS = re.compile(r"\s+-\s+(не)?побутові\b.*$", re.IGNORECASE)


def house_key(text: str) -> str:
    """A house number as stored: lower case, no spaces ('27А' -> '27а'). '85-А' and '85А' stay different:
    a number that is not written the way ZTOE lists it is offered as a button, never taken silently."""
    return normalize(text).replace(" ", "")


def _loose(text: str) -> str:
    """For suggestions only: '85 а', '85а' and '85-А' look alike."""
    return re.sub(r"[\s\-]", "", normalize(text))


def _house_parts(raw: str) -> list[tuple[str, bool]]:
    """'25 - побутові споживачі, 87 - непобутові (юридичні) споживачі' -> [('25', True), ('87', False)],
    numbers spelt as ZTOE lists them."""
    houses = []
    for part in raw.split(","):
        part = part.strip()
        found = _CUSTOMERS.search(part)
        number = _CUSTOMERS.sub("", part).strip()
        if number:
            houses.append((number, not (found and found.group(1))))
    return houses


def parse_houses(raw: str) -> list[tuple[str, bool]]:
    """'25 - побутові споживачі, 87 - непобутові (юридичні) споживачі' -> [('25', True), ('87', False)].

    True = household («побутові»), False = business («непобутові (юридичні)»).
    """
    return [(house_key(number), household) for number, household in _house_parts(raw)]


def listed_houses(rows: list[dict]) -> list[str]:
    """Every house number on a street, spelt as ZTOE lists it (for buttons), each once."""
    seen: dict[str, str] = {}
    for row in rows:
        for number, _household in _house_parts(str(row.get("name", ""))):
            seen.setdefault(house_key(number), number)
    return list(seen.values())


def house_options(rows: list[dict], typed: str) -> list[str]:
    """Listed numbers that look like what was typed: «85а» or «85 а» -> ['85-А']; «85» -> ['85-А', '85/1']."""
    want = _loose(typed)
    if not want:
        return []
    listed = listed_houses(rows)
    same = [h for h in listed if _loose(h) == want]
    longer = [h for h in listed if h not in same and _loose(h).startswith(want)
              and not _loose(h)[len(want)].isdigit()]  # «85» suggests «85-А», never «850»
    return same + longer


def house_numbers(raw: str) -> list[str]:
    """'25 - побутові споживачі, 27А - побутові споживачі' -> ['25', '27а']."""
    return [number for number, _household in parse_houses(raw)]


def _queue_of(row: dict) -> tuple[int, int] | None:
    """ZTOE writes 0.0 for addresses without an outage queue (roads, some businesses): not a queue."""
    if row.get("cherga") is None:
        return None
    queue = (int(row["cherga"]), int(row.get("pidcherga") or 0))
    return queue if queue[0] > 0 else None


def name_of(option: dict) -> str:
    """ZTOE sends some names HTML-escaped (СГТ &quot;Ветеран&quot;): show them as people write them."""
    return html.unescape(str(option.get("name", "")))


def _words(text: str) -> list[str]:
    return re.findall(r"[\w']+", normalize(text))


def match(options: list[dict], query: str) -> list[dict]:
    """Exact name wins; then names containing the typed text; then names where every typed word starts a
    word of the name, in any order ("в карпенка" or "карпенка вас" -> "вул. Василя Карпенка")."""
    q = normalize(html.unescape(query))
    if not q:
        return []
    names = [(o, normalize(name_of(o))) for o in options]
    exact = [o for o, n in names if n == q]
    if exact:
        return exact
    contains = [o for o, n in names if q in n]
    if contains:
        return contains
    typed = _words(q)
    return [o for o, n in names if typed and all(any(w.startswith(t) for w in _words(n)) for t in typed)]


def similar(options: list[dict], query: str, limit: int = 4, cutoff: float = 0.8) -> list[dict]:
    """Closest names for a typo, word by word: «Паражанова» -> «вул. Сергія Параджанова»,
    «Василя Карпенко» -> «вул. Василя Карпенка». For "did you mean" buttons."""
    typed = _words(html.unescape(query))
    if not typed:
        return []
    scored = []
    for o in options:
        words = _words(name_of(o))
        if not words:
            continue
        # every typed word must resemble (or start) some word of the name; the weakest one counts
        score = min(max(1.0 if w.startswith(t) else difflib.SequenceMatcher(None, t, w).ratio() for w in words)
                    for t in typed)
        if score >= cutoff:
            scored.append((score, name_of(o), o))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [o for _score, _name, o in scored[:limit]]


def as_buttons(options: list[dict], prefix: str, per_row: int = 2) -> Buttons:
    rows: Buttons = []
    for i in range(0, len(options), per_row):
        rows.append([(name_of(o)[:60], f"{prefix}:{o['id']}") for o in options[i : i + per_row]])
    return rows


def house_queues(rows: list[dict], house: str) -> dict[bool, tuple[int, int]]:
    """A house's real queues by consumer type: {True: household queue, False: business queue} (0.0 left out)."""
    house = house_key(house)
    queues: dict[bool, tuple[int, int]] = {}
    for row in rows:
        for number, household in parse_houses(str(row.get("name", ""))):
            if number == house and (queue := _queue_of(row)):
                queues.setdefault(household, queue)
    return queues


def resolve_queue(rows: list[dict], house: str, household: bool | None = None) -> tuple[int, int] | str:
    """The queue for a house on a street, or "missing" / "ambiguous" / "no_queue" when it can't be decided.

    A house may be listed several times (households and businesses, sometimes also under 0.0): with no
    `household` choice the household rows win; 0.0 is never a queue.
    """
    queues = {q for r in rows if (q := _queue_of(r))}
    if house:
        house = house_key(house)
        listed = False
        for want_household in ((True, False) if household is None else (household,)):
            for row in rows:
                if (house, want_household) in parse_houses(str(row.get("name", ""))):
                    listed = True
                    if (queue := _queue_of(row)):
                        return queue
        return "no_queue" if listed else "missing"
    if len(queues) == 1:
        return next(iter(queues))
    if queues:
        return "ambiguous"
    return "no_queue" if any(r.get("cherga") is not None for r in rows) else "missing"


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
    # The bot this person is known to reach us on (they wrote to it, or it delivered a message to them).
    # After a bot switch, old subscribers count as active only once the new bot reaches them.
    bot_id: int | None = None
    # "home" / "business" when the house is listed for both with different queues and the person chose;
    # empty = household rows win (the usual case)
    kind: str = ""

    def household(self) -> bool | None:
        return {"home": True, "business": False}.get(self.kind)

    def to_dict(self) -> dict:
        return {"queue": self.queue, "subqueue": self.subqueue, "label": self.label,
                "lead_minutes": self.lead_minutes, "street_id": self.street_id, "house": self.house,
                "checked_at": self.checked_at, "problem": self.problem, "alerts": self.alerts.to_dict(),
                "bot_id": self.bot_id, "kind": self.kind}

    @classmethod
    def from_dict(cls, raw: dict) -> "Subscription":
        house = str(raw.get("house", ""))
        return cls(int(raw["queue"]), int(raw["subqueue"]), label_without_house(str(raw.get("label", "")), house),
                   State.from_dict(raw.get("alerts", {})), int(raw.get("lead_minutes", DEFAULT_LEAD)),
                   str(raw.get("street_id", "")), house,
                   str(raw.get("checked_at", "")), str(raw.get("problem", "")),
                   int(raw["bot_id"]) if raw.get("bot_id") is not None else None, str(raw.get("kind", "")))


def label_without_house(label: str, house: str) -> str:
    """Data minimisation (16.10): labels show town and street only. Older labels ended with the house number."""
    if house and " " in label:
        head, last = label.rsplit(" ", 1)
        if normalize(last).replace(" ", "") == house:
            return head
    return label


@dataclass
class BotState:
    offset: int | None = None
    bot_id: int | None = None  # which Telegram bot this state belongs to (offsets are per bot)
    menu_version: int = 0  # bumped when MENU changes, so Telegram is updated once
    subs: dict[str, Subscription] = field(default_factory=dict)  # chat id -> subscription
    sessions: dict[str, dict] = field(default_factory=dict)  # chat id -> quiz progress
    keyboards: dict[str, int] = field(default_factory=dict)  # chat id -> message with the live buttons
    # Dashboard context: queue "1.2" -> {"2026-10-13": fingerprint of that day's schedule}
    watch: dict[str, dict[str, str]] = field(default_factory=dict)
    watched_at: str = ""
    # Everyone who opened the current bot, as keyed log tags (not chat ids) -> first day seen.
    # Only for the dashboard's "started the bot but chose no address" count.
    seen: dict[str, str] = field(default_factory=dict)
    # Messages in each chat as [message id, unix time], so the chat can clean itself (CLEAN_AFTER).
    history: dict[str, list[list[int]]] = field(default_factory=dict)

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
            self.seen = {}  # "started the bot" counts per bot
            self.history = {}  # message ids belong to the old bot
        return changed

    def to_dict(self) -> dict:
        return {"offset": self.offset, "bot_id": self.bot_id, "menu_version": self.menu_version,
                "subs": {k: v.to_dict() for k, v in self.subs.items()},
                "sessions": self.sessions, "keyboards": self.keyboards,
                "watch": self.watch, "watched_at": self.watched_at, "seen": self.seen, "history": self.history}

    @classmethod
    def from_dict(cls, raw: dict) -> "BotState":
        return cls(raw.get("offset"), raw.get("bot_id"), int(raw.get("menu_version", 0)),
                   {k: Subscription.from_dict(v) for k, v in raw.get("subs", {}).items()},
                   dict(raw.get("sessions", {})),
                   {k: int(v) for k, v in raw.get("keyboards", {}).items()},
                {k: dict(v) for k, v in raw.get("watch", {}).items()}, str(raw.get("watched_at", "")),
                {str(k): str(v) for k, v in raw.get("seen", {}).items()},
                {str(k): [[int(m), int(t)] for m, t in v] for k, v in raw.get("history", {}).items()})


# --- conversation ---------------------------------------------------------------------

NO_QUEUE = ("Для цієї адреси Житомиробленерго не вказує черги відключень 🤔 Тому попереджати за нею не можу. "
            "Перевір адресу або обери іншу: /change")
NOT_UNDERSTOOD = "Я тебе не розумію 🙈 Обери команду з меню ☰ (кнопка «Menu» внизу) або надішли /help."

HELP = (
    "Привіт, я Світло Люся 💡\n"
    "Попереджаю про відключення світла за графіком Житомиробленерго: заздалегідь до вимкнення "
    "і до ввімкнення, кажу, скільки мене не буде, і повідомляю, коли графік змінюється.\n\n"
    "/start - обрати адресу (одна на людину)\n"
    "/change - змінити адресу\n"
    "/schedule - графік на сьогодні й завтра\n"
    "/status - стан за графіком зараз (без урахування аварійних відключень)\n"
    "/setting - за скільки хвилин попереджати\n"
    "/stop - відписатися\n\n"
    "🧹 Повідомлення, старші за 2 доби, я видаляю сама, щоб чат не засмічувався.\n"
    "Аварійні відключення, на жаль, передбачити не можу.\n"
    f"Повний графік: {SCHEDULE_URL}"
)




class Bot:
    def __init__(self, directory: Directory, send: Send, state: BotState,
                 unbutton: Unbutton = lambda _chat, _message: None,
                 delete: Callable[[int, int], bool] = lambda _chat, _message: False) -> None:
        self.dir = directory
        self._send = send
        self._unbutton = unbutton
        self._delete = delete
        self.state = state
        # Aggregate counters for the owner dashboard ("request:/start", "failure:ztoe", ...). No chat ids.
        self.stats: Counter[str] = Counter()
        self.schedule_events: list[dict] = []  # {"queue", "day", "kind": published|changed}
        self.reply_waits: list[int] = []  # seconds each answered message waited for this run (SLA)
        self.queued_at_start: int | None = None  # messages already waiting when the run started
        self.queued_by_kind: Counter[str] = Counter()  # the same, by request type (/start, button, ...)
        self.waits_by_kind: dict[str, list[int]] = {}  # reply_waits split by request type
        # Alert timeliness (spec §6): [minutes of notice, chosen warning time] per alert sent; < 0 = late.
        self.alert_notices: list[list[int]] = []
        self.alert_early = timedelta(0)  # see Settings.early; the always-on server uses its check interval
        # Look at all 12 queues for the dashboard's Context section. Off on the always-on server
        # (owner decision D5: as few ZTOE requests as possible); subscribers' queues are still tracked.
        self.watch_all = True

    def reset_window(self) -> None:
        """Start a new dashboard window (the always-on server reports every few minutes)."""
        self.stats.clear()
        self.schedule_events = []
        self.reply_waits = []
        self.waits_by_kind = {}
        self.alert_notices = []
        self.queued_at_start = 0  # with long polling, nothing waits for a run to start
        self.queued_by_kind = Counter()

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
        if message_id is not None:
            self._remember(chat, int(message_id), time.time())

    def _remember(self, chat: str, message_id: int, at: float) -> None:
        self.state.history.setdefault(chat, []).append([message_id, int(at)])

    def clean_chats(self, now: float | None = None) -> int:
        """Delete messages older than CLEAN_AFTER (both sides), so every chat keeps only the last ~2 days."""
        now = time.time() if now is None else now
        deleted = 0
        for chat, messages in list(self.state.history.items()):
            keep = []
            for message_id, at in messages:
                if now - at < CLEAN_AFTER:
                    keep.append([message_id, at])
                    continue
                if now - at < 48 * 3600 and self._delete(int(chat), message_id):
                    deleted += 1
                if self.state.keyboards.get(chat) == message_id:
                    self.state.keyboards.pop(chat)  # its buttons are gone with it
            if keep:
                self.state.history[chat] = keep
            else:
                self.state.history.pop(chat)
        if deleted:
            self.stats["outcome:messages_cleaned"] += deleted
        return deleted

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
        elif command in ("/setting", "/settings"):
            self.ask_lead(chat_id)
        elif command == "/schedule":
            self.schedule(chat_id)
        elif command in ("/test", "/demo"):
            self.demo(chat_id)
        elif command == "/stop":
            if self.state.subs.pop(chat, None):
                self.stats["outcome:unsubscribed"] += 1
            self.state.sessions.pop(chat, None)
            self.state.keyboards.pop(chat, None)
            self.state.seen.pop(chat_tag(chat), None)  # /stop: nothing about this chat is kept
            self.send(chat_id, "Добре, більше не турбуватиму 💤 Я видалила твою адресу й налаштування "
                               "(резервні копії зникнуть протягом 3 днів). Захочеш повернути мене - надішли /start.",
                      None)
            self.state.history.pop(chat, None)  # after the reply, so not even its id is kept
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
        expected = {"r": "rem", "c": "city", "s": "street", "h": "house", "t": "house"}.get(kind)
        if expected:
            if self.state.sessions.get(str(chat_id), {}).get("step") != expected:
                # A button from an earlier step (tapped twice, or an old message): it must not restart a step.
                self.stats["request:old_button"] += 1
                return
            self.retire_buttons(chat_id)  # the tap is taken: its buttons disappear at once
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
        elif kind == "h":
            self.house_chosen(chat_id, value)
        elif kind == "t":
            self.kind_chosen(chat_id, value)

    # quiz steps ------------------------------------------------------------------------

    def start(self, chat_id: int) -> None:
        sub = self.state.subs.get(str(chat_id))
        if sub is None:
            self.send(chat_id, "Привіт! Я Світло Люся 💡 Знайду твою адресу за 4 кроки і попереджатиму, коли мене вимикатимуть і вмикатимуть.", None)
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
        rems = self.dir.rems()
        self._pick(chat_id, match(rems, query), "r", self.rem_chosen, "такий район", rems, query)

    def rem_chosen(self, chat_id: int, rem_id: str) -> None:
        session = self.state.sessions[str(chat_id)] = {"step": "city", "rem": rem_id}
        cities = self.dir.cities(rem_id)
        towns = [c for c in cities if not str(c.get("name", "")).startswith("с.")][:MAX_BUTTONS]
        session["names"] = {str(c["id"]): name_of(c) for c in towns}
        self.send(chat_id, "2/4. Напиши назву міста чи села (наприклад: Сусли) або обери зі списку:",
                  as_buttons(towns, "c") or None)

    def pick_city_by_text(self, chat_id: int, text: str) -> None:
        session = self._session(str(chat_id))
        cities = self.dir.cities(session["rem"])
        self._pick(chat_id, match(cities, text), "c", self.city_chosen, "такий населений пункт", cities, text)

    def city_chosen(self, chat_id: int, city_id: str) -> None:
        session = self._session(str(chat_id))
        city_name = session.get("names", {}).get(city_id, "")
        session.update({"step": "street", "city": city_id, "city_name": city_name})
        streets = self.dir.streets(city_id)
        if not streets:
            self.send(chat_id, "Ой, для цього населеного пункту в базі немає вулиць 😕 Спробуй /start ще раз.", None)
            return
        session["names"] = {str(s["id"]): name_of(s) for s in streets}
        if len(streets) <= MAX_BUTTONS:
            self.send(chat_id, f"3/4. {city_name}: обери вулицю:", as_buttons(streets, "s"))
        else:
            self.send(chat_id, f"3/4. {city_name}: напиши назву вулиці (наприклад: Центральна):", None)

    def pick_street_by_text(self, chat_id: int, text: str) -> None:
        session = self._session(str(chat_id))
        if normalize(text) == normalize(session.get("city_name", "")):
            # The town typed again (e.g. while the tapped town was still loading): not a street.
            self.send(chat_id, f"{session['city_name']} вже обрано ✅ Тепер напиши назву вулиці:", None)
            return
        streets = self.dir.streets(session["city"])
        self._pick(chat_id, match(streets, text), "s", self.street_chosen, "таку вулицю", streets, text)

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
        elif found == "no_queue":
            self.stats["outcome:no_queue"] += 1
            self.state.sessions.pop(str(chat_id), None)  # the previous address (if any) stays as it was
            self.send(chat_id, NO_QUEUE, None)
        else:
            self.send(chat_id, "4/4. Напиши номер будинку (наприклад: 12 або 12А):", None)

    def pick_house(self, chat_id: int, text: str) -> None:
        session = self._session(str(chat_id))
        rows = self.dir.addresses(session["street"])
        exact = [h for h in listed_houses(rows) if normalize(h) == normalize(text)] if text.strip() else []
        if exact:
            self._house_found(chat_id, rows, exact[0], text)
            return
        options = house_options(rows, text)
        if options and len(options) <= MAX_BUTTONS:
            # Written differently from ZTOE («85а» vs «85-А»): the person confirms the official number.
            session["houses"] = options
            question = (f"Це будинок «{options[0]}»? Натисни, щоб підтвердити, або напиши інакше 👇"
                        if len(options) == 1 else "Знайшла такі будинки - обери свій:")
            buttons = [[(h[:30], f"h:{i}") for i, h in enumerate(options[j:j + 4], j)]
                       for j in range(0, len(options), 4)]
            self.send(chat_id, question, buttons)
            return
        self._house_found(chat_id, rows, "", text)

    def house_chosen(self, chat_id: int, index: str) -> None:
        session = self._session(str(chat_id))
        options = session.get("houses", [])
        if not index.isdigit() or int(index) >= len(options):
            return
        self._house_found(chat_id, self.dir.addresses(session["street"]), options[int(index)], options[int(index)])

    def kind_chosen(self, chat_id: int, kind: str) -> None:
        session = self._session(str(chat_id))
        if kind not in ("home", "business") or not session.get("house"):
            return
        found = resolve_queue(self.dir.addresses(session["street"]), session["house"], kind == "home")
        if isinstance(found, tuple):
            self.subscribe(chat_id, *found, self._label(session), street_id=session["street"],
                           house=session["house"], kind=kind)

    def _house_found(self, chat_id: int, rows: list[dict], listed: str, text: str) -> None:
        session = self._session(str(chat_id))
        session.pop("houses", None)
        wanted = house_key(listed)
        queues = house_queues(rows, wanted) if wanted else {}
        if len(set(queues.values())) == 2:
            # Listed for homes and for businesses («юридичні») with different queues: the person chooses.
            session["house"] = wanted
            home, business = queues[True], queues[False]
            self.send(chat_id, f"Я знайшла за адресою «{listed}» і фізичну, і юридичну особу - у них різні черги. "
                               "Обери свій варіант 👇",
                      [[(f"🏠 Фізична особа (житло) - черга {home[0]}.{home[1]}", "t:home")],
                       [(f"🏢 Юридична особа / ФОП - черга {business[0]}.{business[1]}", "t:business")]])
            return
        found = resolve_queue(rows, wanted) if wanted else "missing"
        if isinstance(found, tuple):
            self.subscribe(chat_id, *found, self._label(session),  # no house number in the label (16.10)
                           street_id=session["street"], house=wanted)
            return
        if found == "no_queue":
            self.stats["outcome:no_queue"] += 1
            self.state.sessions.pop(str(chat_id), None)
            self.send(chat_id, NO_QUEUE, None)
            return
        self.stats["outcome:not_found"] += 1
        self.send(chat_id, f"Не знайшла будинок «{text.strip()}» на цій вулиці 🤔 Перевір номер і напиши ще раз.",
                  None)

    def _pick(self, chat_id: int, found: list[dict], prefix: str, chosen: Callable[[int, str], None], what: str,
              options: list[dict] | None = None, query: str = "") -> None:
        session = self._session(str(chat_id))
        exact = bool(found) and normalize(name_of(found[0])) == normalize(html.unescape(query))
        if prefix == "s" and query and not exact and len(found) <= MAX_BUTTONS:
            # A street is never picked from a partial or misspelt name: the right full names are offered as
            # buttons and the person taps theirs («Паражвнова» -> [вул. Сергія Параджанова]).
            close = found + [o for o in similar(options or [], query) if o not in found]
            close = close[:MAX_BUTTONS]
            if close:
                session.setdefault("names", {}).update({str(o["id"]): name_of(o) for o in close})
                if found:
                    text = (f"Це «{name_of(close[0])}»? Натисни, щоб підтвердити, або напиши інакше 👇"
                            if len(close) == 1 else "Знайшла кілька варіантів - обери свій:")
                else:
                    self.stats["outcome:did_you_mean"] += 1
                    text = f"Не знайшла «{query.strip()}» 🤔 Може, одне з цього?"
                self.send(chat_id, text, as_buttons(close, prefix))
                return
        if not found and options:
            close = similar(options, query)  # a typo: offer the closest names as buttons
            if close:
                self.stats["outcome:did_you_mean"] += 1
                session.setdefault("names", {}).update({str(o["id"]): name_of(o) for o in close})
                self.send(chat_id, f"Не знайшла «{query.strip()}» 🤔 Може, одне з цього?", as_buttons(close, prefix))
                return
        if len(found) == 1:
            session.setdefault("names", {})[str(found[0]["id"])] = name_of(found[0])
            chosen(chat_id, str(found[0]["id"]))
        elif not found:
            self.stats["outcome:not_found"] += 1
            hint = ("\nБагато вулиць перейменовано, а база Житомиробленерго знає лише нові назви. "
                    "Спробуй нову назву або лише частину слова (наприклад: «Карпенка»)." if prefix == "s" else "")
            self.send(chat_id, f"Не знайшла {what} 🤔 Перевір написання і спробуй ще раз.{hint}", None)
        elif len(found) <= MAX_BUTTONS:
            session.setdefault("names", {}).update({str(o["id"]): name_of(o) for o in found})
            self.send(chat_id, "Знайшла кілька варіантів - обери свій:", as_buttons(found, prefix))
        else:
            self.send(chat_id, f"Ой, аж {len(found)} варіантів 😅 Напиши трохи точніше.", None)

    @staticmethod
    def _label(session: dict, house: str = "") -> str:
        street = " ".join(filter(None, (session.get("street_name", ""), house)))
        return ", ".join(filter(None, (session.get("city_name", ""), street)))

    def subscribe(self, chat_id: int, queue: int, subqueue: int, label: str,
                  street_id: str = "", house: str = "", kind: str = "") -> None:
        chat = str(chat_id)
        old = self.state.subs.get(chat)
        lead = old.lead_minutes if old else DEFAULT_LEAD
        # One address per chat: the new one replaces the old, with fresh alert history.
        self.state.subs[chat] = Subscription(queue, subqueue, label, lead_minutes=lead,
                                             street_id=street_id, house=house, kind=kind,
                                             checked_at=datetime.now(KYIV).isoformat(),
                                             bot_id=self.state.bot_id)
        self.state.sessions.pop(chat, None)
        self.stats["outcome:address_changed" if old else "outcome:subscribed"] += 1
        head = "✅ Адресу змінено" if old else "✅ Готово"
        self.send(chat_id, f"{head}! {label}: черга {queue}.{subqueue}.\n"
                           f"Тепер я попереджатиму тебе за {lead} хв до вимкнення і ввімкнення світла, "
                           "скажу, скільки мене не буде, і повідомлю, якщо графік зміниться 💡\n\n"
                           "/schedule - графік · /setting - коли попереджати · /change - інша адреса · "
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

    def mark_reachable(self, chat_id) -> None:
        sub = self.state.subs.get(str(chat_id))
        if sub is not None and self.state.bot_id is not None:
            sub.bot_id = self.state.bot_id

    def note_queue(self, updates: list[dict]) -> None:
        """Record what was already waiting when the run started (first read of the run only)."""
        if self.queued_at_start is None:
            self.queued_at_start = len(updates)
            self.queued_by_kind.update(self._request_kind(u) for u in updates)

    def process_updates(self, updates: list[dict], answer: Callable[[str], None] = lambda _id: None,
                        now: float | None = None) -> None:
        now = time.time() if now is None else now
        for update in updates:
            chat_id = _chat_of(update)
            if chat_id is not None:
                self.mark_reachable(chat_id)  # they wrote to this bot, so it can reach them
                self.state.seen.setdefault(chat_tag(chat_id), datetime.now(KYIV).date().isoformat())
            sent_at = (update.get("message") or {}).get("date")
            if chat_id is not None and sent_at and (update.get("message") or {}).get("message_id"):
                self._remember(str(chat_id), int(update["message"]["message_id"]), int(sent_at))
            if sent_at:  # how long the message waited for a run to pick it up (button taps carry no time)
                self.reply_waits.append(max(0, int(now - int(sent_at))))
                self.waits_by_kind.setdefault(self._request_kind(update), []).append(self.reply_waits[-1])
        if updates:
            self.state.offset = max(int(u["update_id"]) for u in updates) + 1
        for update in updates:
            if "callback_query" in update:
                answer(update["callback_query"]["id"])  # stop every tapped button's spinner, kept or not
        latest = latest_requests(updates)
        if len(latest) < len(updates):
            self.stats["request:superseded"] += len(updates) - len(latest)
        for update in latest:
            self.stats[f"request:{self._request_kind(update)}"] += 1
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
                self.stats["failure:ztoe" if isinstance(exc, ApiError) else "failure:bad_update"] += 1
                chat_id = _chat_of(update)
                print(f"warning: update {update.get('update_id')} failed: {exc}")
                if chat_id is not None:
                    self.send(chat_id, "Ой, щось пішло не так під час пошуку 😕 Спробуй /start трохи пізніше.",
                              None)

    def _request_kind(self, update: dict) -> str:
        if "callback_query" in update:
            return "button"
        message = update.get("message") or {}
        text = str(message.get("text", "")).strip()
        if not text:
            return "media" if message else "other"
        if text.startswith("/"):
            command = text.split()[0].lower().split("@")[0]
            known = {"/start", "/subscribe", "/change", "/address", "/setting", "/settings", "/schedule", "/test", "/demo",
                     "/stop", "/status", "/help"}
            return command if command in known else "unknown_command"
        chat = str(message.get("chat", {}).get("id"))
        return "quiz_answer" if self.state.sessions.get(chat, {}).get("step") else "unknown_text"

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
                    self.stats["failure:ztoe"] += 1
                    print(f"warning: addresses for a subscriber's street unavailable: {exc}")  # no street id in logs
                    streets[sub.street_id] = None
            rows = streets[sub.street_id]
            if rows is None:
                continue  # try again next tick
            found = resolve_queue(rows, sub.house, sub.household())  # the home/business choice is kept
            sub.checked_at = now.isoformat()
            if found == "no_queue":
                continue  # 0.0 is not a queue: keep following the last real one
            try:
                if isinstance(found, tuple):
                    sub.problem = ""
                    if found != (sub.queue, sub.subqueue):
                        old = f"{sub.queue}.{sub.subqueue}"
                        sub.queue, sub.subqueue = found
                        sub.alerts = State()  # new queue: start its alert history fresh
                        changed += 1
                        self.stats["outcome:queue_moved"] += 1
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
            if sub.queue <= 0:
                continue  # 0.0 is "no queue" (subscriptions from before 16.10): nothing to alert about
            if key not in schedules:
                try:
                    schedules[key] = self.dir.schedule(*key)
                except ApiError as exc:
                    self.stats["failure:ztoe"] += 1
                    print(f"warning: schedule {key} unavailable: {exc}")
                    schedules[key] = None  # type: ignore[assignment]
            raw = schedules[key]
            if raw is None:
                continue
            settings = Settings(lead=timedelta(minutes=sub.lead_minutes), early=self.alert_early, label=sub.label)
            messages, new_alerts = plan(raw, now, sub.alerts, settings)
            try:
                for text in messages:
                    self.send(int(chat), text, None)
                    sent += 1
                    self.stats["outcome:alert_sent"] += 1
                    self.mark_reachable(chat)
            except Exception as exc:  # noqa: BLE001 - decide per error below
                if is_gone(exc):
                    self.stats["failure:chat_gone"] += 1
                    print(f"{chat_tag(chat)} blocked the bot or was deleted; unsubscribing")
                    self.state.subs.pop(chat, None)
                    continue
                self.stats["failure:telegram_send"] += 1
                print(f"warning: sending to {chat_tag(chat)} failed: {type(exc).__name__}; will retry next run")
                continue
            self._note_timeliness(sub, raw, now, settings, new_alerts)
            sub.alerts = new_alerts
        for key, raw in schedules.items():
            if raw is not None:
                self.track_schedule(key, raw, now)
        return sent

    def _note_timeliness(self, sub: Subscription, raw: list[dict], now: datetime, settings: Settings,
                         new_alerts: State) -> None:
        """How early each new alert went out, and which events passed since the last check with no alert."""
        for key in new_alerts.sent.keys() - sub.alerts.sent.keys():
            notice = (datetime.fromisoformat(new_alerts.sent[key]) - now).total_seconds() / 60
            # a late alert (sent with an apology) is always below 0, even when it is under a minute late
            self.alert_notices.append([min(-1, round(notice)) if notice <= 0 else round(notice), sub.lead_minutes])
        if sub.alerts.checked:  # nothing to compare with on the very first check
            since = datetime.fromisoformat(sub.alerts.checked)
            missed = [e for e in passed_events(raw, since, now, settings) if e.key not in new_alerts.sent]
            if missed:
                self.stats["outcome:alert_missed"] += len(missed)

    def watch_all_queues(self, now: datetime) -> None:
        """Every ~30 min, look at every queue's schedule so the dashboard can show how often it changes."""
        if not self.watch_all:
            return
        if self.state.watched_at and now - datetime.fromisoformat(self.state.watched_at) < WATCH_EVERY:
            return
        self.state.watched_at = now.isoformat()
        for key in WATCH_QUEUES:
            try:
                raw = self.dir.schedule(*key)
            except ApiError:
                self.stats["failure:ztoe_watch"] += 1
                continue
            self.track_schedule(key, raw, now)

    def track_schedule(self, key: tuple[int, int], raw: list[dict], now: datetime) -> None:
        """Record when a queue's schedule for a day is published or changed (for the dashboard).

        Each day is kept as 48 half-hour codes, so a change can be measured: how long before the
        first edited half-hour it came (notice_min, negative = edited after the fact) and how much
        outage it added or removed (more_off_min).
        """
        name = f"{key[0]}.{key[1]}"
        first_look = name not in self.state.watch
        days = self.state.watch.setdefault(name, {})
        for day, intervals in by_day(raw).items():
            if day < now.date():
                continue
            codes, old = day_codes(day, intervals), days.get(day.isoformat())
            days[day.isoformat()] = codes
            if first_look or old == codes or (old is not None and len(old) != len(codes)):
                continue  # the first look (or one stored in an older format) is only a baseline
            midnight = datetime.combine(day, datetime.min.time(), KYIV)
            event = {"queue": name, "day": day.isoformat(), "at": now.isoformat(timespec="minutes")}
            if old is None:
                event.update(kind="published", notice_min=_minutes(midnight - now))
            else:
                event["kind"] = "changed"
                first = next(i for i, (a, b) in enumerate(zip(old, codes)) if a != b)
                event["notice_min"] = _minutes(midnight + timedelta(minutes=30 * first) - now)
                event["more_off_min"] = 30 * (codes.count("x") - old.count("x"))
            self.stats[f"schedule:{event['kind']}"] += 1
            self.schedule_events.append(event)
        for day in [d for d in days if d < (now.date() - timedelta(days=1)).isoformat()]:
            del days[day]


def day_codes(day, intervals: list) -> str:
    """A day's schedule as 48 half-hour codes: o = power, x = outage, p = possible outage, ? = unknown."""
    midnight = datetime.combine(day, datetime.min.time(), KYIV)
    code = {Status.AVAILABLE: "o", Status.OUTAGE: "x", Status.PROBABLE: "p"}
    out = []
    for i in range(48):
        slot = status_at(intervals, midnight + timedelta(minutes=30 * i))
        out.append(code.get(slot.status, "?") if slot else "?")
    return "".join(out)


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _chat_of(update: dict) -> int | None:
    if "callback_query" in update:
        return ((update["callback_query"].get("message") or {}).get("chat") or {}).get("id")
    return ((update.get("message") or {}).get("chat") or {}).get("id")

