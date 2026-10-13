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
