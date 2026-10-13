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
        sent = bot.send_alerts(now, timedelta(minutes=30), is_gone=lambda e: "blocked" in str(e))
        self.assertEqual(sent, 2)
        self.assertEqual(self.dir.schedule_calls, [(3, 1)])
        self.assertEqual([c for c, _ in sends], [1, 2])
        self.assertTrue(sends[0][1].startswith("[A] 🔴"))
        self.assertNotIn("3", self.state.subs)
        self.assertEqual(bot.send_alerts(now, timedelta(minutes=30)), 0, "no duplicates on the next tick")

    def test_state_round_trip(self):
        self.bot.process_updates(self.updates("/start", "btn:r:16", "Сусли", "btn:s:179889"))
        restored = BotState.from_dict(self.state.to_dict())
        self.assertEqual(restored.subs["42"].queue, 2)
        self.assertEqual(restored.offset, self.state.offset)


class HelperTests(unittest.TestCase):
    def test_normalize_and_house_numbers(self):
        self.assertEqual(normalize("  вул.  Кам’яна "), "кам'яна")
        self.assertEqual(normalize("с. Сусли"), "сусли")
        self.assertEqual(house_numbers("25 - побутові споживачі, 27А - побутові споживачі"), ["25", "27а"])
        self.assertEqual(house_numbers("5/1"), ["5/1"])


if __name__ == "__main__":
    unittest.main()
