import unittest

from svitlo_notifier.bot import Bot, BotState, Subscription, label_without_house
from svitlo_notifier.secure import chat_tag
from tests.test_bot import FakeDirectory


def msg(update_id, chat, text):
    return {"update_id": update_id, "message": {"chat": {"id": chat}, "text": text}}


class PrivacyTests(unittest.TestCase):
    """Owner decision D6 (16.10): a simple privacy policy (/privacy); /stop deletes everything."""

    def setUp(self):
        self.sent = []
        self.state = BotState()
        self.bot = Bot(FakeDirectory(), lambda chat, text, buttons: self.sent.append((chat, text)), self.state)

    def test_privacy_command(self):
        self.bot.process_updates([msg(1, 7, "/privacy")])
        text = self.sent[-1][1]
        for part in ("Telegram-чат", "вулицю", "зашифровані", "ЄС", "/stop"):
            self.assertIn(part, text)

    def test_stop_deletes_everything_about_the_chat(self):
        self.state.subs["7"] = Subscription(1, 2, "с. Сусли, вул. Центральна", house="12а")
        self.state.sessions["7"] = {"step": "city"}
        self.state.keyboards["7"] = 99
        self.state.seen[chat_tag(7)] = "2026-10-16"
        self.bot.process_updates([msg(1, 7, "/stop")])
        self.assertNotIn("7", self.state.subs)
        self.assertNotIn("7", self.state.sessions)
        self.assertNotIn("7", self.state.keyboards)
        self.assertNotIn(chat_tag(7), self.state.seen)
        self.assertIn("видалила", self.sent[-1][1])

    def test_old_labels_lose_the_house_number(self):
        self.assertEqual(label_without_house("с. Сусли, вул. Центральна 12А", "12а"), "с. Сусли, вул. Центральна")
        self.assertEqual(label_without_house("с. Сусли, вул. Центральна", ""), "с. Сусли, вул. Центральна")
        self.assertEqual(label_without_house("м. Звягель, вул. Героїв Крут", "5"), "м. Звягель, вул. Героїв Крут")
        old = Subscription.from_dict({"queue": 3, "subqueue": 1, "label": "с. Сусли, вул. Центральна 12А",
                                      "house": "12а"})
        self.assertEqual(old.label, "с. Сусли, вул. Центральна")


if __name__ == "__main__":
    unittest.main()
