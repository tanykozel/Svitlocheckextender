"""Regression tests for the address-quiz defects reported on 16.10 (м. Житомир, real ZTOE rows)."""

import unittest

from svitlo_notifier.bot import Bot, BotState, Subscription, house_key, parse_houses, resolve_queue, similar
from svitlo_notifier.cache import ScheduleCache
from tests.test_bot import FakeDirectory

# ZTOE's rows for «вул. Сергія Параджанова» (street 174365), as returned on 16.10 (public data, shortened).
PARADZHANOVA = [
    {"id": "386093", "cherga": 5, "pidcherga": 1, "name": "10 - побутові споживачі, 12 - побутові споживачі"},
    {"id": "384641", "cherga": 3, "pidcherga": 2, "name": "117 - побутові споживачі, 67А - побутові споживачі"},
    {"id": "386519", "cherga": 1, "pidcherga": 1, "name": "123 - побутові споживачі"},
    {"id": "388929", "cherga": 0, "pidcherga": 0,
     "name": "45 - непобутові (юридичні) споживачі, 77 - непобутові (юридичні) споживачі"},
    {"id": "388934", "cherga": 0, "pidcherga": 0, "name": "85-А - непобутові (юридичні) споживачі"},
    {"id": "388942", "cherga": 3, "pidcherga": 2,
     "name": "87 - непобутові (юридичні) споживачі, 85-А - непобутові (юридичні) споживачі"},
    {"id": "388941", "cherga": 3, "pidcherga": 2, "name": "77 - непобутові (юридичні) споживачі"},
]
ROAD = [{"id": "1", "cherga": 0, "pidcherga": 0, "name": "1 - непобутові (юридичні) споживачі"}]
ZHYTOMYR_STREETS = [
    {"id": "176608", "name": "автошлях Житомир - Сквира"},
    {"id": "174365", "name": "вул. Сергія Параджанова"},
    {"id": "170001", "name": "вул. Велика Бердичівська"},
    {"id": "170002", "name": "пров Сергія Остапенка"},
]


class HouseNumberTests(unittest.TestCase):
    def test_business_listed_houses_are_read(self):
        self.assertEqual(parse_houses("87 - непобутові (юридичні) споживачі, 12 - побутові споживачі"),
                         [("87", False), ("12", True)])

    def test_house_87_is_found_in_queue_3_2(self):
        self.assertEqual(resolve_queue(PARADZHANOVA, "87"), (3, 2))

    def test_hyphens_and_spaces_do_not_matter(self):
        self.assertEqual(house_key("85-А"), house_key("85 а"))
        self.assertEqual(resolve_queue(PARADZHANOVA, "85А"), (3, 2), "the 0.0 duplicate is ignored")

    def test_households_still_work(self):
        self.assertEqual(resolve_queue(PARADZHANOVA, "12"), (5, 1))
        self.assertEqual(resolve_queue(PARADZHANOVA, "67а"), (3, 2))

    def test_queue_0_0_is_never_a_queue(self):
        self.assertEqual(resolve_queue(PARADZHANOVA, "45"), "no_queue")
        self.assertEqual(resolve_queue(ROAD, ""), "no_queue")
        self.assertEqual(resolve_queue(PARADZHANOVA, "999"), "missing")


class TypoTests(unittest.TestCase):
    def test_typo_in_one_word_finds_the_street(self):
        self.assertEqual([s["id"] for s in similar(ZHYTOMYR_STREETS, "Паражанова")], ["174365"])

    def test_unrelated_word_suggests_nothing(self):
        self.assertEqual(similar(ZHYTOMYR_STREETS, "Герцена"), [])


class QuizFlowTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.unbuttoned = []
        self.dir = FakeDirectory()
        self.dir.streets = lambda city_id: ZHYTOMYR_STREETS
        rows = {"176608": ROAD, "174365": PARADZHANOVA}
        self.dir.addresses = lambda street_id: rows[street_id]
        self.state = BotState()
        self.state.subs["5"] = Subscription(4, 2, "місто Житомир, пров Сергія Остапенка")
        self.bot = Bot(self.dir, lambda chat, text, buttons: self.sent.append((text, buttons)) or len(self.sent),
                       self.state, unbutton=lambda chat, message: self.unbuttoned.append(message))
        self.state.sessions["5"] = {"step": "street", "rem": "7", "city": "16657", "city_name": "місто Житомир"}

    def last(self):
        return self.sent[-1][0]

    def test_town_typed_again_at_the_street_step_is_not_a_street(self):
        self.bot.handle_text(5, "Житомир")
        self.assertIn("вже обрано", self.last())
        self.assertEqual(self.state.subs["5"].queue, 4, "address unchanged")

    def test_partial_street_match_needs_confirmation(self):
        self.bot.handle_text(5, "Сквира")
        text, buttons = self.sent[-1]
        self.assertIn("Це «автошлях Житомир - Сквира»?", text)
        self.assertTrue(buttons)
        self.assertEqual(self.state.subs["5"].queue, 4, "nothing changed before confirming")

    def test_address_without_a_queue_keeps_the_previous_one(self):
        self.bot.handle_button(5, "s:176608")
        self.assertIn("не вказує черги", self.last())
        self.assertEqual((self.state.subs["5"].queue, self.state.subs["5"].subqueue), (4, 2))
        self.assertNotIn("5", self.state.sessions)

    def test_house_87_subscribes_to_3_2(self):
        self.bot.handle_button(5, "s:174365")
        self.assertIn("4/4", self.last())
        self.bot.handle_text(5, "87")
        sub = self.state.subs["5"]
        self.assertEqual((sub.queue, sub.subqueue), (3, 2))

    def test_typo_offers_the_right_street(self):
        self.bot.handle_text(5, "Паражанова")
        text, buttons = self.sent[-1]
        self.assertIn("Може, одне з цього?", text)
        self.assertEqual(buttons[0][0][1], "s:174365")


class OldButtonTests(unittest.TestCase):
    """Tapping «місто Житомир» twice sent two «3/4», the second with an empty town name."""

    def setUp(self):
        self.sent = []
        self.unbuttoned = []
        self.dir = FakeDirectory()
        self.state = BotState()
        self.bot = Bot(self.dir, lambda chat, text, buttons: self.sent.append(text) or len(self.sent), self.state,
                       unbutton=lambda chat, message: self.unbuttoned.append(message))

    def test_second_tap_on_a_town_is_ignored(self):
        self.bot.handle_text(1, "/start")
        self.bot.handle_button(1, "r:16")
        self.bot.handle_button(1, "c:16823")
        count = len(self.sent)
        self.bot.handle_button(1, "c:16823")
        self.assertEqual(len(self.sent), count, "no second «3/4»")
        self.assertEqual(self.state.sessions["1"]["step"], "street")

    def test_buttons_disappear_when_tapped(self):
        self.bot.handle_text(1, "/start")
        self.bot.handle_button(1, "r:16")
        self.assertTrue(self.unbuttoned, "the district buttons were taken off at once")


class CachedListsTests(unittest.TestCase):
    def test_street_list_is_read_once_a_day(self):
        calls = []
        directory = FakeDirectory()
        directory.streets = lambda city_id: calls.append(city_id) or ZHYTOMYR_STREETS
        cache = ScheduleCache(directory)
        cache.streets("16657")
        cache.streets("16657")
        self.assertEqual(calls, ["16657"])


if __name__ == "__main__":
    unittest.main()
