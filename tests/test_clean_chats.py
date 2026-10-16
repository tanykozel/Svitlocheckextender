import unittest

from svitlo_notifier.bot import CLEAN_AFTER, Bot, BotState, Subscription

HOUR = 3600


class CleanChatsTests(unittest.TestCase):
    """Owner, 16.10: the end user's chat clears itself; Telegram allows deleting only within 48 h."""

    def setUp(self):
        self.next_id = 100
        self.deleted = []
        self.state = BotState()
        self.state.subs["7"] = Subscription(1, 2, "с. Сусли, вул. Центральна")

        def send(chat, text, buttons):
            self.next_id += 1
            return self.next_id

        self.bot = Bot(None, send, self.state,
                       delete=lambda chat, message: self.deleted.append((chat, message)) or True)

    def test_messages_both_ways_are_remembered_and_deleted_after_46_hours(self):
        self.bot.process_updates([{"update_id": 1, "message": {"chat": {"id": 7}, "message_id": 50,
                                                              "text": "/help", "date": 1_000_000}}],
                                 now=1_000_001)
        self.assertEqual([m for m, _ in self.state.history["7"]][0], 50, "the user's message")
        self.assertGreaterEqual(len(self.state.history["7"]), 2, "and Люся's reply")
        start = self.state.history["7"][0][1]
        self.assertEqual(self.bot.clean_chats(now=start + 45 * HOUR), 0, "kept for ~2 days")
        cleaned = self.bot.clean_chats(now=start + CLEAN_AFTER + 60)
        self.assertGreaterEqual(cleaned, 1)
        self.assertIn((7, 50), self.deleted)

    def test_too_old_for_telegram_is_just_forgotten(self):
        self.state.history["7"] = [[11, 0]]
        self.assertEqual(self.bot.clean_chats(now=49 * HOUR), 0)
        self.assertEqual(self.deleted, [], "Telegram would refuse after 48 h")
        self.assertNotIn("7", self.state.history)

    def test_deleted_message_with_buttons_is_no_longer_the_live_keyboard(self):
        self.state.history["7"] = [[11, 0]]
        self.state.keyboards["7"] = 11
        self.bot.clean_chats(now=CLEAN_AFTER + 1)
        self.assertNotIn("7", self.state.keyboards)

    def test_stop_forgets_the_chat_history_too(self):
        self.state.history["7"] = [[11, 0]]
        self.bot.process_updates([{"update_id": 1, "message": {"chat": {"id": 7}, "message_id": 12,
                                                              "text": "/stop", "date": 10}}], now=11)
        self.assertNotIn("7", self.state.history)

    def test_history_survives_save_and_load(self):
        self.state.history["7"] = [[11, 123]]
        self.assertEqual(BotState.from_dict(self.state.to_dict()).history, {"7": [[11, 123]]})


if __name__ == "__main__":
    unittest.main()
