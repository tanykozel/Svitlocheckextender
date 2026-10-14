"""Decide which alerts are due, given the schedule, the clock and what was already sent."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .schedule import (
    Event,
    EventKind,
    Interval,
    fingerprint,
    merge,
    parse_slots,
    status_at,
    transitions,
)


@dataclass
class State:
    sent: dict[str, str] = field(default_factory=dict)  # event key -> event time (ISO)
    days: dict[str, str] = field(default_factory=dict)  # schedule date (ISO) -> fingerprint
    checked: str = ""  # when alerts were last checked (ISO), to spot events that passed with no alert

    @classmethod
    def from_dict(cls, raw: dict) -> "State":
        return cls(sent=dict(raw.get("sent", {})), days=dict(raw.get("days", {})), checked=str(raw.get("checked", "")))

    def to_dict(self) -> dict:
        return {"sent": self.sent, "days": self.days, "checked": self.checked}


@dataclass(frozen=True)
class Settings:
    lead: timedelta = timedelta(minutes=30)
    notify_possible: bool = True
    notify_changes: bool = True
    label: str = ""  # e.g. "Дім" or "черга 3.1", shown in every message
    # GitHub may skip scheduled runs for 20-50 min. An alert whose moment passed in such a gap is
    # still sent (marked as late) while the new state lasts, instead of being dropped.
    catch_up: timedelta = timedelta(minutes=45)


def _hm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _span(interval: Interval) -> str:
    end = "24:00" if interval.end.hour == 0 and interval.end.minute == 0 else _hm(interval.end)
    return f"{_hm(interval.start)}–{end}"


SCHEDULE_URL = "https://www.ztoe.com.ua/unhooking-search.php"


def duration(delta: timedelta) -> str:
    """timedelta -> '4 год', '2 год 30 хв', '45 хв'."""
    minutes = round(delta.total_seconds() / 60)
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} год {rest} хв"
    return f"{hours} год" if hours else f"{rest} хв"


def _clock(moment: datetime, now: datetime) -> str:
    """'18:00', '24:00' for the coming midnight, or 'завтра 06:00'."""
    if moment.hour == 0 and moment.minute == 0 and moment.date() == now.date() + timedelta(days=1):
        return "24:00"
    if moment.date() != now.date():
        return f"завтра {_hm(moment)}" if moment.date() == now.date() + timedelta(days=1) else f"{moment:%d.%m %H:%M}"
    return _hm(moment)


def _at(moment: datetime, now: datetime) -> str:
    """'о 20:00', 'завтра о 06:00' or '15.10 о 06:00' (the coming midnight stays 'о 24:00')."""
    text = _clock(moment, now)
    if text.startswith("завтра "):
        return f"завтра о {text[len('завтра '):]}"
    if " " in text:  # 'DD.MM HH:MM'
        day, hm = text.split(" ")
        return f"{day} о {hm}"
    return f"о {text}"


def _until(moment: datetime, now: datetime) -> str:
    """'до 22:00', 'до 24:00', 'до 06:00 завтра'."""
    text = _clock(moment, now)
    if text.startswith("завтра "):
        return f"до {text[len('завтра '):]} завтра"
    return f"до {text}"


def describe_late_event(event: Event, now: datetime, label: str, next_off: Event | None = None) -> str:
    """The alert for a moment that already passed while no run was possible."""
    prefix = f"[{label}] " if label else ""
    sorry = "Вибач, що повідомляю із запізненням 🙏"
    if event.kind == EventKind.OFF:
        return (f"{prefix}🔴 {_at(event.at, now).capitalize()} мене мали вимкнути (за графіком) 😔\n"
                f"Без світла {_until(event.until, now)}.\n{sorry}")
    if event.kind == EventKind.POSSIBLE_OFF:
        return (f"{prefix}🟡 {_at(event.at, now).capitalize()} почалося можливе вимкнення - "
                f"{_until(event.until, now)}.\n{sorry}")
    text = f"{prefix}🟢 Я повернулася! {_at(event.at, now).capitalize()} світло мали увімкнути 💡"
    if next_off is not None:
        text += f"\nНаступного разу мене вимкнуть {_at(next_off.at, now)}."
    return f"{text}\n{sorry}"


def describe_event(event: Event, now: datetime, label: str, next_off: Event | None = None) -> str:
    minutes = max(1, round((event.at - now).total_seconds() / 60))
    prefix = f"[{label}] " if label else ""
    length = duration(event.until - event.at)
    if event.kind == EventKind.OFF:
        return (f"{prefix}🔴 За ~{minutes} хв, {_at(event.at, now)}, мене вимкнуть 😔\n"
                f"Без світла ~{length}, {_until(event.until, now)} (за графіком).\n"
                "Заряди телефон і павербанк 🔋\n"
                f"Повний графік: /schedule або {SCHEDULE_URL}")
    if event.kind == EventKind.POSSIBLE_OFF:
        return (f"{prefix}🟡 Можливо, за ~{minutes} хв, {_at(event.at, now)}, мене вимкнуть - "
                f"{_until(event.until, now)} (~{length}).\nКраще підготуйся заздалегідь 🔋")
    text = f"{prefix}🟢 Я повертаюся! За ~{minutes} хв, {_at(event.at, now)}, світло мають увімкнути 💡"
    if next_off is not None:
        text += (f"\nНаступного разу мене вимкнуть {_at(next_off.at, now)} - "
                 f"світло буде ~{duration(next_off.at - event.at)}.")
    else:
        text += "\nНаступних вимкнень за графіком поки немає 🎉"
    return text


def describe_day(day: date, intervals: list[Interval], label: str, changed: bool) -> str:
    prefix = f"[{label}] " if label else ""
    head = f"Графік на {day:%d.%m} змінився:" if changed else f"З'явився графік на {day:%d.%m}:"
    return f"{prefix}📅 {head}\n{day_lines(intervals)}\nПовний графік: {SCHEDULE_URL}"


def day_lines(intervals: list[Interval]) -> str:
    outages = [i for i in intervals if i.status.value in ("outage", "probable")]
    if not outages:
        return "відключень не заплановано 🎉"
    lines = [
        f"• {_span(i)} ({duration(i.end - i.start)}){' - можливе' if i.status.value == 'probable' else ''}"
        for i in outages
    ]
    off = sum((i.end - i.start for i in outages if i.status.value == "outage"), timedelta())
    lines.append(f"Разом без світла: {duration(off)}")
    return "\n".join(lines)


def schedule_text(raw: list[dict], now: datetime, label: str = "") -> str:
    """Today's and tomorrow's outage windows, for the /schedule command."""
    days = {d: i for d, i in by_day(raw).items() if d >= now.date()}
    head = f"📅 {label}\n" if label else "📅 "
    if not days:
        return f"{head}Графіка на сьогодні ще немає - щойно з'явиться, повідомлю.\nПовний графік: {SCHEDULE_URL}"
    names = {now.date(): "Сьогодні", now.date() + timedelta(days=1): "Завтра"}
    parts = [f"{names.get(d, f'{d:%d.%m}')} ({d:%d.%m}):\n{day_lines(i)}" for d, i in days.items()]
    return head + "\n\n".join(parts) + f"\n\nПовний графік: {SCHEDULE_URL}"


def by_day(raw: list[dict]) -> dict[date, list[Interval]]:
    days: dict[date, list] = defaultdict(list)
    for slot in parse_slots(raw):
        days[slot.start.date()].append(slot)
    return {d: merge(slots) for d, slots in sorted(days.items())}


def plan(raw: list[dict], now: datetime, state: State, settings: Settings) -> tuple[list[str], State]:
    """Return (messages to send now, new state). Pure: no I/O, no clock."""
    messages: list[str] = []
    new_state = State(sent=dict(state.sent), days=dict(state.days), checked=now.isoformat())

    days = by_day(raw)

    if settings.notify_changes:
        first_run = not state.days
        for day, intervals in days.items():
            if day < now.date():
                continue
            fp = fingerprint(intervals)
            old = state.days.get(day.isoformat())
            if not first_run and old != fp:
                messages.append(describe_day(day, intervals, settings.label, changed=old is not None))
            new_state.days[day.isoformat()] = fp

    timeline = merge([i for intervals in days.values() for i in intervals])
    events = transitions(timeline)
    fresh = not state.days and not state.sent  # a new subscriber gets no "late" news about the past
    catch_up = timedelta(0) if fresh else settings.catch_up
    for index, event in enumerate(events):
        if event.kind == EventKind.POSSIBLE_OFF and not settings.notify_possible:
            continue
        late = now - catch_up < event.at <= now and now < event.until
        if late and any(e.key in new_state.sent or e.at <= now + settings.lead for e in events[index + 1 :]):
            continue  # a newer alert is due or already out: send that one, not an apology about the past
        if not (late or now < event.at <= now + settings.lead):
            continue
        if event.key in new_state.sent:
            continue
        next_off = next((e for e in events[index + 1 :] if e.kind != EventKind.ON), None)
        describe = describe_late_event if late else describe_event
        messages.append(describe(event, now, settings.label, next_off))
        new_state.sent[event.key] = event.at.isoformat()

    horizon = now - timedelta(days=2)
    new_state.sent = {
        k: v for k, v in new_state.sent.items() if datetime.fromisoformat(v) >= horizon
    }
    new_state.days = {
        k: v for k, v in new_state.days.items() if date.fromisoformat(k) >= horizon.date()
    }
    return messages, new_state


def passed_events(raw: list[dict], since: datetime, now: datetime, settings: Settings) -> list[Event]:
    """Events between two alert checks (since, now]: each should have had an alert by now."""
    timeline = merge([i for intervals in by_day(raw).values() for i in intervals])
    return [e for e in transitions(timeline) if since < e.at <= now
            and (e.kind != EventKind.POSSIBLE_OFF or settings.notify_possible)]


_STATUS_UA = {"available": "світло є 💡", "outage": "світла немає 🔴", "probable": "можливе відключення 🟡",
              "unknown": "невідомо"}
_EVENT_UA = {"off": "вимкнення 🔴", "on": "увімкнення 🟢", "possible_off": "можливе вимкнення 🟡"}


def summary(raw: list[dict], now: datetime, label: str = "") -> str:
    """Human-readable 'now and next' view for the status command."""
    timeline = merge([i for intervals in by_day(raw).values() for i in intervals])
    current = status_at(timeline, now)
    lines = [f"{label}" if label else "Стан:"]
    if current is None:
        lines.append("Зараз за графіком: даних немає")
    else:
        lines.append(f"Зараз за графіком: {_STATUS_UA[current.status.value]} ({_span(current)})")
    upcoming = [e for e in transitions(timeline) if e.at > now][:6]
    if upcoming:
        lines.append("Далі за графіком:")
        lines += [f"• {_clock(e.at, now)} - {_EVENT_UA[e.kind.value]}" for e in upcoming]
    else:
        lines.append("Змін за графіком далі немає.")
    lines.append("(Аварійні відключення я не бачу - лише графік.)")
    return "\n".join(lines)
