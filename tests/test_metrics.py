import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from svitlo_notifier.api import ApiError
from svitlo_notifier.bot import WATCH_QUEUES, Bot, BotState, Subscription
from svitlo_notifier.cli import metrics_record
from svitlo_notifier.metrics import merge_run
from svitlo_notifier.schedule import KYIV
from svitlo_notifier.telegram import TelegramError
from tests.test_bot import FakeDirectory
from tests.test_planner import TODAY, TOMORROW, block, day_slots


def msg(update_id, chat, text):
    return {"update_id": update_id, "message": {"chat": {"id": chat}, "text": text}}


class DashboardCounterTests(unittest.TestCase):
    """US-16: the owner sees requests, outcomes and failures without any personal data."""

    def setUp(self):
        self.state = BotState()
        self.dir = FakeDirectory()
        self.bot = Bot(self.dir, lambda *_a: None, self.state)

    def test_requests_and_outcomes_are_counted_by_kind(self):
        self.bot.process_updates([msg(1, 5, "/start"), msg(2, 5, "/start")])  # the first is superseded
        self.bot.process_updates([{"update_id": 3, "callback_query": {
            "id": "q", "data": "r:16", "message": {"chat": {"id": 5}}}}])
        self.bot.process_updates([msg(4, 5, "Нівідкіля")])  # quiz answer, not found
        self.bot.process_updates([msg(5, 5, "сусли")])
        self.bot.process_updates([{"update_id": 6, "callback_query": {
            "id": "q", "data": "s:179889", "message": {"chat": {"id": 5}}}}])
        self.bot.process_updates([msg(7, 6, "привіт"), msg(8, 7, "/foo"),
                                  {"update_id": 9, "message": {"chat": {"id": 8}, "sticker": {}}}])
        self.bot.process_updates([msg(10, 5, "/stop")])
        stats = self.bot.stats
        self.assertEqual(stats["request:/start"], 1)
        self.assertEqual(stats["request:superseded"], 1)
        self.assertEqual(stats["request:button"], 2)
        self.assertEqual(stats["request:quiz_answer"], 2)
        self.assertEqual(stats["request:unknown_text"], 1)
        self.assertEqual(stats["request:unknown_command"], 1)
        self.assertEqual(stats["request:media"], 1)
        self.assertEqual(stats["outcome:not_found"], 1)
        self.assertEqual(stats["outcome:subscribed"], 1)
        self.assertEqual(stats["outcome:unsubscribed"], 1)

    def test_failures_are_counted(self):
        def down(*_a):
            raise ApiError("down")
        self.dir.cities = down
        self.bot.process_updates([msg(1, 5, "/start")])
        self.bot.process_updates([{"update_id": 2, "callback_query": {
            "id": "q", "data": "r:16", "message": {"chat": {"id": 5}}}}])
        self.assertEqual(self.bot.stats["failure:ztoe"], 1)

        self.state.subs = {"1": Subscription(3, 1, "A"), "2": Subscription(4, 1, "B")}

        def send(chat, *_a):
            raise TelegramError("blocked" if chat == 1 else "timeout")
        bot = Bot(self.dir, send, self.state)
        bot.send_alerts(datetime(2026, 10, 13, 7, 40, tzinfo=KYIV), is_gone=lambda e: "blocked" in str(e))
        self.assertEqual((bot.stats["failure:chat_gone"], bot.stats["failure:telegram_send"]), (1, 1))

    def test_record_has_no_chat_ids_or_addresses(self):
        self.state.subs = {"123456789": Subscription(1, 2, "с. Сусли, вул. Центральна 5", lead_minutes=60)}
        self.state.sessions = {"987654321": {"step": "city"}}
        record = metrics_record(self.bot, {"username": "svitlo_lusia_zt_bot"}, 3, 1.5)
        self.assertEqual((record["subscribers"], record["quizzes"]), (1, 1))
        self.assertEqual(record["by_queue"], {"1.2": 1})
        self.assertEqual(record["by_lead"], {"60": 1})
        text = json.dumps(record, ensure_ascii=False)
        for secret in ("123456789", "987654321", "Сусли", "Гранітна"):
            self.assertNotIn(secret, text)


