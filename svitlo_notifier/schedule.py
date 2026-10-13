"""Turn raw schedule slots into intervals and power on/off transitions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")


class Status(str, Enum):
    AVAILABLE = "available"
    OUTAGE = "outage"
    PROBABLE = "probable"
    UNKNOWN = "unknown"

    @classmethod
    def from_color(cls, color: str | None) -> "Status":
        return {
            "white": cls.AVAILABLE,
            "green": cls.AVAILABLE,
            "red": cls.OUTAGE,
            "yellow": cls.PROBABLE,
        }.get((color or "").strip().lower(), cls.UNKNOWN)


class EventKind(str, Enum):
    OFF = "off"
    POSSIBLE_OFF = "possible_off"
    ON = "on"


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime
    status: Status


@dataclass(frozen=True)
class Event:
    kind: EventKind
    at: datetime
    until: datetime  # end of the interval the event starts

    @property
    def key(self) -> str:
        return f"{self.kind.value}@{self.at.isoformat()}"


def _parse_span(day: datetime, span: str) -> tuple[datetime, datetime] | None:
    try:
        start_raw, end_raw = (part.strip() for part in span.split("-"))
        sh, sm = (int(x) for x in start_raw.split(":"))
        eh, em = (int(x) for x in end_raw.split(":"))
    except ValueError:
        return None
    start = day + timedelta(hours=sh, minutes=sm)
    end = day + timedelta(hours=eh, minutes=em)  # "24:00" lands on next midnight
    if end <= start:
        end += timedelta(days=1)
    return start, end


def parse_slots(raw: list[dict], tz: ZoneInfo = KYIV) -> list[Interval]:
    slots = []
    for item in raw:
        try:
            day = datetime.strptime(str(item["date"]).strip(), "%d.%m.%Y").replace(tzinfo=tz)
        except (KeyError, ValueError):
            continue
        bounds = _parse_span(day, str(item.get("span", "")))
        if bounds is None:
            continue
        slots.append(Interval(*bounds, Status.from_color(item.get("color"))))
    return sorted(slots, key=lambda s: s.start)


def merge(slots: list[Interval]) -> list[Interval]:
    """Join back-to-back slots with the same status into one interval."""
    merged: list[Interval] = []
    for slot in slots:
        last = merged[-1] if merged else None
        if last and last.status == slot.status and last.end >= slot.start:
            merged[-1] = Interval(last.start, max(last.end, slot.end), last.status)
        else:
            merged.append(slot)
    return merged


def transitions(intervals: list[Interval]) -> list[Event]:
    """Status changes between adjacent intervals. Gaps in data produce no event."""
    events = []
    for prev, cur in zip(intervals, intervals[1:]):
        if prev.end != cur.start or prev.status == cur.status:
            continue
        if Status.UNKNOWN in (prev.status, cur.status):
            continue
        if cur.status == Status.OUTAGE:
            kind = EventKind.OFF
        elif cur.status == Status.PROBABLE:
            if prev.status == Status.OUTAGE:
                continue  # still no confirmed power; wait for AVAILABLE
            kind = EventKind.POSSIBLE_OFF
        else:
            kind = EventKind.ON
        events.append(Event(kind, cur.start, cur.end))
    return events


def status_at(intervals: list[Interval], moment: datetime) -> Interval | None:
    return next((i for i in intervals if i.start <= moment < i.end), None)


def fingerprint(intervals: list[Interval]) -> str:
    text = "|".join(f"{i.start.isoformat()}~{i.end.isoformat()}~{i.status.value}" for i in intervals)
    return hashlib.sha256(text.encode()).hexdigest()[:16]
