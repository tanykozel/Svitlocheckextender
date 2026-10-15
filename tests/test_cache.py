import threading
import unittest

from svitlo_notifier.api import ApiError
from svitlo_notifier.cache import ScheduleCache, start_refresher
from tests.test_bot import FakeDirectory


class FlakyDirectory(FakeDirectory):
    def __init__(self):
        super().__init__()
        self.down = False

    def schedule(self, queue, subqueue):
        if self.down:
            raise ApiError("ztoe down")
        return super().schedule(queue, subqueue)


class ScheduleCacheTests(unittest.TestCase):
    """Replies and alerts read schedules from memory; ZTOE is read in the background only."""

    def test_first_read_is_live_then_memory(self):
        live = FakeDirectory()
        cache = ScheduleCache(live)
        first = cache.schedule(1, 2)
        for _ in range(5):
            self.assertEqual(cache.schedule(1, 2), first)
        self.assertEqual(live.schedule_calls, [(1, 2)], "ZTOE asked once, then memory")

    def test_refresh_fetches_again_and_keeps_last_copy_on_failure(self):
        live = FlakyDirectory()
        cache = ScheduleCache(live)
        cache.refresh([(1, 1), (1, 2), (1, 2)])
        self.assertEqual(live.schedule_calls, [(1, 1), (1, 2)], "each queue once per round")
        live.down = True
        cache.refresh([(1, 1), (1, 2)])
        self.assertEqual(cache.take_errors(), 2)
        self.assertEqual(cache.take_errors(), 0, "counted once")
        self.assertTrue(cache.schedule(1, 2), "the last good copy stays in use while ZTOE is down")

    def test_address_quiz_stays_live(self):
        cache = ScheduleCache(FakeDirectory())
        self.assertEqual(cache.rems()[0]["id"], "16")

    def test_refresher_runs_until_stopped(self):
        live = FakeDirectory()
        cache = ScheduleCache(live)
        stop = threading.Event()
        thread = start_refresher(cache, lambda: [(3, 1)], every=0.01, stop=stop)
        for _ in range(500):
            if len(live.schedule_calls) >= 3:
                break
            stop.wait(0.01)
        stop.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertIsNotNone(cache.age(3, 1))


class FakeStop:
    """Stands in for threading.Event: records every wait and stops after a few rounds."""

    def __init__(self, rounds):
        self.waits, self.rounds = [], rounds

    def is_set(self):
        return self.rounds <= 0

    def wait(self, seconds):
        self.waits.append(seconds)
        if seconds >= 60:  # the wait between rounds
            self.rounds -= 1


class GentleOnZtoeTests(unittest.TestCase):
    """Owner decision D5: as few ZTOE requests as possible."""

    def test_requests_are_spaced_out(self):
        live = FakeDirectory()
        cache = ScheduleCache(live)
        pauses = []
        cache.refresh([(1, 1), (1, 2), (3, 1)], pause=2, wait=pauses.append)
        self.assertEqual(pauses, [2, 2], "one request at a time, 2 s apart, never a burst")

    def test_about_twelve_requests_an_hour_for_two_queues(self):
        live = FakeDirectory()
        stop = FakeStop(rounds=6)  # one hour at one round every 10 minutes
        start_refresher(ScheduleCache(live), lambda: {(1, 1), (1, 2)}, every=600, stop=stop).join(timeout=2)
        self.assertEqual(len(live.schedule_calls), 12)

    def test_a_round_with_errors_is_followed_by_a_longer_break(self):
        live = FlakyDirectory()
        live.down = True
        stop = FakeStop(rounds=2)
        start_refresher(ScheduleCache(live), lambda: {(1, 2)}, every=600, stop=stop).join(timeout=2)
        self.assertEqual([w for w in stop.waits if w >= 60], [1200, 1200], "ZTOE in trouble gets a break")


if __name__ == "__main__":
    unittest.main()
