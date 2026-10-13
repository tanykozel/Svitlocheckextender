import unittest
from datetime import datetime, timedelta

from svitlo_notifier.api import ApiError
from svitlo_notifier.bot import Bot, BotState, Subscription, house_numbers, match, normalize
from svitlo_notifier.schedule import KYIV
from svitlo_notifier.telegram import TelegramError
from tests.test_planner import TODAY


class FakeDirectory:
    def __init__(self):
        self.schedule_calls = []

    def rems(self):
        return [{"id": "16", "name": "Звягельський"}, {"id": "7", "name": "Житомирський"}]

    def cities(self, rem_id):
        return [{"id": "16823", "name": "м. Звягель", "rem_id": rem_id},
                {"id": "17012", "name": "с. Сусли", "rem_id": rem_id},
                {"id": "16951", "name": "с. Мокляки", "rem_id": rem_id},
                {"id": "17028", "name": "с. Хутір-Мокляки", "rem_id": rem_id}]

    def streets(self, city_id):
        if city_id == "16823":  # a big town: more streets than fit as buttons
            return [{"id": str(i), "name": f"вул. Вулиця {i}"} for i in range(40)] + [
                {"id": "500", "name": "вул. Центральна"}]
        return [{"id": "179892", "name": "вул. Центральна"}, {"id": "179889", "name": "вул. Садова"}]

    def addresses(self, street_id):
        if street_id == "179889":  # whole street in one queue
            return [{"id": "1", "name": "1 - побутові споживачі, 3 - побутові споживачі",
                     "cherga": 2, "pidcherga": 2}]
        return [{"id": "1", "name": "10 - побутові споживачі, 12А - побутові споживачі", "cherga": 3, "pidcherga": 1},
                {"id": "2", "name": "14 - побутові споживачі", "cherga": 5, "pidcherga": 2}]

    def schedule(self, queue, subqueue):
        self.schedule_calls.append((queue, subqueue))
        return TODAY


class BotTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.state = BotState()
        self.dir = FakeDirectory()
        self.bot = Bot(self.dir, lambda chat, text, buttons: self.sent.append((chat, text, buttons)), self.state)

    def last(self):
        return self.sent[-1]

    def updates(self, *items):
        out = []
        for i, item in enumerate(items, start=100 + len(self.sent)):
            if item.startswith("btn:"):
                out.append({"update_id": i, "callback_query": {
                    "id": f"q{i}", "data": item[4:], "message": {"chat": {"id": 42}}}})
            else:
                out.append({"update_id": i, "message": {"chat": {"id": 42}, "text": item}})
        return out

    def test_full_quiz_with_typed_village_street_and_house(self):
        self.bot.process_updates(self.updates("/start"))
        chat, text, buttons = self.last()
        self.assertEqual(chat, 42)
        self.assertIn("1/4", text)
        self.assertIn(("Звягельський", "r:16"), [b for row in buttons for b in row])

        self.bot.process_updates(self.updates("btn:r:16"))
        _, text, buttons = self.last()
        self.assertIn("2/4", text)
        labels = [b[0] for row in buttons for b in row]
        self.assertEqual(labels, ["м. Звягель"], "only towns are offered as buttons, villages are typed")

        self.bot.process_updates(self.updates("сусли"))
        _, text, buttons = self.last()
        self.assertIn("3/4. с. Сусли", text)
        self.assertEqual(len(buttons), 1)

        self.bot.process_updates(self.updates("btn:s:179892"))
        self.assertIn("4/4", self.last()[1])

        last_update = self.updates("12а")
        self.bot.process_updates(last_update)
        _, text, _ = self.last()
        self.assertIn("✅", text)
        self.assertIn("черга 3.1", text)
        sub = self.state.subs["42"]
        self.assertEqual((sub.queue, sub.subqueue, sub.label), (3, 1, "с. Сусли, вул. Центральна 12а"))
        self.assertNotIn("42", self.state.sessions)
        self.assertEqual(self.state.offset, last_update[-1]["update_id"] + 1, "offset confirms handled updates")

    def test_street_with_one_queue_skips_house_question(self):
        self.bot.process_updates(self.updates("/start", "btn:r:16", "Сусли", "btn:s:179889"))
        self.assertIn("черга 2.2", self.last()[1])

    def test_big_town_asks_to_type_street(self):
        self.bot.process_updates(self.updates("/start", "btn:r:16", "btn:c:16823"))
        self.assertIn("напишіть назву вулиці", self.last()[1])
        self.bot.process_updates(self.updates("Центральна"))
        self.assertIn("4/4", self.last()[1])

    def test_ambiguous_and_unknown_answers(self):
        self.bot.process_updates(self.updates("/start", "btn:r:16", "мокл"))
        _, text, buttons = self.last()
        self.assertIn("кілька варіантів", text)
        self.assertEqual([b[1] for row in buttons for b in row], ["c:16951", "c:17028"])
        self.bot.process_updates(self.updates("btn:c:17028"))
        self.assertIn("3/4. с. Хутір-Мокляки", self.last()[1], "name remembered for the tapped option")
        self.bot.process_updates(self.updates("/start", "btn:r:16", "Атлантида"))
        self.assertIn("Не знайшов", self.last()[1])

    def test_exact_name_beats_partial(self):
        found = match(FakeDirectory().cities("16"), "Мокляки")
        self.assertEqual([c["id"] for c in found], ["16951"])

    def test_unknown_house_and_stop(self):
        self.bot.process_updates(self.updates("/start", "btn:r:16", "Сусли", "btn:s:179892", "99"))
        self.assertIn("не знайдено", self.last()[1])
        self.bot.process_updates(self.updates("10"))
        self.assertIn("42", self.state.subs)
        self.bot.process_updates(self.updates("/stop"))
        self.assertNotIn("42", self.state.subs)

    def test_api_failure_tells_user_and_continues(self):
        def broken(_rem):
            raise ApiError("down")
        self.dir.cities = broken
        self.bot.process_updates(self.updates("/start", "btn:r:16"))
        self.assertIn("Сталася помилка", self.last()[1])
        self.assertIsNotNone(self.state.offset)

    def test_alerts_fetch_each_queue_once_and_drop_blocked_chats(self):
        self.state.subs = {"1": Subscription(3, 1, "A"), "2": Subscription(3, 1, "B"),
                           "3": Subscription(3, 1, "C")}
        sends = []

        def send(chat, text, _buttons):
            if chat == 3:
                raise TelegramError("sendMessage rejected: Forbidden: bot was blocked by the user")
            sends.append((chat, text))

        bot = Bot(self.dir, send, self.state)
        now = datetime(2026, 10, 13, 7, 40, tzinfo=KYIV)
        sent = bot.send_alerts(now, is_gone=lambda e: "blocked" in str(e))
        self.assertEqual(sent, 2)
        self.assertEqual(self.dir.schedule_calls, [(3, 1)])
        self.assertEqual([c for c, _ in sends], [1, 2])
        self.assertTrue(sends[0][1].startswith("[A] 🔴"))
        self.assertNotIn("3", self.state.subs)
        self.assertEqual(bot.send_alerts(now), 0, "no duplicates on the next tick")

    def test_state_round_trip(self):
        self.bot.process_updates(self.updates("/start", "btn:r:16", "Сусли", "btn:s:179889"))
        restored = BotState.from_dict(self.state.to_dict())
        self.assertEqual(restored.subs["42"].queue, 2)
        self.assertEqual(restored.offset, self.state.offset)