class ScheduleChangeTrackingTests(unittest.TestCase):
    """Context for the dashboard: how often ZTOE publishes or changes a day's schedule."""

    def setUp(self):
        self.state = BotState()
        self.bot = Bot(FakeDirectory(), lambda *_a: None, self.state)
        self.now = datetime(2026, 10, 13, 15, 0, tzinfo=KYIV)

    def test_first_look_is_a_baseline_then_publish_and_change_are_counted(self):
        self.bot.track_schedule((1, 2), TODAY, self.now)
        self.assertEqual(self.bot.schedule_events, [])
        self.bot.track_schedule((1, 2), TODAY + TOMORROW, self.now)
        self.bot.track_schedule((1, 2), TODAY + TOMORROW, self.now)  # unchanged: nothing new
        self.bot.track_schedule((1, 2), TODAY + day_slots("14.10.2026", block(0, 4)), self.now)
        self.assertEqual([(e["queue"], e["day"], e["kind"]) for e in self.bot.schedule_events],
                         [("1.2", "2026-10-14", "published"), ("1.2", "2026-10-14", "changed")])
        self.assertEqual(self.bot.stats["schedule:changed"], 1)
        published, changed = self.bot.schedule_events
        self.assertEqual(published["notice_min"], 9 * 60, "tomorrow published 9 h before midnight")
        self.assertEqual(changed["notice_min"], 11 * 60, "first edited half-hour is 02:00 tomorrow")
        self.assertEqual(changed["more_off_min"], 120, "two more hours without power")
        restored = BotState.from_dict(self.state.to_dict())
        self.assertEqual(restored.watch, self.state.watch)

    def test_last_minute_and_after_the_fact_changes(self):
        self.bot.track_schedule((1, 2), TODAY, self.now)
        extra = day_slots("13.10.2026", {**block(8, 12), **block(16, 17), **block(18, 20, "yellow")})
        self.bot.track_schedule((1, 2), extra, self.now)  # at 15:00, 16:00-17:00 becomes an outage
        self.assertEqual(self.bot.schedule_events[-1]["notice_min"], 60)
        self.assertEqual(self.bot.schedule_events[-1]["more_off_min"], 60)
        earlier = day_slots("13.10.2026", {**block(8, 11), **block(16, 17), **block(18, 20, "yellow")})
        self.bot.track_schedule((1, 2), earlier, self.now)  # the morning outage edited afterwards
        self.assertEqual(self.bot.schedule_events[-1]["notice_min"], -240)
        self.assertEqual(self.bot.schedule_events[-1]["more_off_min"], -60)

    def test_all_queues_are_watched_every_30_minutes(self):
        directory = FakeDirectory()
        bot = Bot(directory, lambda *_a: None, self.state)
        bot.watch_all_queues(self.now)
        bot.watch_all_queues(self.now.replace(minute=20))
        self.assertEqual(len(directory.schedule_calls), len(WATCH_QUEUES))
        bot.watch_all_queues(self.now.replace(minute=31))
        self.assertEqual(len(directory.schedule_calls), 2 * len(WATCH_QUEUES))


class MergeTests(unittest.TestCase):
    def test_runs_daily_totals_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            record = {"ts": "2026-10-13T19:00:00+03:00", "subscribers": 2, "requests": {"/start": 2, "superseded": 4},
                      "outcomes": {"alert_sent": 1}, "failures": {"ztoe": 1},
                      "schedule_events": [{"queue": "1.2", "day": "2026-10-14", "kind": "published"}]}
            merge_run(folder, record, {"run_id": "1", "event": "schedule", "outcome": "success"})
            crashed = merge_run(folder, None, {"run_id": "2", "event": "schedule", "outcome": "failure"})
            self.assertEqual(crashed["failures"], {"run_crashed": 1})
            history = json.loads((folder / "history.json").read_text())
            self.assertEqual([h["run_id"] for h in history], ["1", "2"])
            self.assertNotIn("schedule_events", history[0])
            self.assertEqual(len(json.loads((folder / "events.json").read_text())), 1)
            day = json.loads((folder / "daily.json").read_text())["2026-10-13"]
            self.assertEqual((day["requests"], day["alerts"], day["subscribers_max"]), (2, 1, 2))
            self.assertEqual(day["failures"]["ztoe"], 1)
            self.assertEqual(day["failed_runs"], 1)


if __name__ == "__main__":
    unittest.main()
