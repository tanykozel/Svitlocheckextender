"""Discovery (owner, 16.10): free-text questions the bot did not understand are kept, masked and anonymous."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from svitlo_notifier.bot import DISCOVERY_KEEP, Bot, BotState, mask_text, text_topics
from svitlo_notifier.cli import main
from svitlo_notifier.secure import save_json
from tests.test_bot import FakeDirectory


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.state = BotState()
        self.bot = Bot(FakeDirectory(), lambda chat, text, buttons: self.sent.append(text) or 1, self.state)

    def test_unknown_question_is_kept_masked_and_without_who_asked(self):
        self.bot.handle_text(424242, "Коли завтра вимкнуть світло на вул. Тестова 12, кв 5? тел 0501234567")
        self.assertEqual(len(self.state.free_texts), 1)
        day, text = self.state.free_texts[0]
        self.assertEqual(text, "Коли завтра вимкнуть світло на вул. Тестова ##, кв #? тел ##########")
        self.assertNotIn("424242", str(self.state.to_dict()["free_texts"]))
        self.assertEqual(self.bot.stats["freetext:schedule"], 1)
        self.assertEqual(self.bot.stats["freetext:address"], 1)
        self.assertIn("не розумію", self.sent[-1], "the reply itself is unchanged")

    def test_quiz_answers_and_commands_are_not_kept(self):
        self.bot.handle_text(1, "/start")
        self.bot.handle_text(1, "Звягельський")  # a quiz answer
        self.bot.handle_text(1, "/unknown")
        self.assertEqual(self.state.free_texts, [])

    def test_links_and_names_are_masked(self):
        self.assertEqual(mask_text("пиши @someone або a@b.ua, https://x.ua/1"), "пиши … або … …")

    def test_only_recent_and_limited(self):
        self.state.free_texts = [["2026-08-01", "old"]] + [["2026-10-15", f"t{i}"] for i in range(DISCOVERY_KEEP)]
        self.bot.note_free_text("new", today="2026-10-16")
        self.assertEqual(len(self.state.free_texts), DISCOVERY_KEEP)
        self.assertNotIn(["2026-08-01", "old"], self.state.free_texts)
        self.assertEqual(self.state.free_texts[-1], ["2026-10-16", "new"])

    def test_topics(self):
        self.assertEqual(text_topics("Дякую!"), ["thanks"])
        self.assertEqual(text_topics("ok"), ["other"])

    def test_kept_across_restarts(self):
        self.bot.handle_text(1, "чому не прийшло повідомлення")
        self.assertEqual(BotState.from_dict(self.state.to_dict()).free_texts, self.state.free_texts)

    def test_owner_report(self):
        self.bot.note_free_text("коли буде світло", today="2099-01-01")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bot.json"
            save_json(path, self.state.to_dict())
            out = io.StringIO()
            with redirect_stdout(out):
                main(["discovery", "--state", str(path), "--days", "100000"])
        self.assertIn("1 free-text message", out.getvalue())
        self.assertIn("2099-01-01  коли буде світло", out.getvalue())


if __name__ == "__main__":
    unittest.main()
