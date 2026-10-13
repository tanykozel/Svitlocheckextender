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

    @classmethod
    def from_dict(cls, raw: dict) -> "State":
        return cls(sent=dict(raw.get("sent", {})), days=dict(raw.get("days", {})))

    def to_dict(self) -> dict:
        return {"sent": self.sent, "days": self.days}


@dataclass(frozen=True)
class Settings:
    lead: timedelta = timedelta(minutes=30)
    notify_possible: bool = True
    notify_changes: bool = True
    label: str = ""  # e.g. "Дім" or "черга 3.1", shown in every message


def _hm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _span(interval: Interval) -> str:
    end = "24:00" if interval.end.hour == 0 and interval.end.minute == 0 else _hm(interval.end)
    return f"{_hm(interval.start)}–{end}"


def describe_event(event: Event, now: datetime, label: str) -> str:
    minutes = max(1, round((event.at - now).total_seconds() / 60))
    prefix = f"[{label}] " if label else ""
    until = "24:00" if event.until.hour == 0 and event.until.minute == 0 else _hm(event.until)
    if event.kind == EventKind.OFF:
        return f"{prefix}🔴 Світло вимкнуть через ~{minutes} хв, о {_hm(event.at)} (до {until} за графіком)."
    if event.kind == EventKind.POSSIBLE_OFF:
        return f"{prefix}🟡 Можливе відключення через ~{minutes} хв, о {_hm(event.at)} (до {until})."
    return f"{prefix}🟢 Світло мають увімкнути через ~{minutes} хв, о {_hm(event.at)}."


def describe_day(day: date, intervals: list[Interval], label: str, changed: bool) -> str:
    prefix = f"[{label}] " if label else ""
    head = "змінено" if changed else "опубліковано"
    outages = [i for i in intervals if i.status.value in ("outage", "probable")]
    if not outages:
        body = "відключень не заплановано."
    else:
        body = "\n".join(
            f"• {_span(i)}{' (можливе)' if i.status.value == 'probable' else ''}" for i in outages
        )
    return f"{prefix}📅 Графік на {day:%d.%m} {head}:\n{body}"


def by_day(raw: list[dict]) -> dict[date, list[Interval]]:
    days: dict[date, list] = defaultdict(list)
    for slot in parse_slots(raw):
        days[slot.start.date()].append(slot)
    return {d: merge(slots) for d, slots in sorted(days.items())}


def plan(raw: list[dict], now: datetime, state: State, settings: Settings) -> tuple[list[str], State]:
    """Return (messages to send now, new state). Pure: no I/O, no clock."""
    messages: list[str] = []
    new_state = State(sent=dict(state.sent), days=dict(state.days))

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
    for event in transitions(timeline):
        if event.kind == EventKind.POSSIBLE_OFF and not settings.notify_possible:
            continue
        if not (now < event.at <= now + settings.lead):
            continue
        if event.key in new_state.sent:
            continue
        messages.append(describe_event(event, now, settings.label))
        new_state.sent[event.key] = event.at.isoformat()

    horizon = now - timedelta(days=2)
    new_state.sent = {
        k: v for k, v in new_state.sent.items() if datetime.fromisoformat(v) >= horizon
    }
    new_state.days = {
        k: v for k, v in new_state.days.items() if date.fromisoformat(k) >= horizon.date()
    }
    return messages, new_state


def summary(raw: list[dict], now: datetime, label: str = "") -> str:
    """Human-readable 'now and next' view for the status command."""
    timeline = merge([i for intervals in by_day(raw).values() for i in intervals])
    current = status_at(timeline, now)
    lines = [f"{label}:" if label else "Статус:"]
    if current is None:
        lines.append("  зараз: немає даних у графіку")
    else:
        lines.append(f"  зараз: {current.status.value} ({_span(current)})")
    upcoming = [e for e in transitions(timeline) if e.at > now][:6]
    for event in upcoming:
        lines.append(f"  {event.at:%d.%m %H:%M} → {event.kind.value}")
    if not upcoming:
        lines.append("  змін далі за графіком немає")
    return "\n".join(lines)
