import io
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from svitlo_notifier import cli


def run(env, chats=(), sent=None):
    out = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=True), \
         mock.patch.object(cli, "get_me", return_value={"username": "svitlo_bot", "first_name": "Світло"}), \
         mock.patch.object(cli, "recent_chats", return_value=list(chats)), \
         mock.patch.object(cli, "send_message", side_effect=lambda *a: sent.append(a) if sent is not None else None), \
         redirect_stdout(out):
        code = cli.main(["telegram-setup"])
    return code, out.getvalue()


class TelegramSetupTests(unittest.TestCase):
    def test_no_chats_is_a_warning_not_a_failure(self):
        code, out = run({"TELEGRAM_BOT_TOKEN": "T", "GITHUB_ACTIONS": "true"})
        self.assertEqual(code, 0)
        self.assertIn("::warning::Token works", out)
        self.assertIn("https://t.me/svitlo_bot", out)

    def test_found_chat_id_shown_on_summary(self):
        code, out = run({"TELEGRAM_BOT_TOKEN": "T", "GITHUB_ACTIONS": "true"},
                        chats=[{"id": 42, "type": "private", "first_name": "Test User"}])
        self.assertEqual(code, 0)
        self.assertIn("::notice::Chat found: Tetiana (private) - TELEGRAM_CHAT_ID = 42", out)

    def test_sends_test_message_when_chat_id_set(self):
        sent = []
        code, out = run({"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "42"}, sent=sent)
        self.assertEqual(code, 0)
        self.assertEqual(sent[0][:2], ("T", "42"))
        self.assertNotIn("::", out, "annotations only on GitHub Actions")

    def test_missing_token_fails(self):
        code, _ = run({})
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()


class BotCommandTests(unittest.TestCase):
    def test_menu_is_set_once_and_state_saved(self):
        import json
        import tempfile
        from pathlib import Path

        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "bot.json"
            for _ in range(2):
                with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "T"}, clear=True), \
                     mock.patch.object(cli, "set_commands", side_effect=lambda *a: calls.append(a)), \
                     mock.patch.object(cli, "get_updates", return_value=[]), \
                     redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["bot", "--state", str(state)]), 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1][0], ("start", "Обрати адресу"))
            self.assertEqual(json.loads(state.read_text())["menu_version"], 1)

    def test_bot_without_token_is_idle_not_failing(self):
        with mock.patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["bot"]), 0)


class StayAwakeTests(unittest.TestCase):
    def test_keeps_long_polling_until_time_is_up(self):
        import tempfile
        from pathlib import Path

        waits = []
        clock = iter([0, 0, 10, 20, 31, 100])  # monotonic seconds, consumed by the loop
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "T"}, clear=True), \
             mock.patch.object(cli, "set_commands"), \
             mock.patch.object(cli, "get_updates", side_effect=lambda *a, wait=0: waits.append(wait) or []), \
             mock.patch.object(cli.time, "monotonic", side_effect=lambda: next(clock)), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["bot", "--state", str(Path(tmp) / "b.json"), "--stay-minutes", "0.6"]), 0)
        self.assertEqual(waits[0], 0, "first read never waits")
        self.assertTrue(all(0 < w <= 25 for w in waits[1:]), waits)
        self.assertGreaterEqual(len(waits), 3)
