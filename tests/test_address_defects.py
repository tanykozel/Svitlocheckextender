"""Regression tests for the address-quiz defects reported on 16.10 (м. Житомир, real ZTOE rows)."""

import unittest

from svitlo_notifier.bot import (Bot, BotState, Subscription, house_key, house_options, parse_houses, resolve_queue,
                                 similar)
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

    def test_house_is_matched_as_zteo_writes_it(self):
        self.assertNotEqual(house_key("85-А"), house_key("85 а"), "a different spelling is offered, not taken")
        self.assertEqual(resolve_queue(PARADZHANOVA, "85-А"), (3, 2), "the 0.0 duplicate is ignored")
        self.assertEqual(resolve_queue(PARADZHANOVA, "85А"), "missing")

    def test_similar_spellings_are_suggested(self):
        for typed in ("85а", "85 а", "85А", "85"):
            self.assertEqual(house_options(PARADZHANOVA, typed), ["85-А"], typed)
        self.assertEqual(house_options(PARADZHANOVA, "8"), [], "«8» never suggests «87» or «85-А»")

    def test_latin_letters_and_unlisted_letters_are_suggested(self):
        # owner, 19.10: house typos get the official number to confirm, like streets
        self.assertEqual(house_options(PARADZHANOVA, "85a"), ["85-А"], "Latin a")
        self.assertEqual(house_options(PARADZHANOVA, "67A"), ["67А"], "Latin A")
        self.assertEqual(house_options(PARADZHANOVA, "87б"), ["87"], "a letter ZTOE does not list")
        self.assertEqual(house_options(PARADZHANOVA, "12/1"), ["12"], "a fraction ZTOE does not list")
        self.assertEqual(house_options(PARADZHANOVA, "999"), [])

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

    def test_street_without_a_queue_still_asks_for_the_house(self):
        # owner, 19.10: 0.0 is never taken silently - the house decides
        self.bot.handle_button(5, "s:176608")
        self.assertIn("4/4", self.last())
        self.assertEqual((self.state.subs["5"].queue, self.state.subs["5"].subqueue), (4, 2))

    def test_house_without_a_queue_is_followed(self):
        # owner, 19.10: 0.0 addresses can be followed; the house was matched exactly
        self.bot.handle_button(5, "s:176608")
        self.bot.handle_text(5, "1")
        sub = self.state.subs["5"]
        self.assertEqual((sub.queue, sub.subqueue, sub.street_id, sub.house), (0, 0, "176608", "1"))
        self.assertIn("в цей час не вимикається", self.last())
        self.assertIn("щойно з'явиться черга", self.last())

    def test_0_0_is_never_taken_for_an_unmatched_address(self):
        self.bot.handle_text(5, "Неіснуюча")  # no such street: nothing is offered or taken
        self.assertIn("Не знайшла", self.last())
        self.assertEqual(self.state.subs["5"].queue, 4)
        self.state.sessions["5"] = {"step": "house", "street": "176608", "city_name": "місто Житомир",
                                    "street_name": "автошлях Житомир - Сквира"}
        self.bot.handle_text(5, "999")  # a house ZTOE does not list
        self.assertIn("Не знайшла будинок «999»", self.last())
        self.assertEqual((self.state.subs["5"].queue, self.state.subs["5"].subqueue), (4, 2), "nothing taken")

    def test_followed_0_0_address_gets_no_alerts_and_hears_when_a_queue_appears(self):
        from datetime import datetime, timedelta
        from svitlo_notifier.schedule import KYIV
        self.bot.handle_button(5, "s:176608")
        self.bot.handle_text(5, "1")
        sub = self.state.subs["5"]
        self.bot.handle_text(5, "/schedule")
        self.assertIn("в цей час не вимикається", self.last())
        ROAD[0]["cherga"], ROAD[0]["pidcherga"] = 3, 1  # ZTOE assigns a queue later
        try:
            self.bot.refresh_queues(datetime.now(KYIV) + timedelta(hours=3))
        finally:
            ROAD[0]["cherga"], ROAD[0]["pidcherga"] = 0, 0
        self.assertEqual((sub.queue, sub.subqueue), (3, 1))
        self.assertIn("призначило чергу 3.1", self.last())

    def test_business_only_house_with_0_0_is_followed_too(self):
        self.bot.handle_button(5, "s:174365")
        self.bot.handle_text(5, "45")
        self.assertEqual(self.state.subs["5"].queue, 0)

    def test_house_87_subscribes_to_3_2(self):
        self.bot.handle_button(5, "s:174365")
        self.assertIn("4/4", self.last())
        self.bot.handle_text(5, "87")
        sub = self.state.subs["5"]
        self.assertEqual((sub.queue, sub.subqueue), (3, 2))

    def test_house_spelt_differently_must_be_confirmed(self):
        self.bot.handle_button(5, "s:174365")
        self.bot.handle_text(5, "85а")
        text, buttons = self.sent[-1]
        self.assertIn("Це будинок «85-А»?", text)
        self.assertEqual(buttons, [[("85-А", "h:0")]])
        self.assertEqual(self.state.subs["5"].queue, 4, "nothing changed before the tap")
        self.bot.handle_button(5, "h:0")
        sub = self.state.subs["5"]
        self.assertEqual((sub.queue, sub.subqueue, sub.house), (3, 2, "85-а"))

    def test_house_written_as_listed_is_taken_at_once(self):
        self.bot.handle_button(5, "s:174365")
        self.bot.handle_text(5, "85-а")
        self.assertEqual(self.state.subs["5"].queue, 3)

    def test_home_or_business_is_asked_when_queues_differ(self):
        # synthetic: house 10 listed for homes (5.1) and for businesses (2.1)
        both = PARADZHANOVA + [{"id": "9", "cherga": 2, "pidcherga": 1,
                                "name": "10 - непобутові (юридичні) споживачі"}]
        self.dir.addresses = lambda street_id: both
        self.bot.handle_button(5, "s:174365")
        self.bot.handle_text(5, "10")
        text, buttons = self.sent[-1]
        self.assertIn("і фізичну, і юридичну особу", text)
        self.assertEqual([row[0][1] for row in buttons], ["t:home", "t:business"])
        self.assertIn("5.1", buttons[0][0][0])
        self.assertIn("2.1", buttons[1][0][0])
        self.assertEqual(self.state.subs["5"].queue, 4, "nothing changed before the tap")
        self.bot.handle_button(5, "t:business")
        sub = self.state.subs["5"]
        self.assertEqual((sub.queue, sub.subqueue, sub.kind), (2, 1, "business"))
        restored = BotState.from_dict(self.state.to_dict()).subs["5"]
        self.assertEqual(restored.kind, "business")
        self.assertEqual(resolve_queue(both, "10", restored.household()), (2, 1), "the re-check keeps the choice")

    def test_no_question_when_both_types_share_a_queue_or_one_is_0_0(self):
        self.bot.handle_button(5, "s:174365")
        self.bot.handle_text(5, "87")  # business 3.2 only
        self.assertEqual(self.state.subs["5"].queue, 3)

    def test_old_house_button_is_ignored(self):
        self.bot.handle_button(5, "h:0")
        self.assertEqual(self.state.subs["5"].queue, 4)

    def test_typo_offers_the_right_street(self):
        self.bot.handle_text(5, "Паражанова")
        text, buttons = self.sent[-1]
        self.assertIn("Може, одне з цього?", text)
        self.assertEqual(buttons[0][0][1], "s:174365")

    def test_misspelt_street_is_offered_with_its_full_name(self):
        for typed in ("Паражвнова", "паражанова", "Параджанва"):
            self.bot.handle_text(5, typed)
            text, buttons = self.sent[-1]
            self.assertEqual(buttons[0][0], ("вул. Сергія Параджанова", "s:174365"), typed)
            self.assertEqual(self.state.subs["5"].queue, 4, "never picked without a tap")

    def test_partial_name_is_offered_not_picked(self):
        self.bot.handle_text(5, "Параджанова")
        text, buttons = self.sent[-1]
        self.assertEqual(buttons[0][0], ("вул. Сергія Параджанова", "s:174365"))
        self.assertNotIn("4/4", text)

    def test_exact_full_name_is_picked_at_once(self):
        self.bot.handle_text(5, "вул. Сергія Параджанова")
        self.assertIn("4/4", self.last())

    def test_typed_street_is_confirmed_with_its_official_name(self):
        # owner, 19.10: «Лесі Українки» typed at 3/4 left no ✅, unlike a tapped answer
        self.bot.handle_text(5, "Параджанова")  # partial: asked first, then tapped
        self.bot.handle_button(5, "s:174365")
        self.assertFalse(self.last().startswith("✅"), "a tap is marked on its question, not repeated")
        self.state.sessions["5"] = {"step": "street", "rem": "7", "city": "16657", "city_name": "місто Житомир"}
        self.bot.handle_text(5, "вул. сергія параджанова")
        self.assertTrue(self.last().startswith("✅ вул. Сергія Параджанова\n4/4."), self.last())
        self.bot.handle_text(5, "Сквира")  # no echo leaks into an unrelated message later
        self.assertFalse(self.last().startswith("✅ вул. Сергія"))


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

    def test_tapped_answer_stays_visible(self):
        """16.10: after the taps the chat showed 1/4, 2/4, 3/4 with no answers, as if the bot ran on alone."""
        shown = []
        self.bot._show_choice = lambda chat, message, text: shown.append((message, text))
        self.bot.handle_text(1, "/start")
        question = {"message_id": 1, "text": "1/4. Обери свій район (РЕМ):",
                    "reply_markup": {"inline_keyboard": [[{"text": "Звягельський", "callback_data": "r:16"},
                                                          {"text": "Житомирський", "callback_data": "r:7"}]]}}
        self.bot.handle_button(1, "r:16", question)
        self.assertEqual(shown, [(1, "1/4. Обери свій район (РЕМ):\n✅ Звягельський")])
        self.assertIn("2/4", self.sent[-1])

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