class AddressAndSettingsTests(BotTests.__base__):
    """US-8 one address / change it, US-9 warning time, US-10 schedule view."""

    def setUp(self):
        self.sent = []
        self.state = BotState()
        self.dir = FakeDirectory()
        self.bot = Bot(self.dir, lambda chat, text, buttons: self.sent.append((chat, text, buttons)), self.state)
        self.n = 0

    def say(self, *items):
        out = []
        for item in items:
            self.n += 1
            if item.startswith("btn:"):
                out.append({"update_id": self.n, "callback_query": {
                    "id": str(self.n), "data": item[4:], "message": {"chat": {"id": 7}}}})
            else:
                out.append({"update_id": self.n, "message": {"chat": {"id": 7}, "text": item}})
        self.bot.process_updates(out)
        return self.sent[-1]

    def subscribe_sadova(self):
        return self.say("/start", "btn:r:16", "Сусли", "btn:s:179889")

    def test_start_when_subscribed_offers_change_or_keep(self):
        self.subscribe_sadova()
        _, text, buttons = self.say("/start")
        self.assertIn("Ваша адреса: с. Сусли, вул. Садова (черга 2.2)", text)
        self.assertIn("лише на одну адресу", text)
        self.assertEqual(buttons, [[("Змінити адресу", "a:change"), ("Залишити", "a:keep")]])
        self.assertIn("залишено", self.say("btn:a:keep")[1])
        self.assertEqual(self.state.subs["7"].queue, 2)

    def test_change_address_replaces_old_one_and_keeps_lead(self):
        self.subscribe_sadova()
        self.say("/settings", "btn:l:60")
        self.state.subs["7"].alerts.sent["off@x"] = "2026-10-13T08:00:00+03:00"
        self.say("/change", "btn:r:16", "Сусли", "btn:s:179892")
        _, text, _ = self.say("14")
        self.assertIn("✅ Адресу змінено", text)
        self.assertEqual(len(self.state.subs), 1)
        sub = self.state.subs["7"]
        self.assertEqual((sub.queue, sub.subqueue, sub.lead_minutes), (5, 2, 60))
        self.assertEqual(sub.alerts.sent, {}, "alert history restarts for the new queue")

    def test_settings_lead_time_changes_when_alerts_fire(self):
        self.subscribe_sadova()
        _, text, buttons = self.say("/settings")
        self.assertIn("Зараз: 30 хв", text)
        self.assertEqual([b[1] for b in buttons[0]], ["l:15", "l:30", "l:60"])
        self.assertTrue(buttons[0][1][0].startswith("✓"))
        self.assertIn("за 60 хв", self.say("btn:l:60")[1])

        sent = []
        bot = Bot(self.dir, lambda chat, text, _b: sent.append(text), self.state)
        bot.send_alerts(datetime(2026, 10, 13, 7, 10, tzinfo=KYIV))  # 50 min before the 08:00 outage
        self.assertEqual(len(sent), 1)
        self.assertIn("через ~50 хв", sent[0])

    def test_unknown_lead_value_is_ignored(self):
        self.subscribe_sadova()
        self.say("btn:l:999")
        self.assertEqual(self.state.subs["7"].lead_minutes, 30)

    def test_schedule_command(self):
        self.assertIn("Спершу оберіть адресу", self.say("/schedule")[1])
        self.subscribe_sadova()
        _, text, _ = self.say("/schedule")
        self.assertIn("черга 2.2", text)
        self.assertIn("https://www.ztoe.com.ua/unhooking-search.php", text)


class HelperTests(unittest.TestCase):
    def test_normalize_and_house_numbers(self):
        self.assertEqual(normalize("  вул.  Кам’яна "), "кам'яна")
        self.assertEqual(normalize("с. Сусли"), "сусли")
        self.assertEqual(house_numbers("25 - побутові споживачі, 27А - побутові споживачі"), ["25", "27а"])
        self.assertEqual(house_numbers("5/1"), ["5/1"])


if __name__ == "__main__":
    unittest.main()
