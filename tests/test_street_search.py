import unittest

from svitlo_notifier.bot import Bot, BotState, as_buttons, match, name_of, similar
from tests.test_bot import FakeDirectory

# A slice of ZTOE's real street list for м. Звягель (public data), including its HTML-escaped names.
ZVYAHEL = [
    {"id": "178244", "name": "вул. Василя Карпенка"},
    {"id": "178245", "name": "вул. Василя Симоненка"},
    {"id": "178246", "name": "вул. Василя Стуса"},
    {"id": "178507", "name": "пров. 2-й Василя Карпенка"},
    {"id": "178550", "name": "пров. Василя Карпенка"},
    {"id": "178457", "name": "вул. СГТ &quot;Ветеран&quot; Садова"},
    {"id": "178424", "name": "вул. Садова"},
    {"id": "178494", "name": "вул. Шолом Алейхема"},
    {"id": "180316", "name": "вул. Шолом-Алейхема"},
    {"id": "178274", "name": "вул. Гордєєва"},
]
KARPENKA = {"178244", "178507", "178550"}


def ids(options):
    return {o["id"] for o in options}


class StreetSearchTests(unittest.TestCase):
    """Bug report 16.10: «В карпенка» was not found in м. Звягель."""

    def test_short_first_name_is_understood(self):
        self.assertEqual(ids(match(ZVYAHEL, "В карпенка")), KARPENKA)
        self.assertEqual(ids(match(ZVYAHEL, "карпенка вас")), KARPENKA, "any word order")

    def test_full_name_and_part_of_a_word_still_work(self):
        # the street and the lane of the same name are both offered; "2-й" lane only when the text fits it too
        self.assertEqual(ids(match(ZVYAHEL, "Василя карпенка")), {"178244", "178550"})
        self.assertEqual(ids(match(ZVYAHEL, "Карпенка")), KARPENKA)

    def test_html_escaped_names_are_shown_and_found_normally(self):
        veteran = next(o for o in ZVYAHEL if o["id"] == "178457")
        self.assertEqual(name_of(veteran), 'вул. СГТ "Ветеран" Садова')
        self.assertNotIn("&quot;", as_buttons([veteran], "s")[0][0][0])
        self.assertEqual(ids(match(ZVYAHEL, "ветеран садова")), {"178457"})

    def test_typo_gets_did_you_mean_suggestions(self):
        self.assertEqual(match(ZVYAHEL, "Василя Карпенко"), [])
        self.assertIn("178244", ids(similar(ZVYAHEL, "Василя Карпенко")))

    def test_old_street_name_is_not_guessed(self):
        self.assertEqual(match(ZVYAHEL, "Герцена"), [])
        self.assertEqual(similar(ZVYAHEL, "Герцена"), [], "no random suggestions for an unrelated name")


class StreetSearchInChatTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.dir = FakeDirectory()
        self.dir.streets = lambda city_id: ZVYAHEL
        self.state = BotState()
        self.bot = Bot(self.dir, lambda chat, text, buttons: self.sent.append((text, buttons)), self.state)
        self.state.sessions["5"] = {"step": "street", "rem": "16", "city": "16823", "city_name": "м. Звягель"}

    def test_three_karpenka_streets_offered_as_buttons(self):
        self.bot.pick_street_by_text(5, "В карпенка")
        text, buttons = self.sent[-1]
        self.assertIn("кілька варіантів", text)
        self.assertEqual(sum(len(row) for row in buttons), 3)

    def test_renamed_street_gets_a_helpful_hint(self):
        self.bot.pick_street_by_text(5, "Герцена")
        text, buttons = self.sent[-1]
        self.assertIn("перейменовано", text)
        self.assertIsNone(buttons)

    def test_typo_offers_did_you_mean_buttons(self):
        self.bot.pick_street_by_text(5, "Василя Карпенко")
        text, buttons = self.sent[-1]
        self.assertIn("Може, одне з цього?", text)
        self.assertTrue(buttons)


if __name__ == "__main__":
    unittest.main()
