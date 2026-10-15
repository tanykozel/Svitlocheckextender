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


if __name__ == "__main__":
    unittest.main()
