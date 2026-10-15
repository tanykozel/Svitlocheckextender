"""Schedules kept in memory and refreshed in the background (always-on server).

The bot answers people and checks alerts every minute using these copies, so a reply never waits for
the ZTOE website. A background thread fetches every needed queue every few minutes. If ZTOE does not
answer, the last good copy stays in use (the schedule covers today and tomorrow) and the failure is
counted for the dashboard.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Iterable


class ScheduleCache:
    def __init__(self, directory, clock: Callable[[], float] = time.monotonic):
        self._dir = directory
        self._clock = clock
        self._lock = threading.Lock()
        self._data: dict[tuple[int, int], tuple[float, list[dict]]] = {}
        self._errors = 0

    def __getattr__(self, name):  # rems(), cities(), streets(), addresses(): always live (the address quiz)
        return getattr(self._dir, name)

    def schedule(self, queue: int, subqueue: int) -> list[dict]:
        """The cached schedule; fetched live only the first time a queue is needed (e.g. a new subscriber)."""
        with self._lock:
            hit = self._data.get((queue, subqueue))
        if hit is not None:
            return hit[1]
        raw = self._dir.schedule(queue, subqueue)  # errors go to the caller, like an uncached call
        with self._lock:
            self._data[(queue, subqueue)] = (self._clock(), raw)
        return raw

    def refresh(self, keys: Iterable[tuple[int, int]]) -> None:
        """Fetch each queue again; on failure keep the previous copy."""
        for key in sorted(set(keys)):
            try:
                raw = self._dir.schedule(*key)
            except Exception:  # noqa: BLE001 - one queue failing must not stop the others
                with self._lock:
                    self._errors += 1
                continue
            with self._lock:
                self._data[key] = (self._clock(), raw)

    def take_errors(self) -> int:
        """Failed background fetches since the last call (moved into the dashboard counters)."""
        with self._lock:
            errors, self._errors = self._errors, 0
        return errors

    def age(self, queue: int, subqueue: int) -> float | None:
        with self._lock:
            hit = self._data.get((queue, subqueue))
        return None if hit is None else self._clock() - hit[0]


def start_refresher(cache: ScheduleCache, keys: Callable[[], Iterable[tuple[int, int]]], every: float,
                    stop: threading.Event) -> threading.Thread:
    """Refresh `keys()` now and then every `every` seconds until `stop` is set."""
    def run() -> None:
        while not stop.is_set():
            try:
                cache.refresh(keys())
            except Exception:  # noqa: BLE001 - never let the refresher die; the next round retries
                pass
            stop.wait(every)

    thread = threading.Thread(target=run, name="ztoe-refresh", daemon=True)
    thread.start()
    return thread
