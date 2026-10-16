import unittest
from datetime import datetime, timedelta

from svitlo_notifier.planner import Settings, State, plan, summary
from svitlo_notifier.schedule import KYIV, EventKind, Status, merge, parse_slots, transitions


def day_slots(date: str, outages: dict[str, str]) -> list[dict]:
    """48 half-hour slots for a day; `outages` maps "HH:MM" slot starts to a color."""
    slots = []
    for i in range(48):
        start = f"{i // 2:02d}:{30 * (i % 2):02d}"
        end_minutes = (i + 1) * 30
        end = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
        slots.append({"date": date, "span": f"{start}-{end}", "color": outages.get(start, "white")})
    return slots


def block(start_hour: int, end_hour: int, color: str = "red") -> dict[str, str]:
    return {f"{h:02d}:{m:02d}": color for h in range(start_hour, end_hour) for m in (0, 30)}


TODAY = day_slots("13.10.2026", {**block(8, 12), **block(18, 20, "yellow")})
TOMORROW = day_slots("14.10.2026", block(0, 2))


def at(hh: int, mm: int = 0, day: int = 13) -> datetime:
    return datetime(2026, 10, day, hh, mm, tzinfo=KYIV)


class ScheduleTests(unittest.TestCase):
    def test_merges_half_hour_slots_and_handles_midnight(self):
        intervals = merge(parse_slots(TODAY))
        self.assertEqual(
            [(i.start.hour, i.end.hour, i.status) for i in intervals],
            [(0, 8, Status.AVAILABLE), (8, 12, Status.OUTAGE), (12, 18, Status.AVAILABLE),
             (18, 20, Status.PROBABLE), (20, 0, Status.AVAILABLE)],
        )
        self.assertEqual(intervals[-1].end, at(0, day=14))

    def test_transitions_cross_days(self):
        events = transitions(merge(parse_slots(TODAY + TOMORROW)))
        self.assertEqual(
            [(e.kind, e.at) for e in events],
            [(EventKind.OFF, at(8)), (EventKind.ON, at(12)), (EventKind.POSSIBLE_OFF, at(18)),
             (EventKind.ON, at(20)), (EventKind.OFF, at(0, day=14)), (EventKind.ON, at(2, day=14))],
        )

    def test_bad_rows_are_skipped(self):
        raw = [{"date": "bad", "span": "00:00-00:30", "color": "red"},
               {"date": "13.10.2026", "span": "nonsense", "color": "red"}]
        self.assertEqual(parse_slots(raw), [])


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(lead=timedelta(minutes=30), notify_changes=False)

    def test_alerts_inside_lead_window_only_once(self):
        messages, state = plan(TODAY, at(7, 40), State(), self.settings)
        self.assertEqual(len(messages), 1)
        self.assertIn("За ~20 хв, о 08:00, мене вимкнуть", messages[0])
        self.assertIn("до 12:00", messages[0])

        again, _ = plan(TODAY, at(7, 50), state, self.settings)
        self.assertEqual(again, [])

    def test_no_alert_too_early_or_after_the_fact(self):
        self.assertEqual(plan(TODAY, at(7, 0), State(), self.settings)[0], [])
        self.assertEqual(plan(TODAY, at(8, 5), State(), self.settings)[0], [])

    def test_alert_missed_in_a_run_gap_is_sent_late_once(self):
        # Lead 15 min, runs at 07:40 and then only at 12:20: the 12:00 power-back moment fell in the gap.
        quick = Settings(lead=timedelta(minutes=15), notify_changes=False)
        _, state = plan(TODAY, at(7, 50), State(), quick)  # the 08:00 off alert went out
        messages, state = plan(TODAY, at(12, 20), state, quick)
        self.assertEqual(len(messages), 1)
        self.assertIn("Я повернулася! О 12:00 світло мали увімкнути", messages[0])
        self.assertIn("із запізненням", messages[0])
        self.assertEqual(plan(TODAY, at(12, 30), state, quick)[0], [])

    def test_late_alert_has_limits(self):
        quick = Settings(lead=timedelta(minutes=15), notify_changes=False)
        _, state = plan(TODAY, at(7, 50), State(), quick)
        self.assertEqual(plan(TODAY, at(13, 0), state, quick)[0], [])  # too long ago
        self.assertEqual(plan(TODAY, at(12, 20), State(), quick)[0], [])  # brand-new subscriber

    def test_new_subscriber_gets_no_apology_a_minute_later(self):
        # Owner's report 16.10: subscribed at 08:31 during the 08:00 outage, got «Вибач… із запізненням» at 08:32.
        live = Settings(lead=timedelta(minutes=30))  # as the bot runs: schedule-change news on
        first, state = plan(TODAY, at(8, 31), State(), live)
        self.assertEqual(first, [])
        self.assertEqual(plan(TODAY, at(8, 32), state, live)[0], [])
        later, _ = plan(TODAY, at(11, 45), state, live)
        self.assertEqual(len(later), 1, "the next real alert (power back at 12:00) still comes")

    def test_newer_alert_replaces_the_late_one(self):
        # 18:00 possible outage with a 30-min lead: at 17:45 that alert is due, so the missed
        # 17:30-ish news is not sent as an apology. Same if the newer alert already went out.
        quick = Settings(lead=timedelta(minutes=30), notify_changes=False, catch_up=timedelta(hours=6))
        _, state = plan(TODAY, at(7, 50), State(), quick)
        messages, state = plan(TODAY, at(17, 45), state, quick)
        self.assertEqual(len(messages), 1)
        self.assertIn("о 18:00", messages[0])
        self.assertNotIn("запізненням", messages[0])
        self.assertEqual(plan(TODAY, at(18, 10), state, quick)[0], [])

    def test_early_window_keeps_the_promised_notice(self):
        # Checked every minute: with 1 min of slack a 30-min alert arrives 30-31 min ahead, never 29.
        early = Settings(lead=timedelta(minutes=30), early=timedelta(minutes=1), notify_changes=False)
        messages, _ = plan(TODAY, at(7, 29), State(), early)
        self.assertEqual(len(messages), 1)
        self.assertIn("За ~31 хв, о 08:00", messages[0])
        self.assertEqual(plan(TODAY, at(7, 28), State(), early)[0], [])

    def test_power_back_alert(self):
        messages, _ = plan(TODAY, at(11, 45), State(), self.settings)
        self.assertEqual(len(messages), 1)
        self.assertIn("За ~15 хв, о 12:00, світло мають увімкнути", messages[0])

    def test_possible_outage_can_be_muted(self):
        self.assertEqual(len(plan(TODAY, at(17, 45), State(), self.settings)[0]), 1)
        muted = Settings(lead=timedelta(minutes=30), notify_possible=False, notify_changes=False)
        self.assertEqual(plan(TODAY, at(17, 45), State(), muted)[0], [])

    def test_schedule_published_and_changed(self):
        settings = Settings(notify_changes=True, lead=timedelta(minutes=1))
        first, state = plan(TODAY, at(13), State(), settings)
        self.assertEqual(first, [], "first run only records the baseline")

        published, state = plan(TODAY + TOMORROW, at(14), state, settings)
        self.assertEqual(len(published), 1)
        self.assertIn("З'явився графік на 14.10", published[0])
        self.assertIn("00:00–02:00", published[0])

        changed_tomorrow = day_slots("14.10.2026", block(0, 4))
        changed, state = plan(TODAY + changed_tomorrow, at(15), state, settings)
        self.assertEqual(len(changed), 1)
        self.assertIn("змінився", changed[0])
        self.assertIn("00:00–04:00", changed[0])

        unchanged, _ = plan(TODAY + changed_tomorrow, at(16), state, settings)
        self.assertEqual(unchanged, [])

    def test_old_state_is_pruned(self):
        old = State(sent={"off@2026-10-01T08:00:00+03:00": "2026-10-01T08:00:00+03:00"},
                    days={"2026-10-01": "x"})
        _, state = plan(TODAY, at(13), old, self.settings)
        self.assertEqual(state.sent, {})
        self.assertNotIn("2026-10-01", state.days)

    def test_off_alert_says_how_long_and_links_full_schedule(self):
        messages, _ = plan(TODAY, at(7, 40), State(), self.settings)
        self.assertIn("Без світла ~4 год, до 12:00", messages[0])
        self.assertIn("ztoe.com.ua/unhooking-search.php", messages[0])

    def test_on_alert_mentions_next_outage(self):
        messages, _ = plan(TODAY, at(11, 45), State(), self.settings)
        self.assertIn("Наступного разу мене вимкнуть о 18:00 - світло буде ~6 год", messages[0])
        last_on, _ = plan(TODAY, at(19, 45), State(), self.settings)
        self.assertIn("Наступних вимкнень за графіком поки немає", last_on[0])

    def test_schedule_text_lists_durations_and_total(self):
        from svitlo_notifier.planner import duration, schedule_text
        text = schedule_text(TODAY + TOMORROW, at(9), "Дім")
        self.assertIn("Сьогодні (13.10):\n• 08:00–12:00 (4 год)\n• 18:00–20:00 (2 год) - можливе", text)
        self.assertIn("Разом без світла: 4 год", text)
        self.assertIn("Завтра (14.10):\n• 00:00–02:00 (2 год)", text)
        self.assertEqual(duration(timedelta(minutes=150)), "2 год 30 хв")
        self.assertEqual(duration(timedelta(minutes=45)), "45 хв")

    def test_label_prefix_and_summary(self):
        settings = Settings(lead=timedelta(minutes=30), notify_changes=False, label="Дім")
        messages, _ = plan(TODAY, at(7, 40), State(), settings)
        self.assertTrue(messages[0].startswith("[Дім] "))
        text = summary(TODAY, at(9), "Дім")
        self.assertIn("Зараз за графіком: світла немає 🔴 (08:00–12:00)", text)
        self.assertIn("Аварійні відключення я не бачу", text)
        self.assertIn("• 12:00 - увімкнення 🟢", text)


if __name__ == "__main__":
    unittest.main()


class UkrainianGrammarTests(unittest.TestCase):
    def test_next_day_times_read_naturally(self):
        raw = day_slots("13.10.2026", block(20, 22)) + day_slots("14.10.2026", block(6, 10))
        messages, _ = plan(raw, at(21, 30), State(), Settings(lead=timedelta(minutes=30), notify_changes=False))
        self.assertIn("Наступного разу мене вимкнуть завтра о 06:00", messages[0])
        self.assertNotIn("о завтра", messages[0])

    def test_outage_crossing_midnight(self):
        raw = day_slots("13.10.2026", block(22, 24)) + day_slots("14.10.2026", block(0, 2))
        messages, _ = plan(raw, at(21, 40), State(), Settings(lead=timedelta(minutes=30), notify_changes=False))
        self.assertIn("о 22:00, мене вимкнуть", messages[0])
        self.assertIn("до 02:00 завтра", messages[0])
