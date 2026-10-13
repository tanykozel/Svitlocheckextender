import io
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from svitlo_notifier import cli
from tests.test_bot import FakeDirectory

_no_network = mock.patch.object(cli, "GpvClient", FakeDirectory)


def setUpModule():
    _no_network.start()  # the bot command must never call the real ZTOE site in tests


def tearDownModule():
    _no_network.stop()


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

    def test_found_chat_id_goes_to_telegram_not_to_public_logs(self):
        sent = []
        code, out = run({"TELEGRAM_BOT_TOKEN": "T", "GITHUB_ACTIONS": "true"},
                        chats=[{"id": 670870052, "type": "private", "first_name": "Tetiana"}], sent=sent)
        self.assertEqual(code, 0)
        self.assertIn("::notice::Found 1 chat(s)", out)
        self.assertNotIn("670870052", out)
        self.assertNotIn("Tetiana", out)
        self.assertEqual(sent[0][1], 670870052)
        self.assertIn("TELEGRAM_CHAT_ID: 670870052", sent[0][2])

    def test_sends_test_message_when_chat_id_set(self):
        sent = []
        code, out = run({"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "42"}, sent=sent)
        self.assertEqual(code, 0)
        self.assertEqual(sent[0][:2], ("T", "42"))
        self.assertNotIn("::", out, "annotations only on GitHub Actions")
        self.assertNotIn("42", out.replace("chat#", ""), "chat id is not logged")

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
                     mock.patch.object(cli, "get_me", return_value={"id": 7, "username": "svitlo_lyusia_zt_bot"}), \
                     mock.patch.object(cli, "get_updates", return_value=[]), \
                     redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["bot", "--state", str(state)]), 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1][0], ("start", "Обрати адресу"))
            from svitlo_notifier.bot import MENU_VERSION
            self.assertEqual(json.loads(state.read_text())["menu_version"], MENU_VERSION)

    def test_bot_writes_dashboard_numbers(self):
        import json
        import tempfile
        from pathlib import Path

        update = {"update_id": 1, "message": {"chat": {"id": 555}, "text": "/help"}}
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "T"}, clear=True), \
             mock.patch.object(cli, "set_commands"), \
             mock.patch.object(cli, "send_message", return_value=None), \
             mock.patch.object(cli, "get_me", return_value={"id": 7, "username": "svitlo_lyusia_zt_bot"}), \
             mock.patch.object(cli, "get_updates", return_value=[update]), \
             redirect_stdout(io.StringIO()):
            metrics = Path(tmp) / "m" / "run.json"
            self.assertEqual(cli.main(["bot", "--state", str(Path(tmp) / "b.json"), "--metrics", str(metrics)]), 0)
            record = json.loads(metrics.read_text())
        self.assertEqual(record["bot"], "svitlo_lyusia_zt_bot")
        self.assertEqual(record["requests"], {"/help": 1})
        self.assertEqual(record["processed"], 1)

    def test_bot_without_token_is_idle_not_failing(self):
        with mock.patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["bot"]), 0)


class StayAwakeTests(unittest.TestCase):
    def test_keeps_long_polling_and_checks_alerts_every_minute(self):
        import tempfile
        from pathlib import Path

        clock = {"t": 0.0}
        waits, alert_checks = [], []

        def fake_updates(*_a, wait=0):
            waits.append(wait)
            clock["t"] += max(wait, 1)  # long polling blocks for `wait` seconds when idle
            return []

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "T"}, clear=True), \
             mock.patch.object(cli, "set_commands"), \
             mock.patch.object(cli, "get_me", return_value={"id": 7, "username": "svitlo_lyusia_zt_bot"}), \
             mock.patch.object(cli, "get_updates", side_effect=fake_updates), \
             mock.patch.object(cli.Bot, "send_alerts", side_effect=lambda *a, **k: alert_checks.append(1) or 0), \
             mock.patch.object(cli.time, "monotonic", side_effect=lambda: clock["t"]), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["bot", "--state", str(Path(tmp) / "b.json"), "--stay-minutes", "3"]), 0)
        self.assertEqual(waits[0], 0, "first read never waits")
        self.assertTrue(all(0 < w <= 25 for w in waits[1:]), waits)
        self.assertGreaterEqual(clock["t"], 170, "stayed awake ~3 minutes")
        self.assertGreaterEqual(len(alert_checks), 4, "start + about once a minute + end")


class BotSwitchTests(unittest.TestCase):
    """Switching to a new bot token (@svitlo_dim_tk_bot -> @Svitlo_Lyusia_zt_bot)."""

    def run_bot(self, state_path, bot_id, username, offsets_seen):
        def updates(_token, offset=None, wait=0):
            offsets_seen.append(offset)
            return []
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "T"}, clear=True), \
             mock.patch.object(cli, "get_me", return_value={"id": bot_id, "username": username}), \
             mock.patch.object(cli, "set_commands"), \
             mock.patch.object(cli, "get_updates", side_effect=updates), \
             redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["bot", "--state", str(state_path)]), 0)
        return out.getvalue()

    def test_new_bot_resets_counter_and_menu_but_keeps_subscriptions(self):
        import tempfile
        from pathlib import Path

        from svitlo_notifier.bot import BotState, Subscription
        from svitlo_notifier.secure import load_json, save_json
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bot.json"
            old = BotState(offset=900_000, bot_id=111, menu_version=5,
                           subs={"42": Subscription(1, 2, "с. Сусли, вул. Гранітна 12")},
                           sessions={"42": {"step": "city"}}, keyboards={"42": 5})
            save_json(path, old.to_dict())
            offsets = []
            out = self.run_bot(path, 222, "svitlo_lyusia_zt_bot", offsets)
            self.assertIn("bot: @svitlo_lyusia_zt_bot", out)
            self.assertIn("New bot detected", out)
            self.assertEqual(offsets[0], None, "old bot's counter is not used with the new bot")
            saved = BotState.from_dict(load_json(path))
            self.assertEqual(saved.bot_id, 222)
            self.assertIn("42", saved.subs, "subscription kept")
            self.assertEqual(saved.sessions, {})
            self.assertEqual(saved.keyboards, {})

            offsets.clear()
            out = self.run_bot(path, 222, "svitlo_lyusia_zt_bot", offsets)
            self.assertNotIn("New bot detected", out, "same bot next time: nothing reset")

    def test_rejected_token_stops_without_touching_state(self):
        import tempfile
        from pathlib import Path

        from svitlo_notifier.telegram import TelegramError
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bad"}, clear=True), \
             mock.patch.object(cli, "get_me", side_effect=TelegramError("getMe rejected: Unauthorized")), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["bot", "--state", str(Path(tmp) / "b.json")]), 1)
            self.assertFalse((Path(tmp) / "b.json").exists())


class GoneChatTests(unittest.TestCase):
    def test_only_people_who_left_are_unsubscribed(self):
        from svitlo_notifier.telegram import TelegramError
        for text in ("Forbidden: bot was blocked by the user", "Forbidden: user is deactivated",
                     "Forbidden: bot was kicked from the group chat"):
            self.assertTrue(cli._telegram_gone(TelegramError(text)), text)

    def test_new_bot_not_started_yet_keeps_the_subscription(self):
        from svitlo_notifier.telegram import TelegramError
        for text in ("Bad Request: chat not found", "Forbidden: bot can't initiate conversation with a user"):
            self.assertFalse(cli._telegram_gone(TelegramError(text)), text)

